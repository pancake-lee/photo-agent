package service

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
)

const importStageDirectory = ".import-review"

var importStageFiles sync.RWMutex
var importStagePreparation = make(chan struct{}, min(runtime.GOMAXPROCS(0), 4))

func validReviewBatchID(id string) bool {
	_, err := hex.DecodeString(id)
	return len(id) == 32 && err == nil
}

func importStageLocation(batchID, digest string) (string, string, error) {
	if !validReviewBatchID(batchID) || !validArchiveDigest(digest) {
		return "", "", fmt.Errorf("无效的暂存批次或 JPG 摘要")
	}
	root := filepath.Join(conf.C.Storage.PhotoSrc, importStageDirectory)
	for _, dir := range []string{root, filepath.Join(root, batchID)} {
		info, err := os.Lstat(dir)
		if os.IsNotExist(err) {
			break
		}
		if err != nil {
			return "", "", err
		}
		if !info.IsDir() {
			return "", "", fmt.Errorf("暂存位置不是目录: %s", dir)
		}
	}
	return root, filepath.Join(batchID, digest+".jpg"), nil
}

func importStageReady(batchID, digest string) (bool, error) {
	root, target, err := importStageLocation(batchID, digest)
	if err != nil {
		return false, err
	}
	actual, _, err := digestFile(filepath.Join(root, target))
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if actual != digest {
		return false, fmt.Errorf("服务器暂存 JPG 摘要不符: %s", target)
	}
	return true, nil
}

func getImportStage(req archiveImportRequest) (archiveImportResult, error) {
	root, target, err := importStageLocation(req.BatchID, req.JPG)
	result := archiveImportResult{Root: root, Target: target}
	if err != nil {
		return result, err
	}
	start := time.Now()
	result.JPGStaged, err = importStageReady(req.BatchID, req.JPG)
	req.trace.add("verify_staged_jpg", start, 0)
	return result, err
}

func (s *PhotoServer) importStageStatus(ctx khttp.Context) error {
	var req archiveImportRequest
	err := ctx.Bind(&req)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
	req.trace = startPhotoImportTrace(ctx, req.BatchID, "stage_status")
	defer func() { req.trace.finish(err, nil) }()
	result, err := getImportStage(req)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	return ctx.Result(http.StatusOK, result)
}

func (s *PhotoServer) writeImportStage(ctx khttp.Context) error {
	req, file, err := readArchiveMultipart(ctx)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
	if file.FormName() != "jpg" || !req.valid() || req.NEF != "" {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": "暂存仅接收有效的 JPG"})
	}
	req.trace = startPhotoImportTrace(ctx, req.BatchID, "stage_upload")
	defer func() { req.trace.finish(err, nil) }()
	result, err := saveStagedImport(req, file)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	prepareStagedImport(ctx.Request().Context(), filepath.Join(result.Root, result.Target), req.trace)
	return ctx.Result(http.StatusOK, result)
}

func saveStagedImport(req archiveImportRequest, file io.Reader) (archiveImportResult, error) {
	importStageFiles.RLock()
	defer importStageFiles.RUnlock()
	result, err := getImportStage(req)
	if err != nil || result.JPGStaged {
		return result, err
	}
	err = writeVerifiedArchiveFile(result.Root, result.Target, req.JPG, req.JPGTime, file, nil, req.trace)
	if err != nil && !os.IsExist(err) {
		return result, err
	}
	return getImportStage(req)
}

func prepareStagedImport(ctx context.Context, source string, trace *photoImportTrace) {
	wait := time.Now()
	defer func() { trace.add("preview_slot_wait", wait, 0) }()
	select {
	case importStagePreparation <- struct{}{}:
	case <-ctx.Done():
		return
	}
	prep := trace.fork("stage_prepare_preview")
	go func() {
		var err error
		defer func() { prep.finish(err, nil) }()
		defer func() { <-importStagePreparation }()
		importStageFiles.RLock()
		defer importStageFiles.RUnlock()
		info, err := os.Lstat(source)
		if err != nil {
			return
		}
		if !info.Mode().IsRegular() {
			err = fmt.Errorf("暂存 JPG 不是普通文件")
			return
		}
		work, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		// Requests for an uncached preview or grouping can retry the same work.
		start := time.Now()
		_, thumbErr := stagedImportThumbnail(work, source, prep)
		prep.add("thumbnail", start, 0)
		start = time.Now()
		_, grayErr := stagedImportGray(work, source, prep)
		prep.add("gray_feature", start, 0)
		err = errors.Join(thumbErr, grayErr)
	}()
}

func stagedImportGray(ctx context.Context, source string, trace *photoImportTrace) ([]float64, error) {
	start := time.Now()
	target := source + ".gray.json"
	var gray []float64
	raw, err := os.ReadFile(target)
	if err == nil && json.Unmarshal(raw, &gray) == nil && len(gray) == burstGrayW*burstGrayH {
		trace.add("gray_cache_hit", start, 0)
		return gray, nil
	}
	start = time.Now()
	gray, err = loadGrayMatrixContext(ctx, source)
	trace.add("gray_generate", start, 0)
	if err != nil {
		return nil, err
	}
	temp, err := os.CreateTemp(filepath.Dir(target), ".gray-*.tmp")
	if err != nil {
		return gray, nil
	}
	defer os.Remove(temp.Name())
	encodeErr := json.NewEncoder(temp).Encode(gray)
	closeErr := temp.Close()
	if encodeErr == nil && closeErr == nil {
		_ = os.Rename(temp.Name(), target)
	}
	return gray, nil
}

func (s *PhotoServer) cleanupImportStage(ctx khttp.Context) error {
	var req struct {
		BatchID string `json:"batch_id"`
	}
	ctx.Request().Body = http.MaxBytesReader(ctx.Response(), ctx.Request().Body, 4096)
	err := ctx.Bind(&req)
	if err != nil || !validReviewBatchID(req.BatchID) {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": "无效的暂存批次"})
	}
	importStageFiles.Lock()
	defer importStageFiles.Unlock()
	importReviewBurstJobs.Lock()
	defer importReviewBurstJobs.Unlock()
	for _, job := range importReviewBurstJobs.jobs {
		if job.batchID == req.BatchID && job.State == "running" {
			return apiPhotoArchiveError(ctx, fmt.Errorf("请等待本批次连拍计算结束"))
		}
	}
	err = removeImportStage(req.BatchID)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	return ctx.Result(http.StatusOK, map[string]bool{"cleaned": true})
}

func removeImportStage(batchID string) error {
	if !validReviewBatchID(batchID) {
		return fmt.Errorf("无效的暂存批次")
	}
	if conf.C.Storage.PhotoSrc == "" {
		return fmt.Errorf("服务器未配置照片存储目录")
	}
	root := filepath.Join(conf.C.Storage.PhotoSrc, importStageDirectory)
	info, err := os.Lstat(root)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	if !info.IsDir() {
		return fmt.Errorf("暂存位置不是目录")
	}
	return os.RemoveAll(filepath.Join(root, batchID))
}

func (s *PhotoServer) importStageImage(ctx khttp.Context) error {
	query := ctx.Request().URL.Query()
	digest := query.Get("sha256")
	root, target, err := importStageLocation(query.Get("batch_id"), digest)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
	path := filepath.Join(root, target)
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() {
		return ctx.Result(http.StatusNotFound, map[string]string{"error": "暂存 JPG 不存在"})
	}
	ctx.Response().Header().Set("Cache-Control", "no-store")
	if query.Get("size") == "thumbnail" {
		trace := startPhotoImportTrace(ctx, query.Get("batch_id"), "stage_preview_on_demand")
		importStageFiles.RLock()
		thumbnail, err := stagedImportThumbnail(ctx.Request().Context(), path, trace)
		importStageFiles.RUnlock()
		if trace.spans["thumbnail_cache_hit"].Count == 0 {
			trace.finish(err, nil)
		}
		if err == nil {
			ctx.Response().Header().Set("Cache-Control", "private, max-age=3600")
			path = thumbnail
		}
	}
	http.ServeFile(ctx.Response(), ctx.Request(), path)
	return nil
}

func stagedImportThumbnail(ctx context.Context, source string, trace *photoImportTrace) (string, error) {
	start := time.Now()
	dir := filepath.Join(filepath.Dir(source), "thumbnails")
	err := os.Mkdir(dir, 0755)
	if err != nil && !os.IsExist(err) {
		return "", err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return "", err
	}
	if !info.IsDir() {
		return "", fmt.Errorf("批次缩图位置不是目录")
	}
	target := filepath.Join(dir, filepath.Base(source))
	info, err = os.Lstat(target)
	if err == nil && info.Mode().IsRegular() {
		trace.add("thumbnail_cache_hit", start, 0)
		return target, nil
	}

	temp, err := os.CreateTemp(dir, ".preview-*.jpg")
	if err != nil {
		return "", err
	}
	defer os.Remove(temp.Name())
	err = temp.Close()
	if err != nil {
		return "", err
	}
	thumbnailCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 8*time.Second)
	defer cancel()
	cmd := exec.CommandContext(thumbnailCtx, "convert", source, "-auto-orient",
		"-resize", "512x512>", "-strip", "-quality", "82", temp.Name())
	start = time.Now()
	err = cmd.Run()
	trace.add("thumbnail_generate", start, 0)
	if err != nil {
		return "", err
	}
	err = os.Rename(temp.Name(), target)
	return target, err
}

func (s *PhotoServer) archiveStagedJPG(ctx khttp.Context) error {
	return importArchiveJSON(ctx, "stage_archive", func(app *papp.AppCtx, req archiveImportRequest) (archiveImportResult, error) {
		importStageFiles.RLock()
		defer importStageFiles.RUnlock()
		result, _, err := resolveArchiveImport(app, req)
		if err != nil {
			return result, err
		}
		if req.Target != result.Target {
			return result, fmt.Errorf("归档位置已变化，请刷新预览")
		}
		if result.JPGReady {
			return result, nil
		}
		if !result.JPGStaged {
			return result, fmt.Errorf("请先暂存 JPG")
		}
		root, target, err := importStageLocation(req.BatchID, req.JPG)
		if err != nil {
			return result, err
		}
		input, err := os.Open(filepath.Join(root, target))
		if err != nil {
			return result, err
		}
		defer input.Close()
		reserve := func() error { return data.PhotoDAO.ReserveImportTarget(app, req.key(), result.Target) }
		err = writeVerifiedArchiveFile(result.Root, result.Target, req.JPG, req.JPGTime, input, reserve, req.trace)
		if err != nil {
			return result, err
		}
		result, _, err = resolveArchiveImport(app, req)
		return result, err
	})
}

package service

import (
	"encoding/hex"
	"fmt"
	"net/http"
	"os"
	"path/filepath"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
)

const importStageDirectory = ".import-review"

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
	result.JPGStaged, err = importStageReady(req.BatchID, req.JPG)
	return result, err
}

func (s *PhotoServer) importStageStatus(ctx khttp.Context) error {
	var req archiveImportRequest
	err := ctx.Bind(&req)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
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
	result, err := getImportStage(req)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	if !result.JPGStaged {
		err = writeVerifiedArchiveFile(result.Root, result.Target, req.JPG, req.JPGTime, file, nil)
		if err != nil && !os.IsExist(err) {
			return apiPhotoArchiveError(ctx, err)
		}
		result, err = getImportStage(req)
		if err != nil {
			return apiPhotoArchiveError(ctx, err)
		}
	}
	return ctx.Result(http.StatusOK, result)
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
	http.ServeFile(ctx.Response(), ctx.Request(), path)
	return nil
}

func (s *PhotoServer) archiveStagedJPG(ctx khttp.Context) error {
	return importArchiveJSON(ctx, func(app *papp.AppCtx, req archiveImportRequest) (archiveImportResult, error) {
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
		err = writeVerifiedArchiveFile(result.Root, result.Target, req.JPG, req.JPGTime, input, reserve)
		if err != nil {
			return result, err
		}
		result, _, err = resolveArchiveImport(app, req)
		return result, err
	})
}

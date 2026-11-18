package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"image/jpeg"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"
)

// The shared HTTP timeout is for short requests. File hashing and journal
// operations need a separate budget, while HTTP body I/O still detects a
// closed connection.
const archiveOperationTimeout = 10 * time.Minute

func archiveOperationContext(ctx context.Context) (*papp.AppCtx, context.CancelFunc) {
	operation, cancel := context.WithTimeout(context.WithoutCancel(ctx), archiveOperationTimeout)
	return papp.NewAppCtx(operation), cancel
}

var photoArchiveMu sync.Mutex

type photoImportSpan struct {
	Count int     `json:"count"`
	MS    float64 `json:"ms"`
	MaxMS float64 `json:"max_ms"`
	Bytes int64   `json:"bytes,omitempty"`
}

type photoImportTrace struct {
	batchID, requestID, phase string
	start                     time.Time
	spans                     map[string]photoImportSpan
}

func startPhotoImportTrace(ctx khttp.Context, batchID, phase string) *photoImportTrace {
	if !validReviewBatchID(batchID) {
		batchID = ctx.Request().Header.Get("X-Photo-Import-Batch-ID")
		if !validReviewBatchID(batchID) {
			batchID = ""
		}
	}
	requestID := ctx.Request().Header.Get("X-Photo-Import-Request-ID")
	if !validReviewBatchID(requestID) {
		requestID = putil.UUID()
	}
	ctx.Response().Header().Set("X-Photo-Import-Request-ID", requestID)
	return (&photoImportTrace{batchID: batchID, requestID: requestID}).fork(phase)
}

func (t *photoImportTrace) fork(phase string) *photoImportTrace {
	return &photoImportTrace{batchID: t.batchID, requestID: t.requestID, phase: phase,
		start: time.Now(), spans: make(map[string]photoImportSpan)}
}

func (t *photoImportTrace) add(name string, start time.Time, bytes int64) {
	if t == nil {
		return
	}
	span := t.spans[name]
	ms := float64(time.Since(start).Microseconds()) / 1000
	span.Count++
	span.MS += ms
	span.MaxMS = max(span.MaxMS, ms)
	span.Bytes += bytes
	t.spans[name] = span
}

func (t *photoImportTrace) finish(err error, fields map[string]any) {
	if fields == nil {
		fields = make(map[string]any)
	}
	fields["side"], fields["batch_id"], fields["request_id"] = "server", t.batchID, t.requestID
	fields["phase"], fields["spans"] = t.phase, t.spans
	fields["duration_ms"] = float64(time.Since(t.start).Microseconds()) / 1000
	fields["started_at"] = t.start.UTC()
	outcome := "ok"
	if errors.Is(err, context.Canceled) {
		outcome = "canceled"
	} else if errors.Is(err, context.DeadlineExceeded) {
		outcome = "timeout"
	} else if err != nil {
		outcome = "error"
	} else if failed, _ := fields["failed"].(int); failed > 0 {
		outcome = "partial"
	}
	fields["outcome"] = outcome
	raw, err := json.Marshal(fields)
	if err == nil {
		plogger.Infof("import.trace %s", raw)
	}
}

type archiveImportRequest struct {
	activityNormalized bool
	ActivityID         string     `json:"activity_id,omitempty"`
	PhotoID            string     `json:"photo_id,omitempty"`
	BatchID            string     `json:"batch_id,omitempty"`
	Activity           string     `json:"activity"`
	Name               string     `json:"name"`
	JPG                string     `json:"jpg_sha256"`
	NEF                string     `json:"nef_sha256,omitempty"`
	Favorite           bool       `json:"favorite"`
	ShotAt             *time.Time `json:"shot_at,omitempty"`
	JPGTime            time.Time  `json:"jpg_time"`
	NEFTime            *time.Time `json:"nef_time,omitempty"`
	Target             string     `json:"target,omitempty"`
	trace              *photoImportTrace
}

type archiveImportResult struct {
	ActivityID string `json:"activity_id,omitempty"`
	Activity   string `json:"activity,omitempty"`
	JPGStaged  bool   `json:"jpg_staged,omitempty"`
	Target     string `json:"target"`
	NEFTarget  string `json:"nef_target,omitempty"`
	Root       string `json:"root"`
	JPGReady   bool   `json:"jpg_ready"`
	NEFReady   bool   `json:"nef_ready"`
	Verified   bool   `json:"verified"`
	PhotoID    string `json:"photo_id,omitempty"`
}

func archiveComponent(value string) bool {
	return value != "" && len(value) <= 180 && !strings.HasPrefix(value, ".") &&
		!strings.HasSuffix(value, ".") && strings.TrimSpace(value) == value &&
		!strings.ContainsAny(value, "/\\:*?\"<>|\x00\n\r\t")
}

func validArchiveDigest(value string) bool {
	digest, err := hex.DecodeString(value)
	return err == nil && len(digest) == sha256.Size && value == strings.ToLower(value)
}

func (req archiveImportRequest) valid() bool {
	return archiveComponent(req.Activity) && archiveComponent(req.Name) &&
		req.JPGTime.Unix() > 0 && validArchiveDigest(req.JPG) &&
		(req.NEF == "" || validArchiveDigest(req.NEF) && req.NEFTime != nil &&
			req.NEFTime.Unix() > 0)
}

func (req archiveImportRequest) key() string {
	return data.ArchiveImportKey(req.Activity, req.JPG, req.NEF)
}

func digestFile(path string) (string, int64, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return "", 0, err
	}
	if !info.Mode().IsRegular() {
		return "", 0, fmt.Errorf("路径不是普通文件: %s", path)
	}
	file, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer file.Close()
	digest := sha256.New()
	size, err := io.Copy(digest, file)
	return hex.EncodeToString(digest.Sum(nil)), size, err
}

func archiveSafeDir(root, folder string) error {
	if folder == "" {
		return nil
	}
	if !archiveComponent(folder) {
		return fmt.Errorf("无效归档目录 %q", folder)
	}
	info, err := os.Lstat(filepath.Join(root, folder))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	if !info.IsDir() {
		return fmt.Errorf("归档路径不是目录: %s", folder)
	}
	return nil
}

func archiveFileAt(root, rel string) (string, error) {
	dir, name := filepath.Split(rel)
	folder := strings.TrimSuffix(dir, string(filepath.Separator))
	if !filepath.IsLocal(rel) || !archiveComponent(name) {
		return "", fmt.Errorf("无效归档文件路径 %q", rel)
	}
	if folder != "" {
		err := archiveSafeDir(root, folder)
		if err != nil {
			return "", err
		}
	}
	actual, err := caseInsensitiveFileName(filepath.Join(root, folder), name)
	if err != nil {
		return "", err
	}
	if actual == "" {
		return "", nil
	}
	return filepath.Join(folder, actual), nil
}

func archiveFileState(root, rel, want string) (present, matching bool, err error) {
	actual, err := archiveFileAt(root, rel)
	if err != nil || actual == "" {
		return false, false, err
	}
	digest, _, err := digestFile(filepath.Join(root, actual))
	if err != nil {
		return true, false, err
	}
	return true, digest == want, nil
}

func resolveArchiveImport(
	ctx *papp.AppCtx, req archiveImportRequest,
) (archiveImportResult, *data.PhotoDO, error) {
	start := time.Now()
	defer func() { req.trace.add("resolve_archive", start, 0) }()
	result := archiveImportResult{Root: conf.C.Storage.PhotoSrc, NEFReady: req.NEF == ""}
	if !req.valid() {
		return result, nil, fmt.Errorf("导入清单无效")
	}
	err := normalizeArchiveActivity(ctx, &req)
	if err != nil {
		return result, nil, err
	}
	result.ActivityID, result.Activity = req.ActivityID, req.Activity
	state, err := data.PhotoDAO.FindArchivedImport(ctx, req.key())
	if err != nil {
		return result, nil, err
	}
	if state == nil {
		state, err = data.PhotoDAO.FindCompatibleArchivedImport(ctx, req.Activity, req.JPG, req.NEF)
		if err != nil {
			return result, nil, err
		}
	}
	base := strings.TrimSuffix(sanitizeFilename(req.Name, ".jpg"), ".jpg")
	if len(base) > 110 {
		base = base[:110]
	}
	var preferred string
	reservation, err := data.PhotoDAO.FindImportReservation(ctx, req.key(), "")
	if err != nil {
		return result, nil, err
	}
	if reservation != nil {
		preferred = reservation.Target
	}
	if state != nil {
		photo, err := data.PhotoDAO.GetByID(ctx, state.PhotoID)
		if err != nil {
			return result, nil, fmt.Errorf("此导入记录对应的照片位于最近删除或已移除")
		}
		preferred = photo.FilePath
	}
	for n := 0; n < 100; n++ {
		filename := base + ".jpg"
		if n == 1 {
			filename = base + "_" + req.key()[:12] + ".jpg"
		} else if n > 1 {
			filename = fmt.Sprintf("%s_%s_%d.jpg", base, req.key()[:12], n)
		}
		target := filepath.Join(req.Activity, filename)
		if req.Target != "" {
			target = req.Target
			if filepath.Dir(target) != req.Activity || !strings.EqualFold(filepath.Ext(target), ".jpg") {
				return result, nil, fmt.Errorf("导入目标不在该活动内")
			}
		}
		if preferred != "" {
			target = preferred
		}
		busy, err := data.PhotoDAO.FindImportReservation(ctx, "", target)
		if err != nil {
			return result, nil, err
		}
		if busy != nil && busy.ImportKey != req.key() {
			if req.Target != "" || preferred != "" {
				return result, nil, fmt.Errorf("归档位置由另一份未完成清单占用: %s", target)
			}
			continue
		}
		photo, err := data.PhotoDAO.FindByArchivePath(ctx, target)
		if err != nil {
			return result, nil, err
		}
		actual, err := archiveFileAt(conf.C.Storage.PhotoSrc, target)
		if err != nil {
			return result, nil, err
		}
		if actual != "" {
			target = actual
		}
		check := time.Now()
		jpgPresent, jpgReady, err := archiveFileState(conf.C.Storage.PhotoSrc, target, req.JPG)
		req.trace.add("verify_archive_jpg", check, 0)
		if err != nil {
			return result, nil, err
		}
		nefTarget := strings.TrimSuffix(target, filepath.Ext(target)) + ".nef"
		check = time.Now()
		nefPresent, nefReady, err := archiveFileState(conf.C.Storage.PhotoSrc, nefTarget, req.NEF)
		req.trace.add("verify_archive_nef", check, 0)
		if err != nil {
			return result, nil, err
		}
		// A NEF-only position is reserved only after a matching JPG has landed.
		conflict := (jpgPresent && !jpgReady) || (nefPresent && (!jpgReady || req.NEF != "" && !nefReady)) ||
			(photo != nil && (photo.Timeline != req.Activity || !jpgReady))
		if photo != nil && state == nil {
			prior, stateErr := data.PhotoDAO.GetArchiveState(ctx, photo.ID)
			if stateErr != nil {
				return result, nil, stateErr
			}
			compatible := prior.JPGSHA256 == req.JPG && (req.NEF == "" || prior.NEFSHA256 == "" || prior.NEFSHA256 == req.NEF)
			conflict = conflict || prior.ImportKey != "" && prior.ImportKey != req.key() && !compatible
		}
		if conflict {
			if preferred != "" || req.Target != "" {
				return result, nil, fmt.Errorf("已归档文件与导入清单不一致: %s", target)
			}
			continue
		}
		result.Target, result.JPGReady = target, jpgReady
		if req.NEF != "" {
			result.NEFTarget, result.NEFReady = nefTarget, nefReady
		}
		if photo != nil {
			result.PhotoID = photo.ID
		}
		thumbPresent, err := archiveFileAt(conf.C.Storage.PhotoPath, target)
		if err != nil {
			return result, nil, err
		}
		result.Verified = state != nil && photo != nil && jpgReady && result.NEFReady && thumbPresent != "" && (req.NEF == "" || state.NEFSHA256 == req.NEF)
		if req.BatchID != "" && !jpgReady {
			check := time.Now()
			result.JPGStaged, err = importStageReady(req.BatchID, req.JPG)
			req.trace.add("verify_staged_jpg", check, 0)
			if err != nil {
				return result, nil, err
			}
		}
		return result, photo, nil
	}
	return result, nil, fmt.Errorf("无法分配归档文件名")
}

func importArchiveJSON(
	ctx khttp.Context, phase string, execute func(*papp.AppCtx, archiveImportRequest) (archiveImportResult, error),
) error {
	var req archiveImportRequest
	err := ctx.Bind(&req)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
	req.trace = startPhotoImportTrace(ctx, req.BatchID, phase)
	defer func() { req.trace.finish(err, nil) }()
	wait := time.Now()
	photoArchiveMu.Lock()
	req.trace.add("archive_lock_wait", wait, 0)
	defer photoArchiveMu.Unlock()
	app, cancel := archiveOperationContext(ctx.Request().Context())
	defer cancel()
	err = normalizeArchiveActivity(app, &req)
	if err != nil {
		return ctx.Result(http.StatusConflict, map[string]string{"error": err.Error()})
	}
	result, err := execute(app, req)
	if err != nil {
		return ctx.Result(http.StatusConflict, map[string]string{"error": err.Error()})
	}
	return ctx.Result(http.StatusOK, result)
}

func (s *PhotoServer) previewArchiveImport(ctx khttp.Context) error {
	return importArchiveJSON(ctx, "archive_preview", func(app *papp.AppCtx, req archiveImportRequest) (archiveImportResult, error) {
		result, _, err := resolveArchiveImport(app, req)
		return result, err
	})
}

func writeVerifiedArchiveFile(
	root, target, want string, mtime time.Time, reader io.Reader, reserve func() error, trace *photoImportTrace,
) error {
	dir := filepath.Join(root, filepath.Dir(target))
	err := os.MkdirAll(dir, 0755)
	if err != nil {
		return err
	}
	temp, err := os.CreateTemp(dir, ".import-*")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	digest := sha256.New()
	start := time.Now()
	bytes, err := io.Copy(io.MultiWriter(temp, digest), reader)
	trace.add("stream_hash_write", start, bytes)
	if err == nil && hex.EncodeToString(digest.Sum(nil)) != want {
		err = fmt.Errorf("文件摘要不符: %s", target)
	}
	if err == nil && strings.EqualFold(filepath.Ext(target), ".jpg") {
		_, err = temp.Seek(0, io.SeekStart)
		if err == nil {
			_, err = jpeg.DecodeConfig(temp)
		}
	}
	if err == nil {
		start = time.Now()
		err = temp.Sync()
		trace.add("file_sync", start, 0)
	}
	err = errors.Join(err, temp.Close())
	if err != nil {
		return err
	}
	err = os.Chtimes(temp.Name(), mtime, mtime)
	if err != nil {
		return err
	}
	if reserve != nil {
		start = time.Now()
		err = reserve()
		trace.add("reserve_path", start, 0)
		if err != nil {
			return err
		}
	}
	dest := filepath.Join(root, target)
	start = time.Now()
	err = os.Link(temp.Name(), dest)
	trace.add("publish_file", start, 0)
	return err
}

func readArchiveMultipart(ctx khttp.Context) (archiveImportRequest, *multipart.Part, error) {
	var req archiveImportRequest
	request := ctx.Request()
	request.Body = http.MaxBytesReader(ctx.Response(), request.Body, 2<<30)
	reader, err := request.MultipartReader()
	if err != nil {
		return req, nil, err
	}
	info, err := reader.NextPart()
	if err != nil || info.FormName() != "manifest" {
		return req, nil, fmt.Errorf("缺少导入清单")
	}
	err = json.NewDecoder(io.LimitReader(info, 8192)).Decode(&req)
	if err != nil {
		return req, nil, err
	}
	file, err := reader.NextPart()
	if err != nil {
		return req, nil, fmt.Errorf("缺少上传文件")
	}
	return req, file, nil
}

func (s *PhotoServer) writeArchiveImport(ctx khttp.Context) error {
	req, file, err := readArchiveMultipart(ctx)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}

	req.trace = startPhotoImportTrace(ctx, req.BatchID, "archive_file")
	defer func() { req.trace.finish(err, nil) }()
	wait := time.Now()
	photoArchiveMu.Lock()
	req.trace.add("archive_lock_wait", wait, 0)
	defer photoArchiveMu.Unlock()
	app, cancel := archiveOperationContext(ctx.Request().Context())
	defer cancel()
	err = normalizeArchiveActivity(app, &req)
	if err != nil {
		return ctx.Result(http.StatusConflict, map[string]string{"error": err.Error()})
	}
	result, _, err := resolveArchiveImport(app, req)
	if err == nil && req.Target != result.Target {
		err = fmt.Errorf("归档位置已变化，请刷新预览")
	}
	if err == nil {
		reserve := func() error {
			return data.PhotoDAO.ReserveImportTarget(app, req.key(), result.Target)
		}
		switch file.FormName() {
		case "jpg":
			if !result.JPGReady {
				err = writeVerifiedArchiveFile(result.Root, result.Target, req.JPG, req.JPGTime, file, reserve, req.trace)
			}
		case "nef":
			if !result.JPGReady || result.NEFTarget == "" {
				err = fmt.Errorf("请先上传配对的 JPG 并提供 NEF 清单")
			} else if !result.NEFReady {
				err = writeVerifiedArchiveFile(result.Root, result.NEFTarget, req.NEF, *req.NEFTime, file, reserve, req.trace)
			}
		default:
			err = fmt.Errorf("未知上传文件类型")
		}
	}
	if err != nil {
		return ctx.Result(http.StatusConflict, map[string]string{"error": err.Error()})
	}
	result, _, err = resolveArchiveImport(app, req)
	if err != nil {
		return ctx.Result(http.StatusConflict, map[string]string{"error": err.Error()})
	}
	return ctx.Result(http.StatusOK, result)
}

func (s *PhotoServer) finishArchiveImport(ctx khttp.Context) error {
	return importArchiveJSON(ctx, "archive_finish", finishVerifiedArchive)
}

func finishVerifiedArchive(ctx *papp.AppCtx, req archiveImportRequest) (archiveImportResult, error) {
	err := normalizeArchiveActivity(ctx, &req)
	if err != nil {
		return archiveImportResult{}, err
	}
	result, row, err := resolveArchiveImport(ctx, req)
	if err != nil {
		return result, err
	}
	if req.Target != result.Target || !result.JPGReady || !result.NEFReady {
		return result, fmt.Errorf("归档位置已变化或文件尚未核验")
	}
	if result.Verified {
		if req.Favorite {
			err = data.PhotoDAO.SetArchiveFavorite(ctx, row.ID, true)
			if err != nil {
				return result, err
			}
		}
		return result, nil
	}
	existing := row != nil
	base := filepath.Base(result.Target)
	folder := filepath.Dir(result.Target)
	preview := filepath.Join(conf.C.Storage.PhotoPath, result.Target)
	_, statErr := os.Stat(preview)
	if filepath.Clean(result.Root) != filepath.Clean(conf.C.Storage.PhotoPath) &&
		(!existing || os.IsNotExist(statErr)) {
		err = archiveSafeDir(conf.C.Storage.PhotoPath, folder)
		if err != nil {
			return result, err
		}
		thumbDir := filepath.Join(conf.C.Storage.PhotoPath, folder)
		limit := int64(conf.C.VLM.MaxImageSizeMB * 1024 * 1024)
		start := time.Now()
		err = processToPhotoPath(filepath.Join(result.Root, result.Target),
			base, thumbDir, limit, &req.JPGTime)
		req.trace.add("archive_thumbnail", start, 0)
		if err != nil {
			return result, err
		}
	}
	if !existing {
		row = newPhotoRecord(ctx, putil.UUID(), base, folder, "jpg", req.ShotAt)
		meta, metadataErr := readActivityMetadata(req.Activity)
		if metadataErr != nil {
			return result, metadataErr
		}
		row.ActivityID = meta.ID
		row.Timeline, row.TimelineManual = req.Activity, 0
	}

	state := data.PhotoArchiveDO{
		PhotoID: row.ID, ImportKey: req.key(), Favorite: req.Favorite,
		JPGSHA256: req.JPG, NEFSHA256: req.NEF,
	}
	if existing {
		prior, stateErr := data.PhotoDAO.GetArchiveState(ctx, row.ID)
		if stateErr != nil {
			return result, stateErr
		}
		state.Favorite = state.Favorite || prior.Favorite
		if req.NEF == "" {
			state.NEFSHA256 = prior.NEFSHA256
			state.ImportKey = data.ArchiveImportKey(req.Activity, req.JPG, state.NEFSHA256)
		}
	}
	start := time.Now()
	err = data.PhotoDAO.SaveVerifiedImport(ctx, row, state, existing)
	req.trace.add("save_photo", start, 0)
	if err != nil {
		return result, err
	}
	result.Verified, result.PhotoID = true, row.ID
	return result, nil
}

package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"
)

const photoRecycleRetention = 30 * 24 * time.Hour

type archivedFile struct {
	Original string `json:"original"`
	Restore  string `json:"restore,omitempty"`
	SHA256   string `json:"sha256"`
	Bytes    int64  `json:"bytes"`
	Preview  bool   `json:"preview,omitempty"`
}

type recyclePhotoView struct {
	ID        string     `json:"id"`
	PhotoID   string     `json:"photo_id"`
	Kind      string     `json:"kind"`
	State     string     `json:"state"`
	Activity  string     `json:"activity"`
	Name      string     `json:"name"`
	DeletedAt *time.Time `json:"deleted_at,omitempty"`
	ExpiresAt *time.Time `json:"expires_at,omitempty"`
	Error     string     `json:"error,omitempty"`
}

type nefCleanupCandidate struct {
	ID     string `json:"id"`
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Bytes  int64  `json:"bytes"`
}

func recycleRoot() string {
	return filepath.Join(conf.C.Storage.PhotoSrc, ".recently-deleted")
}

func archivedSource(file archivedFile, rel string) string {
	root := conf.C.Storage.PhotoSrc
	if file.Preview {
		root = conf.C.Storage.PhotoPath
	}
	return filepath.Join(root, rel)
}

func recycleFilePath(recordID string, file archivedFile) string {
	kind := "original"
	if file.Preview {
		kind = "preview"
	}
	root := recycleRoot()
	if file.Preview {
		root = filepath.Join(conf.C.Storage.PhotoPath, ".recently-deleted")
	}
	return filepath.Join(root, recordID, kind, filepath.Base(file.Original))
}

func recycleData(item *data.PhotoRecycleDO) (*data.PhotoDO, []archivedFile, error) {
	var row data.PhotoDO
	err := json.Unmarshal(item.PhotoJSON, &row)
	if err != nil {
		return nil, nil, err
	}
	var files []archivedFile
	err = json.Unmarshal(item.FilesJSON, &files)
	return &row, files, err
}

func fileForRecycle(root, rel string, preview bool) (archivedFile, error) {
	entry := archivedFile{Original: rel, Preview: preview}
	digest, size, err := digestFile(filepath.Join(root, rel))
	entry.SHA256, entry.Bytes = digest, size
	return entry, err
}

func photoPairNEF(ctx *papp.AppCtx, photo *data.PhotoDO) (archivedFile, error) {
	rel := strings.TrimSuffix(photo.FilePath, filepath.Ext(photo.FilePath)) + ".nef"
	actual, err := archiveFileAt(conf.C.Storage.PhotoSrc, rel)
	if err != nil || actual == "" {
		return archivedFile{}, err
	}
	file, err := fileForRecycle(conf.C.Storage.PhotoSrc, actual, false)
	if err != nil {
		return archivedFile{}, err
	}
	state, err := data.PhotoDAO.GetArchiveState(ctx, photo.ID)
	if err != nil {
		return archivedFile{}, err
	}
	if state.JPGSHA256 == "" {
		for _, ext := range []string{".jpg", ".jpeg"} {
			other := strings.TrimSuffix(photo.FilePath, filepath.Ext(photo.FilePath)) + ext
			if strings.EqualFold(photo.FilePath, other) {
				continue
			}
			row, lookupErr := data.PhotoDAO.FindByArchivePath(ctx, other)
			if lookupErr != nil {
				return archivedFile{}, lookupErr
			}
			if row != nil {
				return archivedFile{}, fmt.Errorf("多个 JPG 共享相邻 NEF: %s", actual)
			}
		}
	}
	if state.JPGSHA256 != "" && state.NEFSHA256 != file.SHA256 {
		return archivedFile{}, fmt.Errorf("相邻 NEF 与入库配对不一致: %s", actual)
	}
	return file, nil
}

func moveVerifiedArchiveFile(from, to, want string) error {
	fromHash, _, fromErr := digestFile(from)
	toHash, _, toErr := digestFile(to)
	if fromErr != nil && !os.IsNotExist(fromErr) {
		return fromErr
	}
	if toErr != nil && !os.IsNotExist(toErr) {
		return toErr
	}
	if fromErr == nil && fromHash != want || toErr == nil && toHash != want {
		return fmt.Errorf("文件摘要不符: %s 或 %s", from, to)
	}
	if os.IsNotExist(fromErr) {
		if toErr == nil {
			return nil
		}
		return fmt.Errorf("原位置与目标位置均缺少文件: %s", from)
	}
	if toErr == nil {
		srcInfo, srcErr := os.Stat(from)
		dstInfo, dstErr := os.Stat(to)
		if srcErr != nil || dstErr != nil {
			return errors.Join(srcErr, dstErr)
		}
		if !os.SameFile(srcInfo, dstInfo) {
			return fmt.Errorf("移动目标已存在: %s", to)
		}
	}
	if os.IsNotExist(toErr) {
		err := os.MkdirAll(filepath.Dir(to), 0700)
		if err != nil {
			return err
		}
		err = os.Link(from, to)
		if err != nil {
			return fmt.Errorf("无法在同一文件系统安全移动 %s: %w", from, err)
		}
	}
	return os.Remove(from)
}

func startPhotoRecycle(ctx *papp.AppCtx, id, kind string, selected *archivedFile) error {
	_, syncErr := syncActivityDirectoriesLocked(ctx)
	if syncErr != nil {
		return syncErr
	}
	item, err := data.PhotoDAO.FindPhotoRecycle(ctx, id, kind)
	if err != nil {
		return err
	}
	if item != nil {
		switch item.State {
		case "moving":
			return continuePhotoRecycle(ctx, item)
		case "deleted", "purged":
			return nil
		default:
			return fmt.Errorf("照片正在恢复")
		}
	}
	if kind == "photo" {
		nef, err := data.PhotoDAO.FindPhotoRecycle(ctx, id, "nef")
		if err != nil {
			return err
		}
		if nef != nil && nef.State == "moving" {
			err = continuePhotoRecycle(ctx, nef)
			if err != nil {
				return err
			}
		}
		if nef != nil && nef.State == "restoring" {
			err = continuePhotoRestore(ctx, nef)
			if err != nil {
				return err
			}
		}
	}
	row, err := data.PhotoDAO.GetByID(ctx, id)
	if err != nil {
		return err
	}
	var files []archivedFile
	if selected != nil {
		files = append(files, *selected)
	} else {
		jpg, err := fileForRecycle(conf.C.Storage.PhotoSrc, row.FilePath, false)
		if err != nil {
			return err
		}
		files = append(files, jpg)
		if row.FileType != "nef" {
			nef, err := photoPairNEF(ctx, row)
			if err != nil {
				return err
			}
			if nef.Original != "" {
				files = append(files, nef)
			}
			preview, err := fileForRecycle(conf.C.Storage.PhotoPath, row.FilePath, true)
			if err != nil && !os.IsNotExist(err) {
				return err
			}
			if err == nil && filepath.Clean(conf.C.Storage.PhotoPath) != filepath.Clean(conf.C.Storage.PhotoSrc) {
				files = append(files, preview)
			}
		}
	}
	photoJSON, err := json.Marshal(row)
	if err != nil {
		return err
	}
	filesJSON, err := json.Marshal(files)
	if err != nil {
		return err
	}
	item = &data.PhotoRecycleDO{ID: putil.UUID(), PhotoID: id, Kind: kind,
		State: "moving", PhotoJSON: photoJSON, FilesJSON: filesJSON}
	err = data.PhotoDAO.SaveRecycle(ctx, item)
	if err != nil {
		return err
	}
	return continuePhotoRecycle(ctx, item)
}

func recycleFailure(ctx *papp.AppCtx, item *data.PhotoRecycleDO, err error) error {
	item.LastError = err.Error()
	return errors.Join(err, data.PhotoDAO.SaveRecycle(ctx, item))
}

func continuePhotoRecycle(ctx *papp.AppCtx, item *data.PhotoRecycleDO) error {
	_, files, err := recycleData(item)
	if err != nil {
		return err
	}
	for _, file := range files {
		from := archivedSource(file, file.Original)
		to := recycleFilePath(item.ID, file)
		err = moveVerifiedArchiveFile(from, to, file.SHA256)
		if err != nil {
			return recycleFailure(ctx, item, err)
		}
	}
	item.State, item.LastError = "deleted", ""
	item.DeletedAt = time.Now().UTC()
	return data.PhotoDAO.FinishRecycle(ctx, item)
}

func pickPhotoRestorePaths(
	ctx *papp.AppCtx, row *data.PhotoDO, files []archivedFile,
) ([]archivedFile, error) {
	base := strings.TrimSuffix(row.FilePath, filepath.Ext(row.FilePath))
	for n := 0; n < 100; n++ {
		candidate := base
		if n > 0 {
			candidate = fmt.Sprintf("%s-restored-%d", base, n)
		}
		conflict := false
		for i := range files {
			file := &files[i]
			path := candidate + filepath.Ext(file.Original)
			root := conf.C.Storage.PhotoSrc
			if file.Preview {
				root = conf.C.Storage.PhotoPath
			}
			existing, err := archiveFileAt(root, path)
			if err != nil {
				return nil, err
			}
			if existing != "" {
				conflict = true
				break
			}
			if !file.Preview && !strings.EqualFold(filepath.Ext(path), ".nef") {
				record, err := data.PhotoDAO.FindByArchivePath(ctx, path)
				if err != nil {
					return nil, err
				}
				if record != nil {
					conflict = true
					break
				}
			}
			file.Restore = path
		}
		if !conflict {
			nefPath, err := archiveFileAt(conf.C.Storage.PhotoSrc, candidate+".nef")
			if err != nil {
				return nil, err
			}
			if nefPath == "" {
				return files, nil
			}
		}
	}
	return nil, fmt.Errorf("恢复路径冲突: %s", row.FilePath)
}

func restorePhotoRecycle(ctx *papp.AppCtx, id string, now time.Time) error {
	item, err := data.PhotoDAO.FindRecycle(ctx, id)
	if err != nil {
		return err
	}
	if item == nil || item.State != "deleted" && item.State != "restoring" {
		return fmt.Errorf("回收记录不可恢复")
	}
	if item.State != "restoring" && !now.Before(item.DeletedAt.Add(photoRecycleRetention)) {
		return fmt.Errorf("已超过 30 天恢复期限")
	}
	return continuePhotoRestore(ctx, item)
}

func continuePhotoRestore(ctx *papp.AppCtx, item *data.PhotoRecycleDO) error {
	_, syncErr := syncActivityDirectoriesLocked(ctx)
	if syncErr != nil {
		return syncErr
	}
	current, lookupErr := data.PhotoDAO.FindRecycle(ctx, item.ID)
	if lookupErr != nil {
		return lookupErr
	}
	if current != nil {
		item = current
	}
	row, files, err := recycleData(item)
	if err != nil {
		return err
	}
	if item.State != "restoring" {
		if item.Kind == "nef" {
			row, err = data.PhotoDAO.GetByID(ctx, item.PhotoID)
			if err != nil {
				return recycleFailure(ctx, item, fmt.Errorf("请先恢复关联的 JPG"))
			}
			state, stateErr := data.PhotoDAO.GetArchiveState(ctx, row.ID)
			if stateErr != nil {
				return recycleFailure(ctx, item, stateErr)
			}
			if state.JPGSHA256 != "" {
				jpg, _, digestErr := digestFile(filepath.Join(conf.C.Storage.PhotoSrc, row.FilePath))
				if digestErr != nil || jpg != state.JPGSHA256 {
					return recycleFailure(ctx, item, fmt.Errorf("关联 JPG 的原片摘要已变"))
				}
			}
			target := strings.TrimSuffix(row.FilePath, filepath.Ext(row.FilePath)) + ".nef"
			actual, err := archiveFileAt(conf.C.Storage.PhotoSrc, target)
			if err != nil {
				return recycleFailure(ctx, item, err)
			}
			if actual != "" {
				return recycleFailure(ctx, item, fmt.Errorf("配对 NEF 的目标已占用: %s", actual))
			}
			files[0].Restore = target
		} else {
			files, err = pickPhotoRestorePaths(ctx, row, files)
			if err != nil {
				return recycleFailure(ctx, item, err)
			}
		}
		for _, file := range files {
			digest, _, err := digestFile(recycleFilePath(item.ID, file))
			if err != nil || digest != file.SHA256 {
				return recycleFailure(ctx, item, fmt.Errorf("回收文件缺失或摘要不符: %s", file.Original))
			}
		}
		item.State = "restoring"
		item.FilesJSON, err = json.Marshal(files)
		if err != nil {
			return err
		}
		err = data.PhotoDAO.SaveRecycle(ctx, item)
		if err != nil {
			return err
		}
	}
	for _, file := range files {
		root := conf.C.Storage.PhotoSrc
		if file.Preview {
			root = conf.C.Storage.PhotoPath
		}
		current, err := archiveFileAt(root, file.Restore)
		if err != nil {
			return recycleFailure(ctx, item, err)
		}
		if current != "" && current != file.Restore {
			return recycleFailure(ctx, item, fmt.Errorf("恢复目标与现有文件重名: %s", current))
		}
		dest := archivedSource(file, file.Restore)
		err = moveVerifiedArchiveFile(recycleFilePath(item.ID, file), dest, file.SHA256)
		if err != nil {
			return recycleFailure(ctx, item, err)
		}
		if file.Original == row.FilePath && !file.Preview {
			row.FilePath, row.Filename = file.Restore, filepath.Base(file.Restore)
		}
	}
	err = data.PhotoDAO.FinishRecycleRestore(ctx, item, row)
	if err != nil {
		return recycleFailure(ctx, item, err)
	}
	cleanRecycleDirectories(item.ID, files)
	return nil
}

func cleanRecycleDirectories(id string, files []archivedFile) {
	for _, file := range files {
		dir := filepath.Dir(recycleFilePath(id, file))
		_ = os.Remove(dir)
		_ = os.Remove(filepath.Dir(dir))
	}
}

func sweepPhotoRecycle(ctx *papp.AppCtx, now time.Time) error {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	items, err := data.PhotoDAO.ListRecycleWork(ctx, now.Add(-photoRecycleRetention))
	if err != nil {
		return err
	}
	var failures []error
	for i := range items {
		item := &items[i]
		switch item.State {
		case "moving":
			err = continuePhotoRecycle(ctx, item)
		case "restoring":
			err = continuePhotoRestore(ctx, item)
		case "deleted":
			err = purgePhotoRecycle(ctx, item)
		}
		if err != nil {
			failures = append(failures, fmt.Errorf("%s: %w", item.ID, err))
		}
	}
	return errors.Join(failures...)
}

func purgePhotoRecycle(ctx *papp.AppCtx, item *data.PhotoRecycleDO) error {
	_, files, err := recycleData(item)
	if err != nil {
		return err
	}
	for _, file := range files {
		path := recycleFilePath(item.ID, file)
		digest, _, err := digestFile(path)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil || digest != file.SHA256 {
			return recycleFailure(ctx, item, fmt.Errorf("回收文件核验失败: %s", path))
		}
		err = os.Remove(path)
		if err != nil && !os.IsNotExist(err) {
			return recycleFailure(ctx, item, err)
		}
	}
	cleanRecycleDirectories(item.ID, files)
	return data.PhotoDAO.PurgeRecycle(ctx, item)
}

// RunPhotoRecycleMaintenance reconciles interrupted operations and retention.
func RunPhotoRecycleMaintenance(ctx context.Context) {
	ticker := time.NewTicker(time.Hour)
	defer ticker.Stop()
	for {
		err := sweepPhotoRecycle(papp.NewAppCtx(ctx), time.Now())
		if err != nil {
			plogger.Warnf("photo recycle maintenance: %v", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func apiPhotoArchiveError(ctx khttp.Context, err error) error {
	return ctx.Result(http.StatusConflict, map[string]string{"error": err.Error()})
}

func (s *PhotoServer) photoFavorite(ctx khttp.Context) error {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	app := papp.NewAppCtx(ctx.Request().Context())
	id := ctx.Vars().Get("id")
	_, err := data.PhotoDAO.GetByID(app, id)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	if ctx.Request().Method == http.MethodPost {
		var req struct {
			Favorite *bool `json:"favorite"`
		}
		err = ctx.Bind(&req)
		if err != nil || req.Favorite == nil {
			return ctx.Result(http.StatusBadRequest, map[string]string{"error": "需要收藏状态"})
		}
		err = data.PhotoDAO.SetArchiveFavorite(app, id, *req.Favorite)
		if err != nil {
			return apiPhotoArchiveError(ctx, err)
		}
	}
	state, err := data.PhotoDAO.GetArchiveState(app, id)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	return ctx.Result(http.StatusOK, map[string]bool{"favorite": state.Favorite})
}

func (s *PhotoServer) photoNEFCleanup(ctx khttp.Context) error {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	app, cancel := archiveOperationContext(ctx.Request().Context())
	defer cancel()
	activity := ctx.Request().URL.Query().Get("activity")
	if activity == "" {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": "请选择活动"})
	}
	rows, err := data.PhotoDAO.ListArchiveActivity(app, activity)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	candidates := make([]nefCleanupCandidate, 0)
	var issues []string
	for i := range rows {
		row := &rows[i]
		state, err := data.PhotoDAO.GetArchiveState(app, row.ID)
		if err != nil {
			return apiPhotoArchiveError(ctx, err)
		}
		if state.Favorite {
			continue
		}
		pending, err := data.PhotoDAO.FindPhotoRecycle(app, row.ID, "photo")
		if err != nil {
			return apiPhotoArchiveError(ctx, err)
		}
		if pending != nil {
			continue
		}
		file, err := photoPairNEF(app, row)
		if err != nil {
			issues = append(issues, err.Error())
		} else if file.Original != "" {
			candidates = append(candidates, nefCleanupCandidate{row.ID, file.Original, file.SHA256, file.Bytes})
		}
	}
	if ctx.Request().Method == http.MethodGet {
		return ctx.Result(http.StatusOK, map[string]any{"files": candidates, "issues": issues})
	}
	var confirmed []nefCleanupCandidate
	err = ctx.Bind(&confirmed)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
	current := make(map[string]nefCleanupCandidate)
	for _, file := range candidates {
		current[file.ID] = file
	}
	results := make([]map[string]string, 0, len(confirmed))
	for _, file := range confirmed {
		result := map[string]string{"id": file.ID, "path": file.Path, "status": "skipped"}
		if candidate := current[file.ID]; candidate == file {
			archived := &archivedFile{Original: file.Path, SHA256: file.SHA256, Bytes: file.Bytes}
			err := startPhotoRecycle(app, file.ID, "nef", archived)
			if err != nil {
				result["status"], result["error"] = "failed", err.Error()
			} else {
				result["status"] = "deleted"
			}
		}
		results = append(results, result)
	}
	return ctx.Result(http.StatusOK, results)
}

func (s *PhotoServer) listPhotoRecycle(ctx khttp.Context) error {
	app := papp.NewAppCtx(ctx.Request().Context())
	items, err := data.PhotoDAO.ListRecycle(app)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	result := make([]recyclePhotoView, 0, len(items))
	for i := range items {
		item := &items[i]
		if item.State == "purged" {
			continue
		}
		row, _, err := recycleData(item)
		if err != nil {
			return apiPhotoArchiveError(ctx, err)
		}
		view := recyclePhotoView{ID: item.ID, PhotoID: item.PhotoID, Kind: item.Kind,
			State: item.State, Activity: row.Timeline, Name: row.Filename, Error: item.LastError}
		if !item.DeletedAt.IsZero() {
			expires := item.DeletedAt.Add(photoRecycleRetention)
			view.DeletedAt, view.ExpiresAt = &item.DeletedAt, &expires
		}
		result = append(result, view)
	}
	return ctx.Result(http.StatusOK, result)
}

func (s *PhotoServer) recoverPhotoRecycle(ctx khttp.Context) error {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	var ids []string
	err := ctx.Bind(&ids)
	if err != nil || len(ids) == 0 || len(ids) > 500 {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": "请选择 1 至 500 条记录"})
	}
	app, cancel := archiveOperationContext(ctx.Request().Context())
	defer cancel()
	// A batch may include the JPG and a separately recycled NEF. Restore live
	// photo identities before attempting to attach any NEF.
	photoIDs, nefIDs := make([]string, 0, len(ids)), make([]string, 0, len(ids))
	seen := make(map[string]bool)
	for _, id := range ids {
		if seen[id] {
			continue
		}
		seen[id] = true
		item, err := data.PhotoDAO.FindRecycle(app, id)
		if err != nil {
			return apiPhotoArchiveError(ctx, err)
		}
		if item != nil && item.Kind == "nef" {
			nefIDs = append(nefIDs, id)
		} else {
			photoIDs = append(photoIDs, id)
		}
	}
	ids = append(photoIDs, nefIDs...)
	result := make([]map[string]string, 0, len(ids))
	for _, id := range ids {
		status := map[string]string{"id": id, "status": "restored"}
		err := restorePhotoRecycle(app, id, time.Now())
		if err != nil {
			status["status"], status["error"] = "failed", err.Error()
		}
		result = append(result, status)
	}
	return ctx.Result(http.StatusOK, result)
}

func (s *PhotoServer) previewPhotoRecycle(ctx khttp.Context) error {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	ctx.Response().Header().Set("Cache-Control", "no-store")
	app := papp.NewAppCtx(ctx.Request().Context())
	item, err := data.PhotoDAO.FindRecycle(app, ctx.Vars().Get("id"))
	if err != nil || item == nil || item.State == "purged" {
		return ctx.Result(http.StatusNotFound, map[string]string{"error": "回收记录不存在"})
	}
	if item.Kind == "nef" {
		req := ctx.Request()
		photo, err := data.PhotoDAO.GetByID(app, item.PhotoID)
		if err == nil {
			http.ServeFile(ctx.Response(), req, filepath.Join(conf.C.Storage.PhotoPath, photo.FilePath))
			return nil
		}
		return ctx.Result(http.StatusNotFound, map[string]string{"error": "关联照片已删除"})
	}
	_, files, err := recycleData(item)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	for _, file := range files {
		if file.Preview {
			http.ServeFile(ctx.Response(), ctx.Request(), recycleFilePath(item.ID, file))
			return nil
		}
	}
	for _, file := range files {
		name := strings.ToLower(file.Original)
		if strings.HasSuffix(name, ".jpg") || strings.HasSuffix(name, ".jpeg") {
			http.ServeFile(ctx.Response(), ctx.Request(), recycleFilePath(item.ID, file))
			return nil
		}
	}
	return ctx.Result(http.StatusNotFound, map[string]string{"error": "无回收缩略图"})
}

func (s *PhotoServer) photoDeletedIDs(ctx khttp.Context) error {
	app := papp.NewAppCtx(ctx.Request().Context())
	ids, err := data.PhotoDAO.ListDeletedPhotoIDs(app, ctx.Request().URL.Query().Get("purged") == "1")
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	return ctx.Result(http.StatusOK, ids)
}

func (s *PhotoServer) listImportedActivities(ctx khttp.Context) error {
	server := TimelineServer{}
	result, err := server.ListTimelines(ctx.Request().Context(), &api.Empty{})
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	return ctx.Result(http.StatusOK, result.Timelines)
}

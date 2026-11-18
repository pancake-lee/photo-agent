package service

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"
)

const activityMoveJournalName = ".photo-agent-move.json"

type movePhotosRequest struct {
	PhotoIDs     []string `json:"photo_ids"`
	ActivityID   string   `json:"activity_id"`
	NewActivity  string   `json:"new_activity"`
	ConfirmedIDs []string `json:"confirmed_photo_ids"`
	BurstProfile string   `json:"burst_profile"`
	Preview      bool     `json:"preview"`
}

type activityMoveFile struct {
	From    string `json:"from"`
	To      string `json:"to"`
	Preview bool   `json:"preview,omitempty"`
}

type activityMoveJournal struct {
	Version int                      `json:"version"`
	Moves   []data.PhotoActivityMove `json:"moves"`
	Files   []activityMoveFile       `json:"files"`
}

type photoMovePreviewItem struct {
	PhotoID      string `json:"photo_id"`
	Filename     string `json:"filename"`
	FromActivity string `json:"from_activity"`
	ToFilename   string `json:"to_filename"`
}

type photoMoveResult struct {
	Activity  string                 `json:"activity"`
	Total     int                    `json:"total"`
	Moving    int                    `json:"moving"`
	Unchanged int                    `json:"unchanged"`
	Renamed   int                    `json:"renamed"`
	Items     []photoMovePreviewItem `json:"items"`
	PhotoIDs  []string               `json:"photo_ids"`
	Warning   string                 `json:"warning,omitempty"`
}

func (s *PhotoServer) MovePhotosActivityHandler(kctx khttp.Context) error {
	var req movePhotosRequest
	decoder := json.NewDecoder(io.LimitReader(kctx.Request().Body, 1024*1024))
	if err := decoder.Decode(&req); err != nil {
		return kctx.Result(http.StatusBadRequest, map[string]string{"error": "移动请求无效"})
	}
	validTarget := validActivityID(req.ActivityID) && req.NewActivity == "" ||
		req.Preview && req.ActivityID == "" && archiveComponent(req.NewActivity)
	if len(req.PhotoIDs) == 0 || len(req.PhotoIDs) > 2000 || !validTarget ||
		req.BurstProfile != "all" && req.BurstProfile != "fine" && req.BurstProfile != "coarse" {
		return kctx.Result(http.StatusBadRequest, map[string]string{"error": "请选择 1 至 2000 张照片和有效的目标活动"})
	}
	seen := map[string]bool{}
	for _, id := range req.PhotoIDs {
		if id == "" || seen[id] {
			return kctx.Result(http.StatusBadRequest, map[string]string{"error": "照片 ID 不能为空或重复"})
		}
		seen[id] = true
	}
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	if burstGroups.isRunning() {
		return kctx.Result(http.StatusConflict, map[string]string{"error": "请等待连拍分组完成后再移动照片"})
	}
	ctx := papp.NewAppCtx(kctx.Request().Context())
	list, err := syncActivityDirectoriesLocked(ctx)
	if err != nil {
		return kctx.Result(http.StatusConflict, map[string]string{"error": err.Error()})
	}
	var target *activityDirectory
	if req.NewActivity != "" {
		actual, lookupErr := caseInsensitiveFileName(conf.C.Storage.PhotoSrc, req.NewActivity)
		if lookupErr != nil {
			return kctx.Result(http.StatusConflict, map[string]string{"error": lookupErr.Error()})
		}
		if actual != "" {
			return kctx.Result(http.StatusConflict, map[string]string{"error": "同名活动已存在，请选择已有活动"})
		}
		target = &activityDirectory{Name: req.NewActivity,
			Metadata: activityMetadata{Version: 1, ID: putil.UUID()}}
	}
	for i := range list {
		if list[i].Metadata.ID == req.ActivityID {
			target = &list[i]
			break
		}
	}
	if target == nil {
		return kctx.Result(http.StatusConflict, map[string]string{"error": "目标活动已删除或不可用，请重新选择"})
	}
	plan, result, err := planPhotosActivityMove(ctx, req, *target)
	if err == nil && !req.Preview && len(plan.Moves) > 0 {
		err = applyPhotosActivityMove(ctx, plan)
		if _, statErr := os.Lstat(filepath.Join(conf.C.Storage.PhotoSrc, activityMoveJournalName)); err == nil && statErr == nil {
			result.Warning = "照片已移动，原位置的清理将在下次同步时继续"
		}
	}
	if err != nil {
		return kctx.Result(http.StatusConflict, map[string]string{"error": err.Error()})
	}
	return kctx.Result(http.StatusOK, result)
}

func planPhotosActivityMove(ctx *papp.AppCtx, req movePhotosRequest,
	target activityDirectory,
) (activityMoveJournal, photoMoveResult, error) {
	plan := activityMoveJournal{Version: 1}
	result := photoMoveResult{Activity: target.Name, Items: []photoMovePreviewItem{}}
	photos, err := data.ListPhotosForActivityMove(ctx, req.PhotoIDs, req.BurstProfile)
	if err != nil {
		return plan, result, err
	}
	sort.Slice(photos, func(i, j int) bool { return photos[i].ID < photos[j].ID })
	if len(photos) > 10000 {
		return plan, result, fmt.Errorf("展开连拍后超过 10000 张，请分批移动")
	}
	for _, photo := range photos {
		result.PhotoIDs = append(result.PhotoIDs, photo.ID)
	}
	if !req.Preview {
		confirmed := append([]string(nil), req.ConfirmedIDs...)
		sort.Strings(confirmed)
		if len(confirmed) != len(result.PhotoIDs) {
			return plan, result, fmt.Errorf("选中照片或连拍组已变化，请重新预览")
		}
		for i, id := range confirmed {
			if id != result.PhotoIDs[i] {
				return plan, result, fmt.Errorf("选中照片或连拍组已变化，请重新预览")
			}
		}
	}
	result.Total = len(photos)
	used := map[string]bool{}
	for _, root := range []string{conf.C.Storage.PhotoSrc, conf.C.Storage.PhotoPath} {
		err = archiveSafeDir(root, target.Name)
		if err != nil {
			return plan, result, err
		}
		entries, readErr := os.ReadDir(filepath.Join(root, target.Name))
		if readErr != nil && !os.IsNotExist(readErr) {
			return plan, result, readErr
		}
		for _, entry := range entries {
			used[strings.ToLower(entry.Name())] = true
		}
	}
	existing, err := data.PhotoDAO.ListArchiveActivity(ctx, target.Name)
	if err != nil {
		return plan, result, err
	}
	for _, photo := range existing {
		used[strings.ToLower(photo.Filename)] = true
	}
	checked := map[string]bool{}
	for _, photo := range photos {
		if photo.ActivityID == target.Metadata.ID {
			result.Unchanged++
			continue
		}
		for _, kind := range []string{"photo", "nef"} {
			recycled, recycleErr := data.PhotoDAO.FindPhotoRecycle(ctx, photo.ID, kind)
			if recycleErr != nil {
				return plan, result, recycleErr
			}
			if recycled != nil && (recycled.State == "moving" || recycled.State == "restoring") {
				return plan, result, fmt.Errorf("照片仍有待完成的回收或恢复，请稍后重试: %s", photo.Filename)
			}
		}
		if !archiveComponent(photo.Filename) || photo.Timeline != "" && !archiveComponent(photo.Timeline) {
			return plan, result, fmt.Errorf("照片位置无效: %s", photo.Filename)
		}
		for _, name := range []string{photo.Timeline, target.Name} {
			if checked[name] {
				continue
			}
			busy, busyErr := data.HasActivityReservations(ctx, name)
			if busyErr != nil {
				return plan, result, busyErr
			}
			if busy {
				return plan, result, fmt.Errorf("请先完成活动“%s”中的导入再移动照片", name)
			}
			checked[name] = true
		}
		nef, pairErr := photoPairNEF(ctx, &photo)
		if pairErr != nil {
			return plan, result, pairErr
		}
		name, nameErr := availableMoveFilename(photo.Filename, used)
		if nameErr != nil {
			return plan, result, nameErr
		}
		newPath := filepath.Join(target.Name, name)
		file, fileErr := planActivityMoveFile(photo.FilePath, newPath, false)
		if fileErr != nil {
			return plan, result, fileErr
		}
		plan.Files = append(plan.Files, file)
		if nef.Original != "" {
			newNEF := strings.TrimSuffix(newPath, filepath.Ext(newPath)) + filepath.Ext(nef.Original)
			file, fileErr = planActivityMoveFile(nef.Original, newNEF, false)
			if fileErr != nil {
				return plan, result, fileErr
			}
			plan.Files = append(plan.Files, file)
		}
		if filepath.Clean(conf.C.Storage.PhotoPath) != filepath.Clean(conf.C.Storage.PhotoSrc) {
			preview, lookupErr := archiveFileAt(conf.C.Storage.PhotoPath, photo.FilePath)
			if lookupErr != nil {
				return plan, result, lookupErr
			}
			if preview != "" {
				file, fileErr = planActivityMoveFile(preview, newPath, true)
				if fileErr != nil {
					return plan, result, fileErr
				}
				plan.Files = append(plan.Files, file)
			}
		}
		plan.Moves = append(plan.Moves, data.PhotoActivityMove{
			PhotoID: photo.ID, FromActivityID: photo.ActivityID,
			FromTimeline: photo.Timeline, FromFilename: photo.Filename,
			ActivityID: target.Metadata.ID, Timeline: target.Name, Filename: name,
		})
		result.Items = append(result.Items, photoMovePreviewItem{
			PhotoID: photo.ID, Filename: photo.Filename,
			FromActivity: photo.Timeline, ToFilename: name,
		})
		if name != photo.Filename {
			result.Renamed++
		}
	}
	result.Moving = len(plan.Moves)
	return plan, result, nil
}

func availableMoveFilename(original string, used map[string]bool) (string, error) {
	ext := filepath.Ext(original)
	stem := strings.TrimSuffix(original, ext)
	for number := 1; ; number++ {
		name := original
		if number > 1 {
			suffix := fmt.Sprintf(" (%d)", number)
			if len(suffix+ext) >= 180 {
				return "", fmt.Errorf("文件扩展名过长，无法添加序号: %s", original)
			}
			short := []rune(stem)
			for len(string(short)+suffix+ext) > 180 {
				short = short[:len(short)-1]
			}
			name = string(short) + suffix + ext
		}
		nefName := strings.TrimSuffix(name, ext) + ".nef"
		if !used[strings.ToLower(name)] && !used[strings.ToLower(nefName)] {
			used[strings.ToLower(name)], used[strings.ToLower(nefName)] = true, true
			return name, nil
		}
	}
}

func moveFileRoot(preview bool) string {
	if preview {
		return conf.C.Storage.PhotoPath
	}
	return conf.C.Storage.PhotoSrc
}

func planActivityMoveFile(from, to string, preview bool) (activityMoveFile, error) {
	root := moveFileRoot(preview)
	actual, err := archiveFileAt(root, from)
	if err != nil {
		return activityMoveFile{}, err
	}
	info, err := os.Lstat(filepath.Join(root, actual))
	if err != nil || actual == "" || !info.Mode().IsRegular() {
		return activityMoveFile{}, fmt.Errorf("原文件不可用: %s", from)
	}
	return activityMoveFile{From: actual, To: to, Preview: preview}, nil
}

func applyPhotosActivityMove(ctx *papp.AppCtx, plan activityMoveJournal) error {
	for _, move := range plan.Moves {
		if filepath.Clean(conf.C.Storage.PhotoPath) == filepath.Clean(conf.C.Storage.PhotoSrc) {
			continue
		}
		err := archiveSafeDir(conf.C.Storage.PhotoPath, move.Timeline)
		if err != nil {
			return err
		}
		dir := filepath.Join(conf.C.Storage.PhotoPath, move.Timeline)
		err = os.MkdirAll(dir, 0755)
		if err != nil {
			return err
		}
		err = ensureActivityPreviewID(dir, move.ActivityID)
		if err != nil {
			return err
		}
	}
	path := filepath.Join(conf.C.Storage.PhotoSrc, activityMoveJournalName)
	journal, err := os.CreateTemp(conf.C.Storage.PhotoSrc, ".photo-agent-move-*")
	if err != nil {
		return err
	}
	defer os.Remove(journal.Name())
	err = json.NewEncoder(journal).Encode(plan)
	if err == nil {
		err = journal.Sync()
	}
	err = errors.Join(err, journal.Close())
	if err != nil {
		return err
	}
	// Publish the complete journal atomically without replacing a pending one.
	err = os.Link(journal.Name(), path)
	if err != nil {
		return err
	}
	for _, file := range plan.Files {
		root := moveFileRoot(file.Preview)
		err = archiveSafeDir(root, filepath.Dir(file.To))
		if err == nil {
			err = os.Link(filepath.Join(root, file.From), filepath.Join(root, file.To))
		}
		if err != nil {
			return errors.Join(err, recoverPendingActivityMove(ctx))
		}
	}
	err = data.MovePhotosActivity(ctx, plan.Moves)
	if err != nil {
		return errors.Join(err, recoverPendingActivityMove(ctx))
	}
	// The journal survives a failed cleanup; the next sync finishes it safely.
	err = recoverPendingActivityMove(ctx)
	if err != nil {
		plogger.Warnf("照片活动已更新，移动日志保留等待收尾: %v", err)
	}
	return nil
}

// A durable link plan makes crashes before/after the DB commit distinguishable.
// Only links to the same inode are removed; unrelated user files are preserved.
func recoverPendingActivityMove(ctx *papp.AppCtx) error {
	path := filepath.Join(conf.C.Storage.PhotoSrc, activityMoveJournalName)
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() > 16*1024*1024 {
		return fmt.Errorf("活动移动记录无效")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var plan activityMoveJournal
	err = json.Unmarshal(raw, &plan)
	if err != nil || plan.Version != 1 || len(plan.Moves) == 0 || len(plan.Files) == 0 {
		return fmt.Errorf("活动移动记录损坏: %v", err)
	}
	ids := make([]string, 0, len(plan.Moves))
	for _, move := range plan.Moves {
		ids = append(ids, move.PhotoID)
	}
	photos, err := data.PhotoDAO.GetByIDList(ctx, ids)
	if err != nil {
		return err
	}
	old, updated := true, true
	for _, move := range plan.Moves {
		photo := photos[move.PhotoID]
		if photo == nil {
			return fmt.Errorf("移动中的照片不存在: %s", move.PhotoID)
		}
		old = old && photo.ActivityID == move.FromActivityID &&
			photo.Timeline == move.FromTimeline && photo.Filename == move.FromFilename
		updated = updated && photo.ActivityID == move.ActivityID &&
			photo.Timeline == move.Timeline && photo.Filename == move.Filename
	}
	if !old && !updated {
		return fmt.Errorf("移动中的照片位置已被更改，请核对移动记录")
	}
	for _, file := range plan.Files {
		root := moveFileRoot(file.Preview)
		for _, rel := range []string{file.From, file.To} {
			if !filepath.IsLocal(rel) || !archiveComponent(filepath.Base(rel)) ||
				filepath.Dir(rel) != "." && !archiveComponent(filepath.Dir(rel)) {
				return fmt.Errorf("移动记录包含无效路径")
			}
			if filepath.Dir(rel) != "." {
				err = archiveSafeDir(root, filepath.Dir(rel))
				if err != nil {
					return err
				}
			}
		}
		keep, remove := file.From, file.To
		if updated {
			keep, remove = file.To, file.From
		}
		keepInfo, keepErr := os.Lstat(filepath.Join(root, keep))
		if keepErr != nil || !keepInfo.Mode().IsRegular() {
			return fmt.Errorf("移动中的文件不可用: %s", keep)
		}
		removeInfo, removeErr := os.Lstat(filepath.Join(root, remove))
		if os.IsNotExist(removeErr) {
			continue
		}
		if removeErr != nil {
			return removeErr
		}
		if os.SameFile(keepInfo, removeInfo) {
			err = os.Remove(filepath.Join(root, remove))
			if err != nil {
				return err
			}
		}
	}
	return os.Remove(path)
}

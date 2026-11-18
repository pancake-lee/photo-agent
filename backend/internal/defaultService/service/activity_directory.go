package service

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/go-kratos/kratos/v2/middleware"
	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/putil"
)

const activityMetadataFile = ".photo-agent.json"
const activityPreviewIDFile = ".photo-agent-activity"

type activityMetadata struct {
	Version int    `json:"version"`
	ID      string `json:"id"`
	Date    string `json:"date,omitempty"`
	Note    string `json:"note,omitempty"`
}

type activityDirectory struct {
	Name     string
	Metadata activityMetadata
}

func validActivityID(id string) bool {
	raw, err := hex.DecodeString(strings.ReplaceAll(id, "-", ""))
	return err == nil && len(raw) == 16
}

func validActivityDate(date string) bool {
	if date == "" {
		return true
	}
	for _, layout := range []string{"2006-01-02", time.RFC3339} {
		_, err := time.Parse(layout, date)
		if err == nil {
			return true
		}
	}
	return false
}

func activityDateTime(date string) time.Time {
	value, err := time.Parse(time.RFC3339, date)
	if err == nil {
		return value
	}
	value, _ = time.ParseInLocation("2006-01-02", date, time.Local)
	return value
}

func readActivityMetadata(name string) (activityMetadata, error) {
	var meta activityMetadata
	path := filepath.Join(conf.C.Storage.PhotoSrc, name, activityMetadataFile)
	info, err := os.Lstat(path)
	if err != nil {
		return meta, err
	}
	if !info.Mode().IsRegular() || info.Size() > 1024*1024 {
		return meta, fmt.Errorf("活动元数据不是普通文件或超过 1MB: %s", path)
	}
	file, err := os.Open(path)
	if err != nil {
		return meta, err
	}
	defer file.Close()
	decoder := json.NewDecoder(io.LimitReader(file, 1024*1024+1))
	err = decoder.Decode(&meta)
	if err != nil {
		return meta, fmt.Errorf("活动元数据损坏 %s: %w", name, err)
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || meta.Version != 1 || !validActivityID(meta.ID) || !validActivityDate(meta.Date) {
		return meta, fmt.Errorf("活动元数据格式无效: %s", name)
	}
	return meta, nil
}

func writeActivityMetadata(name string, meta activityMetadata) error {
	raw, err := json.MarshalIndent(meta, "", "  ")
	if err != nil {
		return err
	}
	dir := filepath.Join(conf.C.Storage.PhotoSrc, name)
	err = archiveSafeDir(conf.C.Storage.PhotoSrc, name)
	if err != nil {
		return err
	}
	temp, err := os.CreateTemp(dir, ".photo-agent-*")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	_, err = temp.Write(append(raw, '\n'))
	if err == nil {
		err = temp.Sync()
	}
	err = errors.Join(err, temp.Close())
	if err != nil {
		return err
	}
	return os.Rename(temp.Name(), filepath.Join(dir, activityMetadataFile))
}

func ensureActivityMetadata(ctx *papp.AppCtx, name string) (activityMetadata, error) {
	var meta activityMetadata
	if !archiveComponent(name) {
		return meta, fmt.Errorf("无效活动目录名: %q", name)
	}
	err := archiveSafeDir(conf.C.Storage.PhotoSrc, name)
	if err != nil {
		return meta, err
	}
	meta, err = readActivityMetadata(name)
	if !os.IsNotExist(err) {
		return meta, err
	}
	date, note, err := data.ActivityMetadataSeed(ctx, name)
	if err != nil {
		return meta, err
	}
	if date == "" && len(name) >= 6 {
		month, parseErr := time.Parse("200601", name[:6])
		if parseErr == nil {
			date = month.Format("2006-01-02")
		}
	}
	meta = activityMetadata{Version: 1, ID: putil.UUID(), Date: date, Note: note}
	err = os.MkdirAll(filepath.Join(conf.C.Storage.PhotoSrc, name), 0755)
	if err != nil {
		return meta, err
	}
	return meta, writeActivityMetadata(name, meta)
}

func readActivityDirectories(ctx *papp.AppCtx) ([]activityDirectory, error) {
	entries, err := os.ReadDir(conf.C.Storage.PhotoSrc)
	if os.IsNotExist(err) {
		return []activityDirectory{}, nil
	}
	if err != nil {
		return nil, err
	}
	result := make([]activityDirectory, 0)
	seen := make(map[string]string)
	names := make(map[string]bool)
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".") || !entry.IsDir() {
			continue
		}
		name := entry.Name()
		if !archiveComponent(name) || names[strings.ToLower(name)] {
			return nil, fmt.Errorf("无效或大小写冲突的活动目录: %s", name)
		}
		names[strings.ToLower(name)] = true
		meta, err := ensureActivityMetadata(ctx, name)
		if err != nil {
			return nil, err
		}
		if prior := seen[meta.ID]; prior != "" {
			return nil, fmt.Errorf("活动标识重复: %s 与 %s，请核对复制的目录", prior, name)
		}
		seen[meta.ID] = name
		result = append(result, activityDirectory{Name: name, Metadata: meta})
	}
	sort.Slice(result, func(i, j int) bool {
		left, right := activityDateTime(result[i].Metadata.Date), activityDateTime(result[j].Metadata.Date)
		if !left.Equal(right) {
			return left.After(right)
		}
		return result[i].Name > result[j].Name
	})
	return result, nil
}

func ensureActivityPreviewID(dir, id string) error {
	path := filepath.Join(dir, activityPreviewIDFile)
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		file, createErr := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if createErr != nil {
			return createErr
		}
		_, writeErr := file.WriteString(id)
		return errors.Join(writeErr, file.Close())
	}
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() > 128 {
		return fmt.Errorf("无效活动预览标识: %s", path)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if string(raw) != id {
		return fmt.Errorf("活动预览标识冲突: %s", dir)
	}
	return nil
}

// syncActivityPreview is restartable after a crash between moving a preview
// directory and committing its new database name. The marker rejects collisions.
func syncActivityPreview(id, old, name string) (func() error, error) {
	noop := func() error { return nil }
	if filepath.Clean(conf.C.Storage.PhotoPath) == filepath.Clean(conf.C.Storage.PhotoSrc) {
		return noop, nil
	}
	oldPath := filepath.Join(conf.C.Storage.PhotoPath, old)
	newPath := filepath.Join(conf.C.Storage.PhotoPath, name)
	err := archiveSafeDir(conf.C.Storage.PhotoPath, name)
	if err != nil {
		return nil, err
	}
	if old != "" && old != name {
		err = archiveSafeDir(conf.C.Storage.PhotoPath, old)
		if err != nil {
			return nil, err
		}
		_, fromErr := os.Lstat(oldPath)
		_, toErr := os.Lstat(newPath)
		if fromErr != nil && !os.IsNotExist(fromErr) {
			return nil, fromErr
		}
		if toErr != nil && !os.IsNotExist(toErr) {
			return nil, toErr
		}
		if fromErr == nil {
			if toErr == nil {
				return nil, fmt.Errorf("活动预览目录已存在: %s", name)
			}
			err = ensureActivityPreviewID(oldPath, id)
			if err != nil {
				return nil, err
			}
			err = os.Rename(oldPath, newPath)
			if err != nil {
				return nil, err
			}
			return func() error { return os.Rename(newPath, oldPath) }, nil
		}
		if toErr == nil {
			marker, readErr := os.ReadFile(filepath.Join(newPath, activityPreviewIDFile))
			if readErr != nil || string(marker) != id {
				return nil, fmt.Errorf("活动预览目录身份不匹配: %s", name)
			}
		}
	}
	info, err := os.Lstat(newPath)
	if os.IsNotExist(err) {
		return noop, nil
	}
	if err != nil {
		return nil, err
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("无效预览目录: %s", name)
	}
	return noop, ensureActivityPreviewID(newPath, id)
}

// SyncActivityDirectories is called on startup and before location-sensitive
// operations. Hidden work directories never become activities.
func SyncActivityDirectories(ctx context.Context) error {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	_, err := syncActivityDirectoriesLocked(papp.NewAppCtx(ctx))
	return err
}

func activityPreviewNames() (map[string]string, error) {
	result := make(map[string]string)
	entries, err := os.ReadDir(conf.C.Storage.PhotoPath)
	if os.IsNotExist(err) {
		return result, nil
	}
	if err != nil {
		return nil, err
	}
	for _, entry := range entries {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".") {
			continue
		}
		marker := filepath.Join(conf.C.Storage.PhotoPath, entry.Name(), activityPreviewIDFile)
		info, statErr := os.Lstat(marker)
		if os.IsNotExist(statErr) {
			continue
		}
		if statErr != nil {
			return nil, statErr
		}
		if !info.Mode().IsRegular() || info.Size() > 128 {
			return nil, fmt.Errorf("无效活动预览标识: %s", entry.Name())
		}
		raw, readErr := os.ReadFile(marker)
		if readErr != nil {
			return nil, readErr
		}
		id := string(raw)
		if !validActivityID(id) {
			return nil, fmt.Errorf("无效活动预览标识: %s", entry.Name())
		}
		if prior := result[id]; prior != "" {
			return nil, fmt.Errorf("活动预览标识重复: %s 与 %s", prior, entry.Name())
		}
		result[id] = entry.Name()
	}
	return result, nil
}

func syncActivityDirectoriesLocked(ctx *papp.AppCtx) ([]activityDirectory, error) {
	list, err := readActivityDirectories(ctx)
	if err != nil {
		return nil, err
	}
	err = data.MigratePhotoLocations(ctx)
	if err != nil {
		return nil, err
	}
	locations, err := data.ListActivityLocations(ctx)
	if err != nil {
		return nil, err
	}
	oldNames := make(map[string]string)
	unbound := make(map[string]bool)
	for _, row := range locations {
		if row.ActivityID == "" {
			unbound[row.Timeline] = true
			continue
		}
		if old := oldNames[row.ActivityID]; old != "" && old != row.Timeline {
			return nil, fmt.Errorf("活动 %s 的照片目录记录不一致", row.ActivityID)
		}
		oldNames[row.ActivityID] = row.Timeline
	}
	previewNames, err := activityPreviewNames()
	if err != nil {
		return nil, err
	}
	for _, item := range list {
		id, name := item.Metadata.ID, item.Name
		old := oldNames[id]
		if old == "" {
			old = previewNames[id]
		}
		if old != "" && old != name {
			busy, err := data.HasActivityReservations(ctx, old)
			if err != nil {
				return nil, err
			}
			if busy {
				return nil, fmt.Errorf("活动 %s 有尚未完成的导入，请恢复原名并完成导入后再改名", old)
			}
		}
		undo, err := syncActivityPreview(id, old, name)
		if err != nil {
			return nil, err
		}
		if old != name || unbound[name] {
			err = data.BindActivityDirectory(ctx, id, name)
			if err != nil {
				return nil, errors.Join(err, undo())
			}
		}
		delete(oldNames, id)
	}
	for _, old := range oldNames {
		return nil, fmt.Errorf("活动目录缺失或稳定标识已被修改: %s", old)
	}
	err = data.RetireLegacyTimelineEvents(ctx)
	if err != nil {
		return nil, err
	}
	return list, nil
}

// RegisterActivitySynchronization makes renamed locations visible before RPC
// handlers read them. Raw photo HTTP routes use the equivalent filter below.
func RegisterActivitySynchronization(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	selectors := []string{"/api.PhotoService/*", "/api.defaultCURD/*", "/api.QueryService/*", "/api.DraftService/*", "/api.VlmService/*", "/api.EmbeddingService/*"}
	for _, selector := range selectors {
		if grpcSrv != nil {
			grpcSrv.Use(selector, activitySynchronizationMiddleware)
		}
		if httpSrv != nil {
			httpSrv.Use(selector, activitySynchronizationMiddleware)
		}
	}
}

func activitySynchronizationMiddleware(next middleware.Handler) middleware.Handler {
	return func(ctx context.Context, req any) (any, error) {
		err := SyncActivityDirectories(ctx)
		if err != nil {
			return nil, err
		}
		return next(ctx, req)
	}
}

func activityDirectoryFilter(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/v1/photo-import/") {
			next.ServeHTTP(w, r)
			return
		}
		err := SyncActivityDirectories(r.Context())
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusConflict)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
			return
		}
		next.ServeHTTP(w, r)
	})
}

// Receipts identify an activity independently of its visible name. PhotoID
// also upgrades receipts created before activity IDs were returned to clients.
func normalizeArchiveActivity(ctx *papp.AppCtx, req *archiveImportRequest) error {
	if req.activityNormalized {
		return nil
	}
	if !req.valid() {
		return fmt.Errorf("导入清单无效")
	}
	list, err := syncActivityDirectoriesLocked(ctx)
	if err != nil {
		return err
	}
	id := req.ActivityID
	if req.PhotoID != "" {
		photo, lookupErr := data.PhotoDAO.GetByID(ctx, req.PhotoID)
		if lookupErr != nil {
			return fmt.Errorf("导入回执对应的照片已删除或不可用: %w", lookupErr)
		}
		if id != "" && id != photo.ActivityID {
			return fmt.Errorf("导入回执的活动标识不一致")
		}
		id = photo.ActivityID
	}
	if id != "" {
		for _, item := range list {
			if item.Metadata.ID != id {
				continue
			}
			if req.Target != "" && filepath.Dir(req.Target) == req.Activity {
				req.Target = filepath.Join(item.Name, filepath.Base(req.Target))
			}
			req.ActivityID, req.Activity = id, item.Name
			req.activityNormalized = true
			return nil
		}
		return fmt.Errorf("导入回执对应的活动目录不存在，请重新选择活动")
	}
	meta, err := ensureActivityMetadata(ctx, req.Activity)
	if err != nil {
		return err
	}
	req.ActivityID = meta.ID
	req.activityNormalized = true
	return nil
}

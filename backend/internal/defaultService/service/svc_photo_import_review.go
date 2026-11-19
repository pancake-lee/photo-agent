package service

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"backend/internal/defaultService/conf"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

// Stage cleanup holds importStageFiles exclusively. Always acquire it first.
var importReviewFiles sync.Mutex

type importReviewEntry struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	SHA256   string `json:"sha256"`
	ShotAt   string `json:"shot_at,omitempty"`
	Decision string `json:"decision"`
	Origin   string `json:"origin"`
}

type importReviewManifest struct {
	BatchID   string              `json:"batch_id"`
	Name      string              `json:"name"`
	Activity  string              `json:"activity"`
	State     string              `json:"state"`
	Revision  uint64              `json:"revision"`
	UpdatedAt string              `json:"updated_at"`
	Entries   []importReviewEntry `json:"entries"`
	Fine      [][]string          `json:"fine,omitempty"`
	Coarse    [][]string          `json:"coarse,omitempty"`
}

func importReviewPath(id string) (string, error) {
	root, target, err := importStageLocation(id, strings.Repeat("0", 64))
	if err != nil {
		return "", err
	}
	return filepath.Join(root, filepath.Dir(target), "review.json"), nil
}

func readImportReview(id string) (*importReviewManifest, error) {
	path, err := importReviewPath(id)
	if err != nil {
		return nil, err
	}
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > 16<<20 {
		return nil, fmt.Errorf("选片清单不是有效普通文件")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var manifest importReviewManifest
	err = json.Unmarshal(raw, &manifest)
	if err != nil {
		return nil, err
	}
	if manifest.BatchID != id {
		return nil, fmt.Errorf("选片批次不匹配")
	}
	return &manifest, nil
}

func saveImportReview(manifest *importReviewManifest) error {
	path, err := importReviewPath(manifest.BatchID)
	if err != nil {
		return err
	}
	manifest.Revision++
	manifest.UpdatedAt = time.Now().UTC().Format(time.RFC3339Nano)
	raw, err := json.Marshal(manifest)
	if err != nil {
		return err
	}
	file, err := os.CreateTemp(filepath.Dir(path), ".review-*")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	_, err = file.Write(raw)
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(file.Name(), path)
}

func validImportReviewDecision(decision string) bool {
	switch decision {
	case "pending", "kept", "favorite", "discarded", "later":
		return true
	default:
		return false
	}
}

// Republishing updates metadata and membership, never existing decisions.
func publishImportReview(input importReviewManifest) (*importReviewManifest, error) {
	if len(input.Entries) == 0 || len(input.Entries) > 50000 {
		return nil, fmt.Errorf("选片清单需包含 1 到 50000 张照片")
	}
	previous, err := readImportReview(input.BatchID)
	if err != nil && !os.IsNotExist(err) {
		return nil, err
	}
	oldEntryMap := make(map[string]importReviewEntry)
	if previous != nil {
		if previous.State != "review" {
			return nil, fmt.Errorf("PC 已结束选片，请在 PC 返回选片后继续")
		}
		input.Revision = previous.Revision
		for _, entry := range previous.Entries {
			oldEntryMap[entry.ID] = entry
		}
	}
	input.State = "review"
	seenMap := make(map[string]bool)
	for i := range input.Entries {
		entry := &input.Entries[i]
		if entry.ID == "" || len(entry.ID) > 128 || seenMap[entry.ID] ||
			!validArchiveDigest(entry.SHA256) || !validImportReviewDecision(entry.Decision) ||
			entry.Name == "" || strings.ContainsAny(entry.Name, "/\\") || len(entry.Name) > 512 {
			return nil, fmt.Errorf("无效或重复的选片条目")
		}
		seenMap[entry.ID] = true
		root, target, err := importStageLocation(input.BatchID, entry.SHA256)
		if err != nil {
			return nil, err
		}
		info, err := os.Lstat(filepath.Join(root, target))
		if err != nil {
			return nil, fmt.Errorf("照片暂存未就绪: %s", entry.Name)
		}
		if !info.Mode().IsRegular() {
			return nil, fmt.Errorf("照片暂存不是普通文件")
		}
		if old, ok := oldEntryMap[entry.ID]; ok && old.SHA256 == entry.SHA256 {
			entry.Decision, entry.Origin = old.Decision, old.Origin
		}
	}
	// Ignore client supplied revision/state on a first publish.
	if previous == nil {
		input.Revision = 0
	}
	err = saveImportReview(&input)
	return &input, err
}

func (s *PhotoServer) publishImportReview(ctx khttp.Context) error {
	var input importReviewManifest
	ctx.Request().Body = http.MaxBytesReader(ctx.Response(), ctx.Request().Body, 16<<20)
	err := ctx.Bind(&input)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
	importStageFiles.RLock()
	defer importStageFiles.RUnlock()
	importReviewFiles.Lock()
	defer importReviewFiles.Unlock()
	manifest, err := publishImportReview(input)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	return ctx.Result(http.StatusOK, manifest)
}

func (s *PhotoServer) getImportReview(ctx khttp.Context) error {
	importStageFiles.RLock()
	defer importStageFiles.RUnlock()
	importReviewFiles.Lock()
	defer importReviewFiles.Unlock()
	manifest, err := readImportReview(ctx.Request().URL.Query().Get("batch_id"))
	if err != nil {
		if os.IsNotExist(err) {
			return ctx.Result(http.StatusNotFound, map[string]string{"error": "选片批次已清理，或尚未在 PC 开启手机选片"})
		}
		return apiPhotoArchiveError(ctx, err)
	}
	ctx.Response().Header().Set("Cache-Control", "no-store")
	return ctx.Result(http.StatusOK, manifest)
}

func (s *PhotoServer) listImportReviews(ctx khttp.Context) error {
	importStageFiles.RLock()
	defer importStageFiles.RUnlock()
	importReviewFiles.Lock()
	defer importReviewFiles.Unlock()
	dirs, err := os.ReadDir(filepath.Join(conf.C.Storage.PhotoSrc, importStageDirectory))
	if err != nil && !os.IsNotExist(err) {
		return apiPhotoArchiveError(ctx, err)
	}
	type summary struct {
		BatchID   string `json:"batch_id"`
		Name      string `json:"name"`
		State     string `json:"state"`
		UpdatedAt string `json:"updated_at"`
		Count     int    `json:"count"`
	}
	list := make([]summary, 0)
	for _, dir := range dirs {
		if !dir.IsDir() || !validReviewBatchID(dir.Name()) {
			continue
		}
		manifest, err := readImportReview(dir.Name())
		if err != nil {
			continue
		}
		list = append(list, summary{manifest.BatchID, manifest.Name, manifest.State, manifest.UpdatedAt, len(manifest.Entries)})
	}
	sort.Slice(list, func(i, j int) bool { return list[i].UpdatedAt > list[j].UpdatedAt })
	ctx.Response().Header().Set("Cache-Control", "no-store")
	return ctx.Result(http.StatusOK, list)
}

type importReviewChange struct {
	ID       string `json:"id"`
	Decision string `json:"decision"`
}

func patchImportReview(id string, changes []importReviewChange, state string) (*importReviewManifest, error) {
	manifest, err := readImportReview(id)
	if err != nil {
		return nil, err
	}
	if len(changes) > 0 {
		if manifest.State != "review" {
			return nil, fmt.Errorf("PC 已结束选片，本批次不能再修改")
		}
		indexMap := make(map[string]int)
		for i, entry := range manifest.Entries {
			indexMap[entry.ID] = i
		}
		for _, change := range changes {
			_, ok := indexMap[change.ID]
			if !ok || !validImportReviewDecision(change.Decision) {
				return nil, fmt.Errorf("无效的照片或选片决定")
			}
		}
		for _, change := range changes {
			entry := &manifest.Entries[indexMap[change.ID]]
			entry.Decision, entry.Origin = change.Decision, "manual"
		}
	}
	if state != "" {
		if state != "review" && state != "locked" {
			return nil, fmt.Errorf("无效的选片状态")
		}
		manifest.State = state
	}
	err = saveImportReview(manifest)
	return manifest, err
}

func (s *PhotoServer) editImportReview(ctx khttp.Context) error {
	var req struct {
		BatchID string               `json:"batch_id"`
		Changes []importReviewChange `json:"changes"`
		State   string               `json:"state,omitempty"`
	}
	ctx.Request().Body = http.MaxBytesReader(ctx.Response(), ctx.Request().Body, 4<<20)
	err := json.NewDecoder(io.LimitReader(ctx.Request().Body, 4<<20)).Decode(&req)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
	importStageFiles.RLock()
	defer importStageFiles.RUnlock()
	importReviewFiles.Lock()
	defer importReviewFiles.Unlock()
	manifest, err := patchImportReview(req.BatchID, req.Changes, req.State)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	return ctx.Result(http.StatusOK, manifest)
}

package service

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"net/http"
	"os/exec"
	"path/filepath"
	"sort"
	"sync"
	"time"

	"backend/internal/defaultService/data"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/putil"
)

type importReviewBurstInput struct {
	ID     string    `json:"id"`
	SHA256 string    `json:"sha256"`
	ShotAt time.Time `json:"shot_at,omitempty"`
}

type reviewBurstGroups struct {
	Fine   [][]string `json:"fine"`
	Coarse [][]string `json:"coarse"`
}

type importReviewBurstProgress struct {
	Done    int    `json:"done"`
	Total   int    `json:"total"`
	Failed  int    `json:"failed"`
	Message string `json:"message"`
}

type importReviewBurstJob struct {
	ID       string                    `json:"id"`
	State    string                    `json:"state"`
	Progress importReviewBurstProgress `json:"progress"`
	Groups   *reviewBurstGroups        `json:"groups,omitempty"`
	Error    string                    `json:"error,omitempty"`
	cancel   context.CancelFunc
	finished time.Time
	inputKey [32]byte
	batchID  string
}

var importReviewBurstJobs = struct {
	sync.Mutex
	jobs map[string]*importReviewBurstJob
}{jobs: make(map[string]*importReviewBurstJob)}

func (s *PhotoServer) startImportReviewBurst(ctx khttp.Context) error {
	var req struct {
		BatchID string                   `json:"batch_id"`
		Inputs  []importReviewBurstInput `json:"inputs"`
	}
	ctx.Request().Body = http.MaxBytesReader(ctx.Response(), ctx.Request().Body, 4<<20)
	err := ctx.Bind(&req)
	if err != nil || !validReviewBatchID(req.BatchID) || len(req.Inputs) == 0 {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": "需要批次和 JPG 清单"})
	}
	ids := make(map[string]bool)
	for _, input := range req.Inputs {
		if !validReviewBatchID(input.ID) || !validArchiveDigest(input.SHA256) || ids[input.ID] {
			return ctx.Result(http.StatusBadRequest, map[string]string{"error": "批次 JPG 清单无效"})
		}
		ids[input.ID] = true
	}
	root, target, err := importStageLocation(req.BatchID, req.Inputs[0].SHA256)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	if _, err = exec.LookPath("convert"); err != nil {
		return apiPhotoArchiveError(ctx, fmt.Errorf("服务器缺少 ImageMagick convert: %w", err))
	}
	config, err := loadBurstConfig(papp.NewAppCtx(ctx.Request().Context()))
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	keyPayload, err := json.Marshal(req)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	inputKey := sha256.Sum256(keyPayload)

	importReviewBurstJobs.Lock()
	now := time.Now()
	for id, existing := range importReviewBurstJobs.jobs {
		if existing.State == "running" {
			result := *existing
			importReviewBurstJobs.Unlock()
			if result.inputKey == inputKey {
				return ctx.Result(http.StatusOK, result)
			}
			return apiPhotoArchiveError(ctx, fmt.Errorf("服务器正在计算其他批次的连拍组，请稍后重试"))
		}
		if now.Sub(existing.finished) > time.Hour {
			delete(importReviewBurstJobs.jobs, id)
		}
	}
	jobCtx, cancel := context.WithTimeout(context.Background(), time.Hour)
	job := &importReviewBurstJob{ID: putil.UUID(), State: "running", cancel: cancel, inputKey: inputKey, batchID: req.BatchID,
		Progress: importReviewBurstProgress{Total: len(req.Inputs), Message: "准备计算连拍组"}}
	importReviewBurstJobs.jobs[job.ID] = job
	result := *job
	importReviewBurstJobs.Unlock()

	go func() {
		defer cancel()
		update := func(progress importReviewBurstProgress) {
			importReviewBurstJobs.Lock()
			job.Progress = progress
			importReviewBurstJobs.Unlock()
		}
		work := filepath.Join(root, filepath.Dir(target))
		groups, err := computeImportReviewBursts(jobCtx, work, req.Inputs, config, update)
		importReviewBurstJobs.Lock()
		defer importReviewBurstJobs.Unlock()
		job.finished = time.Now()
		if err != nil {
			job.State, job.Error = "failed", err.Error()
			if jobCtx.Err() == context.Canceled {
				job.State = "canceled"
			}
			return
		}
		job.State, job.Groups = "completed", &groups
	}()
	return ctx.Result(http.StatusOK, result)
}

func (s *PhotoServer) getImportReviewBurst(ctx khttp.Context) error {
	importReviewBurstJobs.Lock()
	job := importReviewBurstJobs.jobs[ctx.Request().URL.Query().Get("id")]
	if job == nil {
		importReviewBurstJobs.Unlock()
		return ctx.Result(http.StatusNotFound, map[string]string{"error": "连拍计算任务已不存在，可重新计算"})
	}
	result := *job
	importReviewBurstJobs.Unlock()
	return ctx.Result(http.StatusOK, result)
}

func (s *PhotoServer) cancelImportReviewBurst(ctx khttp.Context) error {
	var req struct {
		ID string `json:"id"`
	}
	err := ctx.Bind(&req)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
	importReviewBurstJobs.Lock()
	defer importReviewBurstJobs.Unlock()
	if job := importReviewBurstJobs.jobs[req.ID]; job != nil {
		job.cancel()
	}
	return ctx.Result(http.StatusOK, map[string]bool{"canceled": true})
}

// computeImportReviewBursts uses the library algorithm on the staged batch only.
// Missing capture times and files that cannot be read remain separate cards.
func computeImportReviewBursts(
	ctx context.Context, dir string, inputs []importReviewBurstInput, config burstConfig,
	update func(importReviewBurstProgress),
) (reviewBurstGroups, error) {
	list := make([]burstPhotoInfo, 0, len(inputs))
	progress := importReviewBurstProgress{Total: len(inputs), Message: "计算连拍组"}
	for _, input := range inputs {
		if err := ctx.Err(); err != nil {
			return reviewBurstGroups{}, err
		}
		progress.Done++
		if input.ShotAt.After(time.Unix(946684800, 0)) {
			path := filepath.Join(dir, input.SHA256+".jpg")
			digest, _, err := digestFile(path)
			if err == nil && digest == input.SHA256 {
				gray, grayErr := loadGrayMatrixContext(ctx, path)
				if grayErr == nil {
					photo := &data.PhotoDO{ID: input.ID, ShotAt: input.ShotAt}
					list = append(list, burstPhotoInfo{photo: photo, gray: gray, valid: true})
				} else {
					progress.Failed++
				}
			} else {
				progress.Failed++
			}
		}
		update(progress)
	}
	if err := ctx.Err(); err != nil {
		return reviewBurstGroups{}, err
	}
	sort.SliceStable(list, func(i, j int) bool { return list[i].photo.ShotAt.Before(list[j].photo.ShotAt) })
	result := reviewBurstGroups{
		Fine:   reviewBurstMemberIDs(splitBurstGroups(list, config.Fine)),
		Coarse: reviewBurstMemberIDs(splitBurstGroups(list, config.Coarse)),
	}
	progress.Message = "连拍组计算完成"
	update(progress)
	return result, nil
}

func reviewBurstMemberIDs(groups [][]burstPhotoInfo) [][]string {
	result := make([][]string, 0, len(groups))
	for _, group := range groups {
		if len(group) < 2 {
			continue
		}
		members := make([]string, 0, len(group))
		for _, member := range group {
			members = append(members, member.photo.ID)
		}
		result = append(result, members)
	}
	return result
}

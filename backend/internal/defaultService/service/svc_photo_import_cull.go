package service

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"net/http"
	"path/filepath"
	"sync"
	"time"

	"backend/internal/defaultService/conf"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/putil"
)

type importCullInput struct {
	ID     string `json:"id"`
	SHA256 string `json:"sha256"`
}

type importCullScore struct {
	Tier    string `json:"tier"`
	Rating  int    `json:"rating"`
	Rank    int    `json:"rank"`
	Why     string `json:"why"`
	Cluster string `json:"cluster"`
	Scene   string `json:"scene"`
	SHA256  string `json:"sha256"`
}

type importCullProgress struct {
	Done    int    `json:"done"`
	Total   int    `json:"total"`
	Failed  int    `json:"failed"`
	Message string `json:"message"`
}

type importCullJob struct {
	ID       string                      `json:"id"`
	State    string                      `json:"state"`
	Progress importCullProgress          `json:"progress"`
	Scores   map[string]*importCullScore `json:"scores,omitempty"`
	Failures map[string]bool             `json:"failures,omitempty"`
	Error    string                      `json:"error,omitempty"`
	cancel   context.CancelFunc
	finished time.Time
	inputKey [32]byte
}

var importCullJobs = struct {
	sync.Mutex
	jobs map[string]*importCullJob
}{jobs: make(map[string]*importCullJob)}

func (s *PhotoServer) startImportCull(ctx khttp.Context) error {
	var req struct {
		BatchID string            `json:"batch_id"`
		Scene   string            `json:"scene"`
		Inputs  []importCullInput `json:"inputs"`
	}
	ctx.Request().Body = http.MaxBytesReader(ctx.Response(), ctx.Request().Body, 4<<20)
	err := ctx.Bind(&req)
	if err != nil || !validReviewBatchID(req.BatchID) || len(req.Inputs) == 0 {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": "需要批次和待审 JPG 清单"})
	}
	ids := make(map[string]bool)
	for _, input := range req.Inputs {
		if !validReviewBatchID(input.ID) || !validArchiveDigest(input.SHA256) || ids[input.ID] {
			return ctx.Result(http.StatusBadRequest, map[string]string{"error": "待审 JPG 清单无效"})
		}
		ids[input.ID] = true
	}
	root, target, err := importStageLocation(req.BatchID, req.Inputs[0].SHA256)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	sourceDir := conf.C.AutoCull.SourceDir
	if _, _, _, err = autocullCommand(sourceDir); err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	keyPayload, err := json.Marshal(req)
	if err != nil {
		return apiPhotoArchiveError(ctx, err)
	}
	inputKey := sha256.Sum256(keyPayload)

	importCullJobs.Lock()
	now := time.Now()
	for id, existing := range importCullJobs.jobs {
		if existing.State == "running" {
			result := *existing
			importCullJobs.Unlock()
			if result.inputKey == inputKey {
				return ctx.Result(http.StatusOK, result)
			}
			return apiPhotoArchiveError(ctx, fmt.Errorf("服务器已有初筛任务，请稍后重试"))
		}
		if now.Sub(existing.finished) > time.Hour {
			delete(importCullJobs.jobs, id)
		}
	}
	jobCtx, cancel := context.WithTimeout(context.Background(), time.Hour)
	job := &importCullJob{ID: putil.UUID(), State: "running", cancel: cancel, inputKey: inputKey,
		Progress: importCullProgress{Total: len(req.Inputs), Message: "准备待审 JPG"}}
	importCullJobs.jobs[job.ID] = job
	result := *job
	importCullJobs.Unlock()

	go func() {
		defer cancel()
		update := func(progress importCullProgress) {
			importCullJobs.Lock()
			job.Progress = progress
			importCullJobs.Unlock()
		}
		work := filepath.Join(root, filepath.Dir(target))
		scores, failures, err := analyzeImportBatch(jobCtx, work, req.Inputs, sourceDir, req.Scene, update)
		importCullJobs.Lock()
		defer importCullJobs.Unlock()
		job.finished = time.Now()
		if err != nil {
			job.State, job.Error = "failed", err.Error()
			if jobCtx.Err() == context.Canceled {
				job.State = "canceled"
			}
			return
		}
		job.State, job.Scores, job.Failures = "completed", scores, failures
	}()
	return ctx.Result(http.StatusOK, result)
}

func (s *PhotoServer) getImportCull(ctx khttp.Context) error {
	importCullJobs.Lock()
	job := importCullJobs.jobs[ctx.Request().URL.Query().Get("id")]
	if job == nil {
		importCullJobs.Unlock()
		return ctx.Result(http.StatusNotFound, map[string]string{"error": "服务器初筛任务已不存在，可重试"})
	}
	result := *job
	importCullJobs.Unlock()
	return ctx.Result(http.StatusOK, result)
}

func (s *PhotoServer) cancelImportCull(ctx khttp.Context) error {
	var req struct {
		ID string `json:"id"`
	}
	err := ctx.Bind(&req)
	if err != nil {
		return ctx.Result(http.StatusBadRequest, map[string]string{"error": err.Error()})
	}
	importCullJobs.Lock()
	defer importCullJobs.Unlock()
	if job := importCullJobs.jobs[req.ID]; job != nil {
		job.cancel()
	}
	return ctx.Result(http.StatusOK, map[string]bool{"canceled": true})
}

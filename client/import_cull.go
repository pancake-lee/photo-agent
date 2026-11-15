package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

type ImportCullScore struct {
	Tier    string `json:"tier"`
	Rating  int    `json:"rating"`
	Rank    int    `json:"rank"`
	Why     string `json:"why"`
	Cluster string `json:"cluster"`
	Scene   string `json:"scene"`
	SHA256  string `json:"sha256"`
}

type ImportCullProgress struct {
	BatchID string `json:"batch_id"`
	Done    int    `json:"done"`
	Total   int    `json:"total"`
	Failed  int    `json:"failed"`
	Message string `json:"message"`
}

type reviewCullInput struct {
	ID     string `json:"id"`
	SHA256 string `json:"sha256"`
}

type reviewCullJob struct {
	ID       string                      `json:"id"`
	State    string                      `json:"state"`
	Progress ImportCullProgress          `json:"progress"`
	Scores   map[string]*ImportCullScore `json:"scores"`
	Failures map[string]bool             `json:"failures"`
	Error    string                      `json:"error"`
}

func reviewHTTP(ctx context.Context, server, path string, payload, result any) error {
	method := http.MethodGet
	var body io.Reader
	if payload != nil {
		method = http.MethodPost
		raw, err := json.Marshal(payload)
		if err != nil {
			return err
		}
		body = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, method, joinURL(server, "/api/v1/photo-import/"+path), body)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 20 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		var failure struct {
			Error string `json:"error"`
		}
		_ = json.NewDecoder(io.LimitReader(resp.Body, 8192)).Decode(&failure)
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, failure.Error)
	}
	return json.NewDecoder(io.LimitReader(resp.Body, 16<<20)).Decode(result)
}

func (a *App) CancelImportCull() {
	a.cullMu.Lock()
	defer a.cullMu.Unlock()
	if a.cancelCull != nil {
		a.cancelCull()
	}
}

func (a *App) ClearImportCull(id string) (*ImportBatch, error) {
	return a.editImportBatch(id, func(batch *ImportBatch) error {
		for i := range batch.Entries {
			batch.Entries[i].Score = nil
		}
		return nil
	})
}

func (a *App) AnalyzeImportBatch(id, server, scene string) (*ImportBatch, error) {
	a.cullMu.Lock()
	if a.cancelCull != nil {
		a.cullMu.Unlock()
		return nil, fmt.Errorf("已有初筛正在运行")
	}
	ctx, cancel := context.WithCancel(context.Background())
	a.cancelCull = cancel
	a.cullMu.Unlock()
	defer func() {
		cancel()
		a.cullMu.Lock()
		a.cancelCull = nil
		a.cullMu.Unlock()
	}()
	batch, err := a.GetImportBatch(id)
	if err != nil {
		return nil, err
	}
	var pending []ImportBatchEntry
	for _, entry := range batch.Entries {
		if entry.canStage() && entry.StagedServer == server && entry.Decision == batchPending &&
			!entry.Conflict && entry.Pair != "review" {
			pending = append(pending, entry)
		}
	}
	if len(pending) == 0 {
		return nil, fmt.Errorf("请先将待审 JPG 上传到服务器")
	}
	sort.Slice(pending, func(i, j int) bool { return pending[i].JPG.Path < pending[j].JPG.Path })
	inputs := make([]reviewCullInput, 0, len(pending))
	for _, entry := range pending {
		inputs = append(inputs, reviewCullInput{ID: entry.ID, SHA256: entry.JPG.SHA256})
	}
	var job reviewCullJob
	request := struct {
		BatchID string            `json:"batch_id"`
		Scene   string            `json:"scene"`
		Inputs  []reviewCullInput `json:"inputs"`
	}{id, scene, inputs}
	// Obtain the job ID even if cancellation arrives while the request starts.
	err = reviewHTTP(context.Background(), server, "cull/start", request, &job)
	if err != nil {
		return nil, err
	}
	if job.ID == "" {
		return nil, fmt.Errorf("服务器未返回初筛任务编号")
	}
	startedID := job.ID
	defer func() {
		if job.State == "running" && ctx.Err() != nil {
			var result map[string]bool
			stop, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			_ = reviewHTTP(stop, server, "cull/cancel", map[string]string{"id": startedID}, &result)
		}
	}()
	for {
		job.Progress.BatchID = id
		if a.ctx != nil {
			runtime.EventsEmit(a.ctx, "import:cull", job.Progress)
		}
		switch job.State {
		case "completed":
			return a.editImportBatch(id, func(latest *ImportBatch) error {
				for i := range latest.Entries {
					entry := &latest.Entries[i]
					if entry.JPG == nil || entry.StagedServer != server {
						continue
					}
					if score := job.Scores[entry.ID]; score != nil && score.SHA256 == entry.JPG.SHA256 {
						entry.Score = score
					} else if job.Failures[entry.ID] {
						entry.Score = nil
					}
				}
				return nil
			})
		case "failed", "canceled":
			return nil, fmt.Errorf("服务器初筛%s: %s", map[string]string{"failed": "失败", "canceled": "已取消"}[job.State], job.Error)
		case "running":
		default:
			return nil, fmt.Errorf("服务器返回了无效的初筛状态")
		}
		ticker := time.NewTimer(800 * time.Millisecond)
		select {
		case <-ctx.Done():
			ticker.Stop()
			return nil, ctx.Err()
		case <-ticker.C:
		}
		var next reviewCullJob
		err = reviewHTTP(ctx, server, "cull/status?id="+url.QueryEscape(startedID), nil, &next)
		if err != nil {
			return nil, err
		}
		job = next
	}
}

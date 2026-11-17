package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"slices"
	"sort"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

type ImportReviewBursts struct {
	Fine   [][]string `json:"fine"`
	Coarse [][]string `json:"coarse"`
	Server string     `json:"server"`
}

type ImportBurstProgress struct {
	BatchID string `json:"batch_id"`
	Done    int    `json:"done"`
	Total   int    `json:"total"`
	Failed  int    `json:"failed"`
	Message string `json:"message"`
}

type reviewBurstInput struct {
	ID     string `json:"id"`
	SHA256 string `json:"sha256"`
	ShotAt string `json:"shot_at,omitempty"`
}

type reviewBurstJob struct {
	ID       string              `json:"id"`
	State    string              `json:"state"`
	Progress ImportBurstProgress `json:"progress"`
	Groups   *ImportReviewBursts `json:"groups"`
	Error    string              `json:"error"`
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

func (a *App) CancelImportBursts() {
	a.burstMu.Lock()
	defer a.burstMu.Unlock()
	if a.cancelBurst != nil {
		a.cancelBurst()
	}
}

func importBurstInputs(batch *ImportBatch, server string) []reviewBurstInput {
	var pending []ImportBatchEntry
	for _, entry := range batch.Entries {
		if entry.canStage() && entry.StagedServer == server &&
			!entry.Conflict && entry.Pair != "review" {
			pending = append(pending, entry)
		}
	}
	sort.Slice(pending, func(i, j int) bool { return pending[i].JPG.Path < pending[j].JPG.Path })
	inputs := make([]reviewBurstInput, 0, len(pending))
	for _, entry := range pending {
		inputs = append(inputs, reviewBurstInput{ID: entry.ID, SHA256: entry.JPG.SHA256, ShotAt: entry.ShotAt})
	}
	return inputs
}

func (a *App) GroupImportBatch(id, server string) (_ *ImportBatch, retErr error) {
	trace := startImportTrace(id, "burst")
	counters := map[string]any{}
	defer func() { trace.finish(retErr, counters) }()
	a.burstMu.Lock()
	if a.cancelBurst != nil {
		a.burstMu.Unlock()
		return nil, fmt.Errorf("正在计算连拍组")
	}
	ctx, cancel := context.WithCancel(context.Background())
	a.cancelBurst = cancel
	a.burstMu.Unlock()
	defer func() {
		cancel()
		a.burstMu.Lock()
		a.cancelBurst = nil
		a.burstMu.Unlock()
	}()
	batch, err := a.GetImportBatch(id)
	if err != nil {
		return nil, err
	}
	if batch.workflowStep() != "review" {
		return nil, fmt.Errorf("请在选片步骤计算连拍组")
	}
	inputs := importBurstInputs(batch, server)
	if len(inputs) == 0 {
		return nil, fmt.Errorf("请先上传可选片的 JPG")
	}

	var job reviewBurstJob
	request := struct {
		BatchID string             `json:"batch_id"`
		Inputs  []reviewBurstInput `json:"inputs"`
	}{id, inputs}
	// Obtain the job ID even if cancellation arrives while the request starts.
	start := time.Now()
	err = reviewHTTP(context.Background(), server, "burst/start", request, &job)
	trace.add("start_job", start, 0)
	if err != nil {
		return nil, err
	}
	if job.ID == "" {
		return nil, fmt.Errorf("服务器未返回连拍计算任务编号")
	}
	startedID := job.ID
	counters["job_id"], counters["files"] = startedID, len(inputs)
	defer func() {
		if job.State == "running" && ctx.Err() != nil {
			var result map[string]bool
			stop, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			_ = reviewHTTP(stop, server, "burst/cancel", map[string]string{"id": startedID}, &result)
		}
	}()
	for {
		job.Progress.BatchID = id
		counters["failed"] = job.Progress.Failed
		if a.ctx != nil {
			runtime.EventsEmit(a.ctx, "import:burst", job.Progress)
		}
		switch job.State {
		case "completed":
			if job.Groups == nil {
				return nil, fmt.Errorf("服务器未返回连拍分组")
			}
			return a.editImportReview(id, func(latest *ImportBatch) error {
				if !slices.Equal(inputs, importBurstInputs(latest, server)) {
					return fmt.Errorf("批次照片已变化，请重新计算连拍组")
				}
				latest.Bursts = job.Groups
				latest.Bursts.Server = server
				return nil
			})
		case "failed", "canceled":
			return nil, fmt.Errorf("连拍计算%s: %s", map[string]string{"failed": "失败", "canceled": "已取消"}[job.State], job.Error)
		case "running":
		default:
			return nil, fmt.Errorf("服务器返回了无效的连拍计算状态")
		}
		ticker := time.NewTimer(800 * time.Millisecond)
		select {
		case <-ctx.Done():
			ticker.Stop()
			return nil, ctx.Err()
		case <-ticker.C:
		}
		var next reviewBurstJob
		start := time.Now()
		err = reviewHTTP(ctx, server, "burst/status?id="+url.QueryEscape(startedID), nil, &next)
		trace.add("poll_job", start, 0)
		if err != nil {
			return nil, err
		}
		job = next
	}
}

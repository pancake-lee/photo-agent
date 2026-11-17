package main

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

func (entry ImportBatchEntry) canStage() bool {
	return entry.JPG != nil && !entry.Historical && !entry.ReferenceOnly && entry.Decision != batchDiscarded &&
		(entry.Upload == nil || !entry.Upload.Verified)
}

func (a *App) StageImportJPGs(id, server string) (_ *ImportBatch, retErr error) {
	trace := startImportTrace(id, "stage")
	counters := map[string]any{}
	defer func() { trace.finish(retErr, counters) }()
	wait := time.Now()
	a.batchMu.Lock()
	trace.add("batch_lock_wait", wait, 0)
	defer a.batchMu.Unlock()
	root := importBatchRoot()
	batch, err := loadImportBatch(root, id)
	if err != nil {
		return nil, err
	}
	if batch.workflowStep() != "review" {
		return nil, fmt.Errorf("请在选片步骤上传暂存 JPG")
	}
	batch.Name, err = importBatchName(root, batch)
	if err != nil {
		return nil, err
	}
	for _, entry := range batch.Entries {
		if entry.StagedServer != "" && !slices.Contains(batch.StageServers, entry.StagedServer) {
			batch.StageServers = append(batch.StageServers, entry.StagedServer)
		}
	}
	err = trace.save(root, batch)
	if err != nil {
		return nil, err
	}
	total := 0
	for _, entry := range batch.Entries {
		if entry.canStage() {
			total++
		}
	}
	completed := 0
	ctx := trace.context(context.Background())
	reused, failed := 0, 0
	counters["files"] = total
	defer func() { counters["reused"], counters["failed"] = reused, failed }()
	for i := range batch.Entries {
		entry := &batch.Entries[i]
		if !entry.canStage() {
			continue
		}
		wasReadyForGrouping := entry.StagedServer == server && entry.canUpload()
		req := entry.archiveManifest(batch.Activity)
		req.BatchID, req.NEF, req.NEFTime = id, "", nil
		status, stageErr := archiveRPC(ctx, server, "stage/status", req, "", nil)
		if stageErr == nil && status.JPGStaged {
			reused++
		}
		if stageErr == nil && !slices.Contains(batch.StageServers, server) {
			// Persist the reachable staging server before it can receive any files.
			batch.StageServers = append(batch.StageServers, server)
			err = trace.save(root, batch)
			if err != nil {
				return nil, err
			}
		}
		if stageErr == nil && !status.JPGStaged {
			status, stageErr = archiveRPC(ctx, server, "stage/file", req, "jpg", entry.JPG)
		}
		if stageErr == nil && !status.JPGStaged {
			stageErr = fmt.Errorf("服务器尚未核验暂存 JPG")
		}
		if stageErr != nil {
			failed++
			entry.StagedServer, entry.StageError = "", stageErr.Error()
		} else {
			entry.StagedServer, entry.StageError = server, ""
		}
		if wasReadyForGrouping != (entry.StagedServer == server && entry.canUpload()) {
			batch.Bursts = nil
		}
		err = trace.save(root, batch)
		if err != nil {
			return nil, err
		}
		completed++
		if a.ctx != nil {
			progress := ImportUploadProgress{
				BatchID: id, Completed: completed, Total: total, Path: entry.JPG.Path,
				EntryID: entry.ID, StagedOn: entry.StagedServer, Error: entry.StageError,
			}
			runtime.EventsEmit(a.ctx, "import:stage", progress)
		}
	}
	return batch, nil
}

func cleanupImportBatchStage(batch *ImportBatch) error {
	servers := append([]string(nil), batch.StageServers...)
	for _, entry := range batch.Entries {
		servers = append(servers, entry.StagedServer)
	}
	if batch.Bursts != nil {
		servers = append(servers, batch.Bursts.Server)
	}
	seen := make(map[string]bool)
	for _, server := range servers {
		if server == "" || seen[server] {
			continue
		}
		seen[server] = true
		err := cleanupImportStage(context.Background(), server, batch.ID)
		if err != nil {
			return fmt.Errorf("清理 %s 上的批次暂存失败: %w", server, err)
		}
	}
	for i := range batch.Entries {
		batch.Entries[i].StagedServer = ""
	}
	batch.StageServers = nil
	return nil
}

func cleanupImportStage(ctx context.Context, server, id string) error {
	request := struct {
		BatchID string `json:"batch_id"`
	}{BatchID: id}
	var result struct {
		Cleaned bool `json:"cleaned"`
	}
	err := reviewHTTP(ctx, server, "stage/cleanup", request, &result)
	if err == nil && !result.Cleaned {
		return fmt.Errorf("服务器未确认清理结果")
	}
	return err
}

package main

import (
	"context"
	"fmt"
	"slices"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

func (entry ImportBatchEntry) canStage() bool {
	return entry.JPG != nil && !entry.Historical && !entry.ReferenceOnly && entry.Decision != batchDiscarded &&
		(entry.Upload == nil || !entry.Upload.Verified)
}

func (a *App) StageImportJPGs(id, server string) (*ImportBatch, error) {
	a.batchMu.Lock()
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
	err = saveImportBatch(root, batch)
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
	ctx := context.Background()
	for i := range batch.Entries {
		entry := &batch.Entries[i]
		if !entry.canStage() {
			continue
		}
		wasReadyForGrouping := entry.StagedServer == server && entry.canUpload()
		req := entry.archiveManifest(batch.Activity)
		req.BatchID, req.NEF, req.NEFTime = id, "", nil
		status, stageErr := archiveRPC(ctx, server, "stage/status", req, "", nil)
		if stageErr == nil && !slices.Contains(batch.StageServers, server) {
			// Persist the reachable staging server before it can receive any files.
			batch.StageServers = append(batch.StageServers, server)
			err = saveImportBatch(root, batch)
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
			entry.StagedServer, entry.StageError = "", stageErr.Error()
		} else {
			entry.StagedServer, entry.StageError = server, ""
		}
		if wasReadyForGrouping != (entry.StagedServer == server && entry.canUpload()) {
			batch.Bursts = nil
		}
		err = saveImportBatch(root, batch)
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

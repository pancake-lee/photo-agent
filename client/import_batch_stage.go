package main

import (
	"context"
	"fmt"

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
		req := entry.archiveManifest(batch.Activity)
		req.BatchID, req.NEF, req.NEFTime = id, "", nil
		status, stageErr := archiveRPC(ctx, server, "stage/status", req, "", nil)
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
		err = saveImportBatch(root, batch)
		if err != nil {
			return nil, err
		}
		completed++
		if a.ctx != nil {
			progress := ImportUploadProgress{BatchID: id, Completed: completed, Total: total, Path: entry.JPG.Path}
			runtime.EventsEmit(a.ctx, "import:stage", progress)
		}
	}
	return batch, nil
}

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

type ImportBatchUpload struct {
	JPGStaged bool   `json:"jpg_staged,omitempty"`
	Server    string `json:"server,omitempty"`
	Root      string `json:"root"`
	Target    string `json:"target"`
	NEFTarget string `json:"nef_target,omitempty"`
	JPGReady  bool   `json:"jpg_ready"`
	NEFReady  bool   `json:"nef_ready"`
	Verified  bool   `json:"verified"`
	PhotoID   string `json:"photo_id,omitempty"`
	Error     string `json:"error,omitempty"`
}

type ImportUploadProgress struct {
	BatchID   string `json:"batch_id"`
	Completed int    `json:"completed"`
	Total     int    `json:"total"`
	Path      string `json:"path"`
	EntryID   string `json:"entry_id,omitempty"`
	StagedOn  string `json:"staged_on,omitempty"`
	Error     string `json:"error,omitempty"`
}

type importArchiveManifest struct {
	BatchID  string     `json:"batch_id,omitempty"`
	Activity string     `json:"activity"`
	Name     string     `json:"name"`
	JPG      string     `json:"jpg_sha256"`
	NEF      string     `json:"nef_sha256,omitempty"`
	Favorite bool       `json:"favorite"`
	ShotAt   string     `json:"shot_at,omitempty"`
	JPGTime  time.Time  `json:"jpg_time"`
	NEFTime  *time.Time `json:"nef_time,omitempty"`
	Target   string     `json:"target,omitempty"`
}

type ImportBatchPlan struct {
	EntryID string            `json:"entry_id"`
	JPG     string            `json:"jpg"`
	NEF     string            `json:"nef,omitempty"`
	Plan    ImportBatchUpload `json:"plan"`
}

func parseImportShotTime(value string) string {
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02 15:04:05", "2006-01-02T15:04:05"} {
		parsed, err := time.ParseInLocation(layout, value, time.Local)
		if err == nil {
			return parsed.Format(time.RFC3339Nano)
		}
	}
	return ""
}

func (entry ImportBatchEntry) canUpload() bool {
	return !entry.Historical && entry.JPG != nil && !entry.ReferenceOnly && !entry.Conflict &&
		entry.Pair != "review" && entry.Decision != batchDiscarded
}

func (entry ImportBatchEntry) archiveManifest(activity string) importArchiveManifest {
	req := importArchiveManifest{
		Activity: activity, Name: filepath.Base(entry.JPG.Path), JPG: entry.JPG.SHA256,
		Favorite: entry.Decision == batchFavorite, ShotAt: entry.ShotAt, JPGTime: entry.JPG.ModTime,
	}
	if entry.NEF != nil {
		req.NEF, req.NEFTime = entry.NEF.SHA256, &entry.NEF.ModTime
	}
	return req
}

func archiveRPC(
	ctx context.Context, base, endpoint string, manifest importArchiveManifest,
	kind string, file *ImportBatchFile,
) (ImportBatchUpload, error) {
	var result ImportBatchUpload
	payload, err := json.Marshal(manifest)
	if err != nil {
		return result, err
	}
	var body io.Reader = bytes.NewReader(payload)
	contentType := "application/json"
	if file != nil {
		input, err := os.Open(file.Path)
		if err != nil {
			return result, err
		}
		defer input.Close()
		reader, writer := io.Pipe()
		defer reader.Close()
		multi := multipart.NewWriter(writer)
		contentType = multi.FormDataContentType()
		go func() {
			err := multi.WriteField("manifest", string(payload))
			if err == nil {
				var part io.Writer
				part, err = multi.CreateFormFile(kind, filepath.Base(file.Path))
				if err == nil {
					_, err = io.Copy(part, input)
				}
			}
			if err == nil {
				err = multi.Close()
			}
			_ = writer.CloseWithError(err)
		}()
		body = reader
	}
	url := joinURL(base, "/api/v1/photo-import/"+endpoint)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, body)
	if err != nil {
		return result, err
	}
	req.Header.Set("Content-Type", contentType)
	timeout := uploadTimeout
	if file == nil && endpoint == "preview" {
		timeout = 15 * time.Second
	}
	client := &http.Client{Timeout: timeout}
	resp, err := client.Do(req)
	if err != nil {
		return result, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		var failure struct {
			Error string `json:"error"`
		}
		_ = json.NewDecoder(io.LimitReader(resp.Body, 8192)).Decode(&failure)
		return result, fmt.Errorf("HTTP %d: %s", resp.StatusCode, failure.Error)
	}
	err = json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&result)
	if err == nil && (result.Target == "" || result.Verified &&
		(result.PhotoID == "" || !result.JPGReady || !result.NEFReady)) {
		err = fmt.Errorf("服务器返回了无效的归档状态")
	}
	return result, err
}

func (a *App) PreviewImportUploads(id, serverURL string) ([]ImportBatchPlan, error) {
	batch, err := a.GetImportBatch(id)
	if err != nil {
		return nil, err
	}
	plans := make([]ImportBatchPlan, 0)
	for _, entry := range batch.Entries {
		if !entry.canUpload() || entry.Upload != nil && entry.Upload.Verified {
			continue
		}
		req := entry.archiveManifest(batch.Activity)
		req.BatchID = id
		if entry.Upload != nil && entry.Upload.Server == serverURL &&
			(entry.Upload.JPGReady || entry.Upload.NEFReady) {
			req.Target = entry.Upload.Target
		}
		plan := ImportBatchPlan{EntryID: entry.ID, JPG: entry.JPG.Path}
		if entry.NEF != nil {
			plan.NEF = entry.NEF.Path
		}
		plan.Plan, err = archiveRPC(context.Background(), serverURL, "preview", req, "", nil)
		if err == nil {
			err = verifyImportLocalFiles(entry, plan.Plan)
		}
		if err != nil {
			plan.Plan.Error = err.Error()
		}
		plans = append(plans, plan)
	}
	byID := make(map[string]ImportBatchEntry)
	for _, entry := range batch.Entries {
		byID[entry.ID] = entry
	}
	assigned := make(map[string]string)
	for i := range plans {
		plan := &plans[i]
		if plan.Plan.Error != "" || plan.Plan.Target == "" {
			continue
		}
		entry := byID[plan.EntryID]
		key := entryFilesKey(entry)
		target := strings.ToLower(plan.Plan.Target)
		if before := assigned[target]; before != "" && before != key {
			req := entry.archiveManifest(batch.Activity)
			req.BatchID = id
			req.Name = importNameWithDigest(req)
			plan.Plan, err = archiveRPC(context.Background(), serverURL, "preview", req, "", nil)
			if err != nil {
				plan.Plan.Error = err.Error()
				continue
			}
			target = strings.ToLower(plan.Plan.Target)
			if before = assigned[target]; before != "" && before != key {
				plan.Plan.Error = "归档位置与同批次照片冲突，请核对"
				continue
			}
		}
		assigned[target] = key
	}
	return plans, nil
}

func importNameWithDigest(req importArchiveManifest) string {
	stem := strings.TrimSuffix(req.Name, filepath.Ext(req.Name))
	if len([]rune(stem)) > 30 {
		stem = string([]rune(stem)[:30])
	}
	suffix := req.JPG[:10]
	if req.NEF != "" {
		suffix += "_" + req.NEF[:8]
	}
	return stem + "_" + suffix + ".jpg"
}

func verifyImportLocalFiles(entry ImportBatchEntry, result ImportBatchUpload) error {
	for i, file := range []*ImportBatchFile{entry.JPG, entry.NEF} {
		if i == 0 && (result.JPGReady || result.JPGStaged) || i == 1 && result.NEFReady {
			continue
		}
		if file == nil {
			continue
		}
		if i == 0 {
			return fmt.Errorf("请先上传 JPG 到服务器暂存区: %s", file.Path)
		}
		digest, err := importFileDigest(file.Path)
		if err != nil {
			return fmt.Errorf("%s: %w", file.Path, err)
		}
		if digest != file.SHA256 {
			return fmt.Errorf("文件与扫描时不一致: %s", file.Path)
		}
	}
	return nil
}

func (a *App) UploadImportBatch(id, serverURL string, plans []ImportBatchPlan) (*ImportBatch, error) {
	a.batchMu.Lock()
	defer a.batchMu.Unlock()
	root := importBatchRoot()
	batch, err := loadImportBatch(root, id)
	if err != nil {
		return nil, err
	}
	if batch.Step != "" && batch.Step != "archive" {
		return nil, fmt.Errorf("请在入库步骤上传原片")
	}
	batch.Name, err = importBatchName(root, batch)
	if err != nil {
		return nil, err
	}
	byID := make(map[string]ImportBatchPlan)
	for _, plan := range plans {
		if plan.Plan.Target != "" && plan.Plan.Error == "" {
			byID[plan.EntryID] = plan
		}
	}
	ctx := context.Background()
	completed := 0
	for i := range batch.Entries {
		entry := &batch.Entries[i]
		plan, selected := byID[entry.ID]
		if !selected || !entry.canUpload() || entry.Upload != nil && entry.Upload.Verified {
			continue
		}
		req := entry.archiveManifest(batch.Activity)
		req.BatchID = id
		req.Target = plan.Plan.Target
		saveReceipt := func(receipt ImportBatchUpload) error {
			receipt.Server = serverURL
			entry.Upload = &receipt
			return saveImportBatch(root, batch)
		}
		current, err := archiveRPC(ctx, serverURL, "preview", req, "", nil)
		if err == nil && current.Target != req.Target {
			err = fmt.Errorf("服务器目标已变，请重新预览")
		}
		if err == nil {
			err = verifyImportLocalFiles(*entry, current)
		}
		if err == nil && !current.JPGReady {
			before := current
			current, err = archiveRPC(ctx, serverURL, "stage/archive", req, "", nil)
			if err != nil {
				current = before
			} else if saveErr := saveReceipt(current); saveErr != nil {
				return nil, saveErr
			}
		}
		if err == nil && entry.NEF != nil && !current.NEFReady {
			before := current
			current, err = archiveRPC(ctx, serverURL, "file", req, "nef", entry.NEF)
			if err != nil {
				current = before
			} else if saveErr := saveReceipt(current); saveErr != nil {
				return nil, saveErr
			}
		}
		if err == nil {
			before := current
			current, err = archiveRPC(ctx, serverURL, "finish", req, "", nil)
			if err != nil {
				current = before
			}
		}
		if err != nil {
			current.Error = err.Error()
			current.Verified = false
			if current.Target == "" {
				current.Target, current.Root, current.NEFTarget = plan.Plan.Target, plan.Plan.Root, plan.Plan.NEFTarget
			}
		}
		err = saveReceipt(current)
		if err != nil {
			return nil, err
		}
		completed++
		if a.ctx != nil {
			progress := ImportUploadProgress{BatchID: id, Completed: completed, Total: len(byID), Path: entry.JPG.Path}
			runtime.EventsEmit(a.ctx, "import:upload", progress)
		}
	}
	return batch, nil
}

package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"testing"
)

func TestClientUsesStagedJPGAndSendsOnlyNEFAtConfirmation(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("fixture redirects the application config using XDG_CONFIG_HOME")
	}
	root := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", root)
	jpgPath, nefPath := filepath.Join(root, "pair.JPG"), filepath.Join(root, "pair.NEF")
	writeFile(t, jpgPath, []byte("original jpg"))
	writeFile(t, nefPath, []byte("original nef"))
	jpg, err := inspectBatchFile(jpgPath, root)
	if err != nil {
		t.Fatal(err)
	}
	nef, err := inspectBatchFile(nefPath, root)
	if err != nil {
		t.Fatal(err)
	}
	batch := &ImportBatch{ID: strings.Repeat("a", 32), Activity: "demo", Entries: []ImportBatchEntry{{
		ID: strings.Repeat("b", 32), JPG: jpg, NEF: nef, Decision: batchPending, Pair: "paired",
	}}}
	err = saveImportBatch(importBatchRoot(), batch)
	if err != nil {
		t.Fatal(err)
	}
	calls := make(chan string, 10)
	var cleanupAttempts atomic.Int32
	staged, jpgReady, nefReady := false, false, false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		endpoint := strings.TrimPrefix(r.URL.Path, "/api/v1/photo-import/")
		calls <- endpoint
		if endpoint == "stage/cleanup" {
			var req struct {
				BatchID string `json:"batch_id"`
			}
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.BatchID != batch.ID {
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			if cleanupAttempts.Add(1) == 1 {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]bool{"cleaned": true})
			return
		}
		isFile := endpoint == "stage/file" || endpoint == "file"
		if isFile {
			req, file, kind, err := readTestReviewUpload(r)
			if err != nil || req.BatchID != batch.ID {
				http.Error(w, "invalid upload", http.StatusBadRequest)
				return
			}
			if endpoint == "stage/file" && kind == "jpg" && req.NEF == "" && file == "original jpg" {
				staged = true
			}
			if endpoint == "file" && kind == "nef" && req.NEF == nef.SHA256 && jpgReady && file == "original nef" {
				nefReady = true
			}
		}
		if endpoint == "stage/archive" && staged {
			jpgReady = true
		}
		result := ImportBatchUpload{Target: "demo/pair.jpg", NEFTarget: "demo/pair.nef",
			JPGStaged: staged, JPGReady: jpgReady, NEFReady: nefReady}
		if endpoint == "finish" && jpgReady && nefReady {
			result.Verified, result.PhotoID = true, "photo-id"
		}
		_ = json.NewEncoder(w).Encode(result)
	}))
	defer server.Close()

	app := NewApp()
	out, err := app.StageImportJPGs(batch.ID, server.URL)
	if err != nil || out.Entries[0].StagedServer != server.URL {
		t.Fatalf("stage result %#v %v", out, err)
	}
	if _, err := app.FinishImportBatch(batch.ID); err == nil {
		t.Fatal("cleanup should wait for the end of the workflow")
	}
	advance := func(step string, leaveLocal bool) {
		t.Helper()
		out, err := app.AdvanceImportBatch(batch.ID, step, leaveLocal)
		if err != nil || out.Step != step {
			t.Fatalf("continue to %s: %#v %v", step, out, err)
		}
	}
	advance("reject", false)
	advance("archive", false)
	if _, err := app.AdvanceImportBatch(batch.ID, "keep", false); err == nil {
		t.Fatal("local originals cannot be recycled before archive verification")
	}
	// Having a valid server copy is enough to proceed with the JPG absent locally.
	err = os.Remove(jpgPath)
	if err != nil {
		t.Fatal(err)
	}
	plans, err := app.PreviewImportUploads(batch.ID, server.URL)
	if err != nil || len(plans) != 1 || plans[0].Plan.Error != "" || !plans[0].Plan.JPGStaged {
		t.Fatalf("archive preview %#v %v", plans, err)
	}
	out, err = app.UploadImportBatch(batch.ID, server.URL, plans)
	if err != nil || out.Entries[0].Upload == nil || !out.Entries[0].Upload.Verified {
		t.Fatalf("confirm result %#v %v", out, err)
	}
	advance("keep", false)
	if _, err := app.AdvanceImportBatch(batch.ID, "finish", false); err == nil {
		t.Fatal("the remaining originals should require a decision")
	}
	writeFile(t, jpgPath, []byte("original jpg"))
	advance("finish", true)
	if _, err := app.FinishImportBatch(batch.ID); err == nil {
		t.Fatal("cleanup should report that it failed")
	}
	resumed, err := app.GetImportBatch(batch.ID)
	if err != nil || resumed.Step != "finish" || resumed.Entries[0].StagedServer != server.URL {
		t.Fatalf("cleanup retry was not persisted: %#v %v", resumed, err)
	}
	out, err = app.FinishImportBatch(batch.ID)
	if err != nil || out.Step != "done" || out.Entries[0].StagedServer != "" ||
		!out.Entries[0].Upload.Verified {
		t.Fatalf("cleanup result %#v %v", out, err)
	}
	if _, err := app.FinishImportBatch(batch.ID); err != nil {
		t.Fatal(err)
	}
	close(calls)
	var actual []string
	for endpoint := range calls {
		actual = append(actual, endpoint)
	}
	assertStrSlice(t, actual, []string{"stage/status", "stage/file", "preview", "preview", "stage/archive", "file", "finish", "stage/cleanup", "stage/cleanup"})
}

func TestAbandonImportBatchRetriesOnlyStagingCleanup(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("fixture redirects the application config using XDG_CONFIG_HOME")
	}
	root := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", root)
	const abandonID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	const doneID = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	const draftID = "cccccccccccccccccccccccccccccccc"
	var attempts atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			BatchID string `json:"batch_id"`
		}
		err := json.NewDecoder(r.Body).Decode(&req)
		if err != nil || req.BatchID != abandonID || r.URL.Path != "/api/v1/photo-import/stage/cleanup" {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if attempts.Add(1) == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]bool{"cleaned": true})
	}))
	defer server.Close()

	local := filepath.Join(root, "original.JPG")
	writeFile(t, local, []byte("original"))
	for _, batch := range []ImportBatch{
		{ID: doneID, Activity: "完成", Step: "done"},
		{ID: draftID, Activity: "草稿"},
		{ID: abandonID, Activity: "待废弃", Step: "archive", StageServers: []string{server.URL},
			Entries: []ImportBatchEntry{{ID: "photo", JPG: &ImportBatchFile{Path: local},
				StagedServer: server.URL, Upload: &ImportBatchUpload{PhotoID: "verified", Verified: true}}}},
	} {
		if err := saveImportBatch(importBatchRoot(), &batch); err != nil {
			t.Fatal(err)
		}
	}
	app := NewApp()
	if err := app.AbandonImportBatch(doneID); err == nil {
		t.Fatal("completed batches should stay completed")
	}
	if err := app.AbandonImportBatch(abandonID); err == nil {
		t.Fatal("failed cleanup was reported as successful")
	}
	list, err := app.ListImportBatches()
	if err != nil || len(list) != 2 {
		t.Fatalf("retry list = %#v: %v", list, err)
	}
	for _, item := range list {
		if item.ID == doneID || item.ID == abandonID && item.Step != "abandoning" {
			t.Fatalf("unexpected resumable batch: %#v", item)
		}
	}
	if _, err := app.AdvanceImportBatch(abandonID, "review", false); err == nil {
		t.Fatal("a batch waiting for cleanup must not resume importing")
	}
	if err := app.AbandonImportBatch(abandonID); err != nil {
		t.Fatal(err)
	}
	if err := app.AbandonImportBatch(abandonID); err != nil || attempts.Load() != 2 {
		t.Fatalf("discard retry was not idempotent: %d, %v", attempts.Load(), err)
	}
	list, err = app.ListImportBatches()
	if err != nil || len(list) != 1 || list[0].ID != draftID {
		t.Fatalf("active batches = %#v: %v", list, err)
	}
	batch, err := app.GetImportBatch(abandonID)
	if err != nil || batch.Step != "abandoned" || len(batch.StageServers) != 0 ||
		batch.Entries[0].StagedServer != "" || batch.Entries[0].Upload.PhotoID != "verified" {
		t.Fatalf("discarded batch receipt = %#v: %v", batch, err)
	}
	data, err := os.ReadFile(local)
	if err != nil || string(data) != "original" {
		t.Fatalf("local original was changed: %q %v", data, err)
	}
}

func readTestReviewUpload(r *http.Request) (importArchiveManifest, string, string, error) {
	var req importArchiveManifest
	reader, err := r.MultipartReader()
	if err != nil {
		return req, "", "", err
	}
	manifest, err := reader.NextPart()
	if err != nil {
		return req, "", "", err
	}
	err = json.NewDecoder(manifest).Decode(&req)
	if err != nil {
		return req, "", "", err
	}
	file, err := reader.NextPart()
	if err != nil {
		return req, "", "", err
	}
	raw, err := io.ReadAll(file)
	return req, string(raw), file.FormName(), err
}

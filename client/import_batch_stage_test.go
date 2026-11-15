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
		ID: strings.Repeat("b", 32), JPG: jpg, NEF: nef, Decision: batchKept, Pair: "paired",
	}}}
	err = saveImportBatch(importBatchRoot(), batch)
	if err != nil {
		t.Fatal(err)
	}
	calls := make(chan string, 10)
	staged, jpgReady, nefReady := false, false, false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		endpoint := strings.TrimPrefix(r.URL.Path, "/api/v1/photo-import/")
		calls <- endpoint
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
	close(calls)
	var actual []string
	for endpoint := range calls {
		actual = append(actual, endpoint)
	}
	assertStrSlice(t, actual, []string{"stage/status", "stage/file", "preview", "preview", "stage/archive", "file", "finish"})
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

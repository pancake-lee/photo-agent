package service

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

func TestStagedReviewHTTP(t *testing.T) {
	app, root := setupUserPathTest(t)
	router := khttp.NewServer(khttp.Timeout(50 * time.Millisecond))
	(&PhotoServer{}).Reg(nil, router)
	server := httptest.NewServer(router)
	defer server.Close()
	if runtime.GOOS != "windows" {
		conf.C.AutoCull.SourceDir = fakeAutoCull(t, root, false)
	}
	jpg, nef := archiveTestJPG(t, 90), []byte("original NEF")
	req := archiveTestRequest("stage-test", jpg, nef, true)
	req.BatchID = strings.Repeat("a", 32)
	base := server.URL + "/api/v1/photo-import/"
	request := func(method, path string, body any, code int, result any) {
		t.Helper()
		resp := doJSONRequest(t, server.Client(), method, base+path, body)
		readArchiveTestResponse(t, resp, code, result)
	}
	upload := func(path, kind string, input archiveImportRequest, file []byte, code int) archiveImportResult {
		t.Helper()
		return archiveTestUploadAt(t, server, path, input, kind, file, code)
	}

	stageReq := req
	stageReq.NEF, stageReq.NEFTime = "", nil
	var status archiveImportResult
	request(http.MethodPost, "stage/status", stageReq, 200, &status)
	if status.JPGStaged {
		t.Fatal("JPG already staged")
	}
	upload("stage/file", "jpg", stageReq, []byte("corrupt"), http.StatusConflict)
	upload("stage/file", "nef", req, nef, http.StatusBadRequest)
	status = upload("stage/file", "jpg", stageReq, jpg, http.StatusOK)
	if !status.JPGStaged || status.Verified {
		t.Fatalf("staging receipt = %#v", status)
	}
	if n, _ := countFiles(conf.C.Storage.PhotoSrc); n != 0 {
		t.Fatalf("staging is counted as archive: %d", n)
	}

	imagePath := "stage/image?batch_id=" + req.BatchID + "&sha256=" + req.JPG
	resp := doJSONRequest(t, server.Client(), http.MethodGet, base+imagePath, nil)
	got, err := io.ReadAll(resp.Body)
	resp.Body.Close()
	if err != nil || resp.StatusCode != http.StatusOK || !bytes.Equal(got, jpg) {
		t.Fatalf("server review image status %d: %v", resp.StatusCode, err)
	}
	request(http.MethodGet, "stage/image?batch_id=../&sha256="+req.JPG, nil, http.StatusBadRequest, nil)

	if conf.C.AutoCull.SourceDir != "" {
		id := strings.Repeat("b", 32)
		var job importCullJob
		start := map[string]any{"batch_id": req.BatchID, "scene": "auto", "inputs": []importCullInput{{id, req.JPG}}}
		request(http.MethodPost, "cull/start", start, 200, &job)
		until := time.Now().Add(5 * time.Second)
		for job.State == "running" && time.Now().Before(until) {
			time.Sleep(20 * time.Millisecond)
			var next importCullJob
			request(http.MethodGet, "cull/status?id="+job.ID, nil, 200, &next)
			job = next
		}
		if job.State != "completed" || job.Scores[id] == nil || job.Scores[id].Rating != 0 {
			t.Fatalf("review job = %#v", job)
		}
		digest, _, err := digestFile(filepath.Join(status.Root, status.Target))
		if err != nil || digest != req.JPG {
			t.Fatalf("runner changed staged JPG: %s %v", digest, err)
		}
	}
	var archived archiveImportResult
	request(http.MethodPost, "preview", req, 200, &archived)
	if archived.JPGReady || !archived.JPGStaged || archived.NEFReady {
		t.Fatalf("archive preview = %#v", archived)
	}
	req.Target = archived.Target
	request(http.MethodPost, "stage/archive", req, 200, &archived)
	if !archived.JPGReady || archived.Verified {
		t.Fatalf("archive JPG = %#v", archived)
	}
	request(http.MethodPost, "finish", req, http.StatusConflict, nil)
	upload("file", "nef", req, nef, 200)
	request(http.MethodPost, "finish", req, 200, &archived)
	row, err := data.PhotoDAO.GetByID(app, archived.PhotoID)
	if err != nil || !archived.Verified || row.Timeline != req.Activity {
		t.Fatalf("verified archive = %#v, row %#v, error %v", archived, row, err)
	}
}

func fakeAutoCull(t *testing.T, root string, cancel bool) string {
	t.Helper()
	source := filepath.Join(root, "autocull")
	python := filepath.Join(source, ".venv", "bin", "python")
	if err := os.MkdirAll(filepath.Dir(python), 0700); err != nil {
		t.Fatal(err)
	}
	action := `file=$(printf '%s' *.jpg)
mkdir -p _cull_out/autocull
printf 'filename,rating,tier,rank,why,cluster\n%s,0,tail,-1,test,3\n' "$file" > _cull_out/autocull/tiers.csv
printf 'only the workspace copy changes' > "$file"`
	if cancel {
		action = "printf 'analyzing\\n'\nexec sleep 30"
	}
	script := fmt.Sprintf(`#!/bin/sh
set -eu
[ "$1" = "-m" ] && [ "$2" = "autocull" ]
if [ "$3" = "--version" ]; then
  printf 'autocull 1.4.9\n'
  exit 0
fi
cd "$4"
%s
`, action)
	if err := os.WriteFile(python, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	return source
}

func TestServerCullCancellationCleansWorkspace(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX AutoCull fixture")
	}
	root := t.TempDir()
	executable := fakeAutoCull(t, root, true)
	jpg := archiveTestJPG(t, 28)
	req := archiveTestRequest("activity", jpg, nil, false)
	err := os.WriteFile(filepath.Join(root, req.JPG+".jpg"), jpg, 0600)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	start := time.Now()
	_, _, err = analyzeImportBatch(ctx, root, []importCullInput{{strings.Repeat("c", 32), req.JPG}}, executable, "auto", func(progress importCullProgress) {
		if progress.Message == "analyzing" {
			cancel()
		}
	})
	if err != context.Canceled || time.Since(start) > 4*time.Second {
		t.Fatalf("cancel error %v", err)
	}
	paths, err := filepath.Glob(filepath.Join(root, "cull-*"))
	if err != nil || len(paths) != 0 {
		t.Fatalf("orphaned analysis workspace: %v, %v", paths, err)
	}
}

func TestReadCullScoresRejectsDuplicates(t *testing.T) {
	path := filepath.Join(t.TempDir(), "tiers.csv")
	raw := "\xef\xbb\xbffilename,rating,tier,rank,why,cluster\n" +
		"a.jpg,4,top5,1,sharp,1\na.jpg,1,reject,-1,duplicate,\nb.jpg,0,tail,-1,good,3\n"
	if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
		t.Fatal(err)
	}
	manifest := map[string]importCullInput{"a.jpg": {"a", "digest-a"}, "b.jpg": {"b", "digest-b"}}
	scores, err := readCullScores(path, manifest, "auto")
	if err != nil || len(scores) != 1 || scores["b"] == nil || scores["b"].Rating != 0 {
		t.Fatalf("scores %#v, error %v", scores, err)
	}
}

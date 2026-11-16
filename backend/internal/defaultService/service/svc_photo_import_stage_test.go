package service

import (
	"bytes"
	"image/jpeg"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

func TestStagedReviewHTTP(t *testing.T) {
	app, _ := setupUserPathTest(t)
	router := khttp.NewServer(khttp.Timeout(50 * time.Millisecond))
	(&PhotoServer{}).Reg(nil, router)
	server := httptest.NewServer(router)
	defer server.Close()

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

	if _, err := exec.LookPath("convert"); err == nil {
		staged := filepath.Join(status.Root, status.Target)
		thumbnail := filepath.Join(filepath.Dir(staged), "thumbnails", filepath.Base(staged))
		deadline := time.Now().Add(3 * time.Second)
		for {
			_, previewErr := os.Stat(thumbnail)
			_, grayErr := os.Stat(staged + ".gray.json")
			if previewErr == nil && grayErr == nil {
				break
			}
			if time.Now().After(deadline) {
				t.Fatalf("upload did not prepare the preview and grouping data: %v, %v", previewErr, grayErr)
			}
			time.Sleep(20 * time.Millisecond)
		}
		thumb := doJSONRequest(t, server.Client(), http.MethodGet, base+imagePath+"&size=thumbnail", nil)
		_, decodeErr := jpeg.DecodeConfig(thumb.Body)
		thumb.Body.Close()
		if decodeErr != nil || thumb.StatusCode != http.StatusOK ||
			thumb.Header.Get("Cache-Control") == "no-store" {
			t.Fatalf("server thumbnail status %d: %v", thumb.StatusCode, decodeErr)
		}
		at := req.JPGTime.Add(-time.Hour)
		inputs := []importReviewBurstInput{
			{ID: strings.Repeat("b", 32), SHA256: req.JPG, ShotAt: at},
			{ID: strings.Repeat("c", 32), SHA256: req.JPG, ShotAt: at.Add(time.Second)},
			{ID: strings.Repeat("d", 32), SHA256: req.JPG, ShotAt: at.Add(20 * time.Minute)},
			{ID: strings.Repeat("e", 32), SHA256: req.JPG},
		}
		var job importReviewBurstJob
		start := map[string]any{"batch_id": req.BatchID, "inputs": inputs}
		request(http.MethodPost, "burst/start", start, 200, &job)
		until := time.Now().Add(5 * time.Second)
		for job.State == "running" && time.Now().Before(until) {
			time.Sleep(20 * time.Millisecond)
			var next importReviewBurstJob
			request(http.MethodGet, "burst/status?id="+job.ID, nil, 200, &next)
			job = next
		}
		if job.State != "completed" || job.Groups == nil || len(job.Groups.Fine) != 1 ||
			len(job.Groups.Fine[0]) != 2 || job.Groups.Fine[0][0] != inputs[0].ID ||
			job.Groups.Fine[0][1] != inputs[1].ID {
			t.Fatalf("review job = %#v, groups %#v", job, job.Groups)
		}
		digest, _, err := digestFile(filepath.Join(status.Root, status.Target))
		if err != nil || digest != req.JPG {
			t.Fatalf("grouping changed staged JPG: %s %v", digest, err)
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

	other := stageReq
	other.BatchID = strings.Repeat("f", 32)
	upload("stage/file", "jpg", other, jpg, http.StatusOK)
	request(http.MethodPost, "stage/cleanup", map[string]string{"batch_id": "../" + req.Activity}, http.StatusBadRequest, nil)
	cleanup := map[string]string{"batch_id": req.BatchID}
	request(http.MethodPost, "stage/cleanup", cleanup, http.StatusOK, nil)
	request(http.MethodPost, "stage/cleanup", cleanup, http.StatusOK, nil)
	if _, err := os.Stat(filepath.Join(status.Root, req.BatchID)); !os.IsNotExist(err) {
		t.Fatalf("batch staging directory survives cleanup: %v", err)
	}
	request(http.MethodGet, imagePath, nil, http.StatusNotFound, nil)
	request(http.MethodPost, "stage/status", other, http.StatusOK, &status)
	if !status.JPGStaged {
		t.Fatal("another batch lost its staged JPG")
	}
	for name, want := range map[string][]byte{archived.Target: jpg, archived.NEFTarget: nef} {
		contents, err := os.ReadFile(filepath.Join(archived.Root, name))
		if err != nil || !bytes.Equal(contents, want) {
			t.Fatalf("archive changed during cleanup for %s: %v", name, err)
		}
	}
}

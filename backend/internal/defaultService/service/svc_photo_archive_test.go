package service

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/jpeg"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

func archiveTestJPG(t *testing.T, clr uint8) []byte {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, 2, 2))
	img.Set(0, 0, color.RGBA{R: clr, A: 255})
	var out bytes.Buffer
	err := jpeg.Encode(&out, img, nil)
	if err != nil {
		t.Fatal(err)
	}
	return out.Bytes()
}

func archiveTestRequest(activity string, jpg, nef []byte, favorite bool) archiveImportRequest {
	mod := time.Unix(1760000000, 456000000).UTC()
	shot := mod.Add(-time.Hour)
	req := archiveImportRequest{Activity: activity, Name: "DSC_0123.JPG", Favorite: favorite,
		JPG: fmt.Sprintf("%x", sha256.Sum256(jpg)), JPGTime: mod, ShotAt: &shot}
	if nef != nil {
		req.NEF, req.NEFTime = fmt.Sprintf("%x", sha256.Sum256(nef)), &mod
	}
	return req
}

type delayedArchiveBody struct {
	reader  *bytes.Buffer
	delayed bool
}

func (body *delayedArchiveBody) Read(target []byte) (int, error) {
	if body.delayed {
		time.Sleep(140 * time.Millisecond)
		body.delayed = false
		return body.reader.Read(target)
	}
	if len(target) > 350 {
		target = target[:350]
	}
	body.delayed = true
	return body.reader.Read(target)
}

func archiveTestUpload(t *testing.T, server *httptest.Server, req archiveImportRequest, kind string, file []byte, code int) archiveImportResult {
	t.Helper()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	raw, err := json.Marshal(req)
	if err != nil {
		t.Fatal(err)
	}
	err = writer.WriteField("manifest", string(raw))
	if err != nil {
		t.Fatal(err)
	}
	part, err := writer.CreateFormFile(kind, req.Name)
	if err != nil {
		t.Fatal(err)
	}
	_, err = part.Write(file)
	if err != nil {
		t.Fatal(err)
	}
	err = writer.Close()
	if err != nil {
		t.Fatal(err)
	}
	var requestBody io.Reader = &body
	if kind == "nef" {
		requestBody = &delayedArchiveBody{reader: &body}
	}
	resp, err := server.Client().Post(server.URL+"/api/v1/photo-import/file", writer.FormDataContentType(), requestBody)
	if err != nil {
		t.Fatal(err)
	}
	var result archiveImportResult
	readArchiveTestResponse(t, resp, code, &result)
	return result
}

func readArchiveTestResponse(t *testing.T, response *http.Response, code int, dest any) {
	t.Helper()
	defer response.Body.Close()
	raw, err := io.ReadAll(response.Body)
	if err != nil || response.StatusCode != code {
		t.Fatalf("HTTP %d, want %d, body %s, err %v", response.StatusCode, code, raw, err)
	}
	if dest != nil && code == http.StatusOK {
		err = json.Unmarshal(raw, dest)
		if err != nil {
			t.Fatalf("decode %s: %v", raw, err)
		}
	}
}

func TestVerifiedImportHTTPAndRecycle(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	router := khttp.NewServer(khttp.Timeout(100 * time.Millisecond))
	(&PhotoServer{}).Reg(nil, router)
	server := httptest.NewServer(router)
	defer server.Close()

	preview := func(req archiveImportRequest) archiveImportResult {
		var plan archiveImportResult
		resp := doJSONRequest(t, server.Client(), http.MethodPost, server.URL+"/api/v1/photo-import/preview", req)
		readArchiveTestResponse(t, resp, http.StatusOK, &plan)
		return plan
	}
	finish := func(req archiveImportRequest, code int) archiveImportResult {
		var result archiveImportResult
		resp := doJSONRequest(t, server.Client(), http.MethodPost, server.URL+"/api/v1/photo-import/finish", req)
		readArchiveTestResponse(t, resp, code, &result)
		return result
	}
	jpg, nef := archiveTestJPG(t, 90), []byte("original NEF sample")
	req := archiveTestRequest("桂林", jpg, nef, true)
	plan := preview(req)
	req.Target = plan.Target
	if plan.JPGReady || plan.Verified || plan.NEFTarget == "" {
		t.Fatalf("initial plan = %#v", plan)
	}
	archiveTestUpload(t, server, req, "jpg", []byte("wrong digest"), http.StatusConflict)
	if got := preview(req); got.JPGReady {
		t.Fatalf("mismatched upload was accepted: %#v", got)
	}
	partial := archiveTestUpload(t, server, req, "jpg", jpg, http.StatusOK)
	if !partial.JPGReady || partial.NEFReady || partial.Verified || partial.PhotoID != "" {
		t.Fatalf("partially uploaded = %#v", partial)
	}
	changedPair := archiveTestRequest("桂林", jpg, []byte("different pair"), false)
	if occupied := preview(changedPair); occupied.Target == req.Target || occupied.JPGReady {
		t.Fatalf("partial target was reused by a different NEF manifest: %#v", occupied)
	}
	finish(req, http.StatusConflict)
	if got := preview(req); !got.JPGReady || got.NEFReady {
		t.Fatalf("retry plan = %#v", got)
	}
	archiveTestUpload(t, server, req, "nef", nef, http.StatusOK)
	verified := finish(req, http.StatusOK)
	if !verified.Verified || verified.PhotoID == "" || finish(req, http.StatusOK).PhotoID != verified.PhotoID {
		t.Fatalf("verified receipt = %#v", verified)
	}
	resp := doJSONRequest(t, server.Client(), http.MethodPut,
		server.URL+"/api/v1/photos/"+verified.PhotoID+"/shot_at", map[string]any{"shotAt": "1760000010"})
	readArchiveTestResponse(t, resp, http.StatusOK, nil)
	gotDigest, _, err := digestFile(filepath.Join(verified.Root, verified.Target))
	if err != nil || gotDigest != req.JPG {
		t.Fatalf("original bytes after time correction: %s %v", gotDigest, err)
	}
	info, err := os.Stat(filepath.Join(verified.Root, verified.Target))
	if err != nil || !info.ModTime().Equal(req.JPGTime) {
		t.Fatalf("original mtime: %v %v", info, err)
	}

	other := archiveTestRequest("桂林", archiveTestJPG(t, 12), []byte("other NEF"), false)
	otherPlan := preview(other)
	if otherPlan.Target == plan.Target || otherPlan.NEFTarget == plan.NEFTarget {
		t.Fatalf("name collision: %#v vs %#v", plan, otherPlan)
	}
	other.Target = otherPlan.Target
	archiveTestUpload(t, server, other, "jpg", archiveTestJPG(t, 12), http.StatusOK)
	archiveTestUpload(t, server, other, "nef", []byte("other NEF"), http.StatusOK)
	reviewed := finish(other, http.StatusOK)

	outsideJPG := archiveTestJPG(t, 72)
	outside := archiveTestRequest("其他活动", outsideJPG, []byte("outside NEF"), false)
	outside.Target = preview(outside).Target
	archiveTestUpload(t, server, outside, "jpg", outsideJPG, http.StatusOK)
	archiveTestUpload(t, server, outside, "nef", []byte("outside NEF"), http.StatusOK)
	finish(outside, http.StatusOK)
	var activities []string
	resp = doJSONRequest(t, server.Client(), http.MethodGet, server.URL+"/api/v1/photo-import/activities", nil)
	readArchiveTestResponse(t, resp, http.StatusOK, &activities)
	if len(activities) != 2 {
		t.Fatalf("imported activities: %v", activities)
	}
	cleanupPath := server.URL + "/api/v1/photo-recycle/activity-nef?activity=" + url.QueryEscape(req.Activity)
	var candidates struct {
		Files []nefCleanupCandidate `json:"files"`
	}
	resp = doJSONRequest(t, server.Client(), http.MethodGet, cleanupPath, nil)
	readArchiveTestResponse(t, resp, http.StatusOK, &candidates)
	if len(candidates.Files) != 1 || candidates.Files[0].ID != reviewed.PhotoID {
		t.Fatalf("activity NEF candidates = %#v", candidates)
	}
	favoritePath := server.URL + "/api/v1/photos/" + reviewed.PhotoID + "/favorite"
	resp = doJSONRequest(t, server.Client(), http.MethodPost, favoritePath, map[string]bool{"favorite": true})
	readArchiveTestResponse(t, resp, http.StatusOK, nil)
	var cleanup []map[string]string
	resp = doJSONRequest(t, server.Client(), http.MethodPost, cleanupPath, candidates.Files)
	readArchiveTestResponse(t, resp, http.StatusOK, &cleanup)
	if len(cleanup) != 1 || cleanup[0]["status"] != "skipped" {
		t.Fatalf("favorite changed after preview: %#v", cleanup)
	}
	resp = doJSONRequest(t, server.Client(), http.MethodPost, favoritePath, map[string]bool{"favorite": false})
	readArchiveTestResponse(t, resp, http.StatusOK, nil)
	resp = doJSONRequest(t, server.Client(), http.MethodPost, cleanupPath, candidates.Files)
	readArchiveTestResponse(t, resp, http.StatusOK, &cleanup)
	if len(cleanup) != 1 || cleanup[0]["status"] != "deleted" {
		t.Fatalf("NEF removal result: %#v", cleanup)
	}
	resp = doJSONRequest(t, server.Client(), http.MethodGet, server.URL+"/api/v1/photos/"+reviewed.PhotoID+"/image", nil)
	readArchiveTestResponse(t, resp, http.StatusOK, nil)
	nefItem, err := data.PhotoDAO.FindPhotoRecycle(ctx, reviewed.PhotoID, "nef")
	if err != nil || nefItem == nil {
		t.Fatalf("NEF recycle record: %#v %v", nefItem, err)
	}

	deletePath := server.URL + "/api/v1/photos/" + reviewed.PhotoID
	resp = doJSONRequest(t, server.Client(), http.MethodDelete, deletePath, nil)
	readArchiveTestResponse(t, resp, http.StatusOK, nil)
	resp = doJSONRequest(t, server.Client(), http.MethodGet, deletePath+"/image", nil)
	readArchiveTestResponse(t, resp, http.StatusGone, nil)
	photoItem, err := data.PhotoDAO.FindPhotoRecycle(ctx, reviewed.PhotoID, "photo")
	if err != nil || photoItem == nil {
		t.Fatalf("photo recycle record: %#v %v", photoItem, err)
	}
	if err = restorePhotoRecycle(ctx, nefItem.ID, time.Now()); err == nil || !strings.Contains(err.Error(), "先恢复") {
		t.Fatalf("restoring NEF before JPG = %v", err)
	}
	occupied := filepath.Join(conf.C.Storage.PhotoSrc, otherPlan.Target)
	err = os.WriteFile(occupied, []byte("different original"), 0600)
	if err != nil {
		t.Fatal(err)
	}
	restorePath := server.URL + "/api/v1/photo-recycle/restore"
	var restored []map[string]string
	resp = doJSONRequest(t, server.Client(), http.MethodPost, restorePath, []string{nefItem.ID, photoItem.ID})
	readArchiveTestResponse(t, resp, http.StatusOK, &restored)
	for _, result := range restored {
		if result["status"] != "restored" {
			t.Fatalf("restore result = %#v", restored)
		}
	}
	row, err := data.PhotoDAO.GetByID(ctx, reviewed.PhotoID)
	if err != nil || row.Timeline != other.Activity || !row.ShotAt.Equal(*other.ShotAt) ||
		!strings.Contains(row.Filename, "restored") {
		t.Fatalf("restored identity/time/name = %#v %v", row, err)
	}
	paired, err := photoPairNEF(ctx, row)
	if err != nil || paired.SHA256 != other.NEF {
		t.Fatalf("restored NEF pair %v %v", paired, err)
	}
}

func TestRecycleResumeAndExpiryFailure(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	s := &PhotoServer{}
	id, err := s.doUpload(ctx, strings.NewReader("source"), "resume.jpg", "", nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	item := &data.PhotoRecycleDO{ID: "resume", PhotoID: id, Kind: "photo", State: "moving"}
	row, err := data.PhotoDAO.GetByID(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	item.PhotoJSON, _ = json.Marshal(row)
	file, err := fileForRecycle(conf.C.Storage.PhotoSrc, row.FilePath, false)
	if err != nil {
		t.Fatal(err)
	}
	item.FilesJSON, _ = json.Marshal([]archivedFile{file})
	err = data.PhotoDAO.SaveRecycle(ctx, item)
	if err != nil {
		t.Fatal(err)
	}
	dest := recycleFilePath(item.ID, file)
	err = moveVerifiedArchiveFile(archivedSource(file, file.Original), dest, file.SHA256)
	if err != nil {
		t.Fatal(err)
	}
	err = sweepPhotoRecycle(ctx, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	item, err = data.PhotoDAO.FindRecycle(ctx, item.ID)
	if err != nil || item.State != "deleted" || item.DeletedAt.IsZero() {
		t.Fatalf("resume result %#v %v", item, err)
	}
	deadline := item.DeletedAt.Add(photoRecycleRetention)
	err = restorePhotoRecycle(ctx, item.ID, deadline)
	if err == nil {
		t.Fatal("expired item restored")
	}
	err = os.WriteFile(dest, []byte("modified"), 0600)
	if err != nil {
		t.Fatal(err)
	}
	if sweepPhotoRecycle(ctx, deadline) == nil {
		t.Fatal("purge failed digest was not reported")
	}
	err = os.WriteFile(dest, []byte("source"), 0600)
	if err != nil {
		t.Fatal(err)
	}
	err = sweepPhotoRecycle(ctx, deadline)
	if err != nil {
		t.Fatal(err)
	}
	item, err = data.PhotoDAO.FindRecycle(ctx, item.ID)
	if err != nil || item.State != "purged" || len(item.FilesJSON) != 0 {
		t.Fatalf("purge retry: %#v %v", item, err)
	}
}

package service

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"
	"backend/internal/testutil"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
)

func setupUserPathTest(t *testing.T) (*papp.AppCtx, string) {
	t.Helper()
	tempDir := t.TempDir()
	testutil.InitSchemaSQLite(t)
	testutil.AssertMigrationCompatible(t)
	gdb := pdb.GetGormDB()

	previous := conf.C
	conf.C.Storage.PhotoSrc = filepath.Join(tempDir, "source")
	conf.C.Storage.PhotoPath = filepath.Join(tempDir, "thumb")
	conf.C.Storage.TimelineWindowDays = 7
	t.Cleanup(func() {
		conf.C = previous
		if sqlDB, err := gdb.DB(); err == nil {
			_ = sqlDB.Close()
		}
	})
	return papp.NewAppCtx(context.Background()), tempDir
}

func newDraftHTTPServer() *httptest.Server {
	httpServer := khttp.NewServer()
	var draftServer DraftServer
	draftServer.Reg(nil, httpServer)
	return httptest.NewServer(httpServer)
}

func doJSONRequest(t *testing.T, client *http.Client, method, url string, body any) *http.Response {
	t.Helper()
	var reader io.Reader
	if body != nil {
		payload, err := json.Marshal(body)
		if err != nil {
			t.Fatalf("marshal request: %v", err)
		}
		reader = bytes.NewReader(payload)
	}
	req, err := http.NewRequest(method, url, reader)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("do request: %v", err)
	}
	return resp
}

func TestDraftHTTPCRUDAndExport(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	if err := os.MkdirAll(conf.C.Storage.PhotoSrc, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(conf.C.Storage.PhotoSrc, "p1.jpg"), []byte("photo-content"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := data.PhotoDAO.Add(ctx, &data.PhotoDO{ID: "p1", Filename: "p1.jpg", FilePath: "p1.jpg", FileType: "jpg"}); err != nil {
		t.Fatalf("add photo: %v", err)
	}

	server := newDraftHTTPServer()
	defer server.Close()
	client := server.Client()
	create := doJSONRequest(t, client, http.MethodPost, server.URL+"/api/v1/drafts", map[string]any{
		"title": "初稿", "content": "正文", "photo_ids": []string{"p1"}, "input_mode": "prompt", "prompt": "旅行记录",
	})
	defer create.Body.Close()
	if create.StatusCode != http.StatusCreated {
		t.Fatalf("create status = %d", create.StatusCode)
	}
	var created draftResponse
	if err := json.NewDecoder(create.Body).Decode(&created); err != nil {
		t.Fatalf("decode create response: %v", err)
	}
	if created.ID == "" || created.Prompt != "旅行记录" {
		t.Fatalf("created draft = %#v", created)
	}

	update := doJSONRequest(t, client, http.MethodPut, server.URL+"/api/v1/drafts/"+created.ID, map[string]any{
		"content": "更新正文", "input_mode": "draft", "draft_input": "原始随笔",
	})
	defer update.Body.Close()
	if update.StatusCode != http.StatusOK {
		t.Fatalf("update status = %d", update.StatusCode)
	}

	list := doJSONRequest(t, client, http.MethodGet, server.URL+"/api/v1/drafts", nil)
	defer list.Body.Close()
	var listResponse struct {
		Items []draftResponse `json:"items"`
		Total int             `json:"total"`
	}
	if err := json.NewDecoder(list.Body).Decode(&listResponse); err != nil {
		t.Fatalf("decode list response: %v", err)
	}
	if listResponse.Total != 1 || listResponse.Items[0].DraftInput != "原始随笔" {
		t.Fatalf("list response = %#v", listResponse)
	}

	export := doJSONRequest(t, client, http.MethodGet, server.URL+"/api/v1/drafts/"+created.ID+"/export", nil)
	defer export.Body.Close()
	if export.StatusCode != http.StatusOK {
		t.Fatalf("export status = %d", export.StatusCode)
	}
	zipBody, err := io.ReadAll(export.Body)
	if err != nil {
		t.Fatalf("read export: %v", err)
	}
	zipReader, err := zip.NewReader(bytes.NewReader(zipBody), int64(len(zipBody)))
	if err != nil {
		t.Fatalf("open export zip: %v", err)
	}
	zipNames := make([]string, 0, len(zipReader.File))
	for _, file := range zipReader.File {
		zipNames = append(zipNames, file.Name)
	}
	if strings.Join(zipNames, ",") != "photos/p1.jpg,post.md" {
		t.Fatalf("zip entries = %v", zipNames)
	}

	deleteResponse := doJSONRequest(t, client, http.MethodDelete, server.URL+"/api/v1/drafts/"+created.ID, nil)
	defer deleteResponse.Body.Close()
	if deleteResponse.StatusCode != http.StatusOK {
		t.Fatalf("delete status = %d", deleteResponse.StatusCode)
	}
}

func TestPhotoUploadDeleteAndVlmWriteback(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	server := PhotoServer{}
	conf.C.VLM.MaxImageSizeMB = 0
	jpgID, err := server.doUpload(ctx, strings.NewReader("jpg-photo"), "photo.jpg", "", nil, nil)
	if err != nil {
		t.Fatalf("upload JPG: %v", err)
	}
	for _, path := range []string{
		filepath.Join(conf.C.Storage.PhotoSrc, "photo.jpg"),
		filepath.Join(conf.C.Storage.PhotoPath, "photo.jpg"),
	} {
		if _, statErr := os.Stat(path); statErr != nil {
			t.Fatalf("JPG file missing after upload: %s: %v", path, statErr)
		}
	}
	if _, err := server.DeletePhoto(context.Background(), &api.DeletePhotoRequest{Id: jpgID}); err != nil {
		t.Fatalf("delete JPG: %v", err)
	}
	for _, path := range []string{
		filepath.Join(conf.C.Storage.PhotoSrc, "photo.jpg"),
		filepath.Join(conf.C.Storage.PhotoPath, "photo.jpg"),
	} {
		if _, statErr := os.Stat(path); !os.IsNotExist(statErr) {
			t.Fatalf("JPG file remains after delete: %s: %v", path, statErr)
		}
	}

	thumbDir := conf.C.Storage.PhotoPath
	brokenThumbPath := filepath.Join(filepath.Dir(thumbDir), "broken-thumb")
	if err := os.WriteFile(brokenThumbPath, []byte("not a directory"), 0644); err != nil {
		t.Fatal(err)
	}
	conf.C.Storage.PhotoPath = brokenThumbPath
	if _, err := server.doUpload(ctx, strings.NewReader("jpg-photo"), "failed.jpg", "", nil, nil); err == nil {
		t.Fatal("expected JPG upload failure when thumbnail directory is invalid")
	}
	if _, statErr := os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, "failed.jpg")); !os.IsNotExist(statErr) {
		t.Fatalf("failed JPG upload left source file: %v", statErr)
	}
	conf.C.Storage.PhotoPath = thumbDir

	photoID, err := server.doNefUpload(ctx, strings.NewReader("raw-photo"), "photo.nef", "", nil)
	if err != nil {
		t.Fatalf("upload NEF: %v", err)
	}
	if _, err := os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, "photo.nef")); err != nil {
		t.Fatalf("source file missing after upload: %v", err)
	}
	if _, err := data.PhotoDAO.GetByID(ctx, photoID); err != nil {
		t.Fatalf("photo record missing after upload: %v", err)
	}

	if _, err := server.DeletePhoto(context.Background(), &api.DeletePhotoRequest{Id: photoID}); err != nil {
		t.Fatalf("delete photo: %v", err)
	}
	if _, err := os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, "photo.nef")); !os.IsNotExist(err) {
		t.Fatalf("source file remains after delete: %v", err)
	}

	photo := &data.PhotoDO{ID: "vlm-photo", Filename: "vlm.jpg", FilePath: "vlm.jpg", FileType: "jpg"}
	if err := data.PhotoDAO.Add(ctx, photo); err != nil {
		t.Fatalf("add VLM photo: %v", err)
	}
	validDescription := "照片描述\n```json\n{\"subject\":{\"main_objects\":[\"山\"]}}\n```"
	if err := applyDescriptionToPhoto(ctx, photo.ID, &vlmDescriptionEntry{Description: validDescription, Model: "local", Time: time.Now().Format("2006-01-02 15:04:05")}); err != nil {
		t.Fatalf("apply valid VLM description: %v", err)
	}
	updated, err := data.PhotoDAO.GetByID(ctx, photo.ID)
	if err != nil || updated.Description != validDescription || updated.Objects != "山" {
		t.Fatalf("VLM writeback = %#v, err=%v", updated, err)
	}
	var healthyCount int64
	if err := pdb.GetGormDB().Table("ai_processing_history").Where("photo_id = ? AND status = ?", photo.ID, aiStatusHealthy).Count(&healthyCount).Error; err != nil {
		t.Fatalf("query VLM success history: %v", err)
	}
	if healthyCount != 1 {
		t.Fatalf("healthy history count = %d", healthyCount)
	}
	if err := applyDescriptionToPhoto(ctx, photo.ID, &vlmDescriptionEntry{Description: "invalid", Model: "local", Time: time.Now().Format("2006-01-02 15:04:05")}); err != nil {
		t.Fatalf("apply invalid VLM description: %v", err)
	}
	updated, err = data.PhotoDAO.GetByID(ctx, photo.ID)
	if err != nil || updated.DescriptionRaw != "invalid" || updated.Description != validDescription {
		t.Fatalf("VLM review writeback = %#v, err=%v", updated, err)
	}
	var reviewCount int64
	if err := pdb.GetGormDB().Table("ai_processing_history").Where("photo_id = ? AND status = ?", photo.ID, aiStatusReview).Count(&reviewCount).Error; err != nil {
		t.Fatalf("query VLM history: %v", err)
	}
	if reviewCount != 1 {
		t.Fatalf("review history count = %d", reviewCount)
	}
	recordAIHistory(photo.ID, "task-1", "vlm", aiStatusFailed, "local failure")
	var failedCount int64
	if err := pdb.GetGormDB().Table("ai_processing_history").Where("photo_id = ? AND status = ?", photo.ID, aiStatusFailed).Count(&failedCount).Error; err != nil {
		t.Fatalf("query VLM failure history: %v", err)
	}
	if failedCount != 1 {
		t.Fatalf("failed history count = %d", failedCount)
	}
}

func TestVlmQueueLifecycle(t *testing.T) {
	manager := &vlmQueueManager{}
	if !manager.start("task-1") {
		t.Fatal("queue did not start")
	}
	manager.setTotal(2)
	manager.setBatchPending([]string{"p1", "p2"})
	if !manager.hasBatchPending("p1") || manager.snapshot().Total != 2 {
		t.Fatalf("unexpected queue state: %#v", manager.snapshot())
	}
	if !manager.stop() {
		t.Fatal("queue did not accept stop")
	}
	select {
	case <-manager.stopCh:
	case <-time.After(time.Second):
		t.Fatal("queue stop signal was not closed")
	}
	manager.removeBatchPending("p1")
	if manager.hasBatchPending("p1") {
		t.Fatal("processed photo remained pending")
	}
}

func TestVlmQueueEndToEndSuccess(t *testing.T) {
	ctx, tempDir := setupUserPathTest(t)
	if err := os.MkdirAll(conf.C.Storage.PhotoSrc, 0755); err != nil {
		t.Fatal(err)
	}
	image, err := base64.StdEncoding.DecodeString("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9k=")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(conf.C.Storage.PhotoSrc, "queue.jpg"), image, 0644); err != nil {
		t.Fatal(err)
	}
	if err := data.PhotoDAO.Add(ctx, &data.PhotoDO{ID: "queue-photo", Filename: "queue.jpg", FilePath: "queue.jpg", FileType: "jpg"}); err != nil {
		t.Fatalf("add queue photo: %v", err)
	}
	promptPath := filepath.Join(tempDir, "prompt.txt")
	if err := os.WriteFile(promptPath, []byte("describe"), 0644); err != nil {
		t.Fatal(err)
	}
	vlm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("{\"model\":\"local-vlm\",\"output\":[{\"type\":\"message\",\"content\":[{\"type\":\"output_text\",\"text\":\"山景\\n```json\\n{\\\"subject\\\":{\\\"main_objects\\\":[\\\"山\\\"]}}\\n```\"}]}]}"))
	}))
	defer vlm.Close()
	conf.C.VLM.BaseURL = vlm.URL
	conf.C.VLM.Prompt = promptPath
	conf.C.VLM.MaxImageSizeMB = 0

	server := VlmServer{}
	started, err := server.StartVlmQueue(context.Background(), &api.StartVlmQueueRequest{})
	if err != nil || started.Total != 1 {
		t.Fatalf("start VLM queue = %#v, err=%v", started, err)
	}
	if !vlmQueue.waitExit(3 * time.Second) {
		t.Fatal("VLM worker did not exit")
	}
	status, err := server.GetVlmQueueStatus(context.Background(), &api.Empty{})
	if err != nil || status.Status.Running || status.Status.Completed != 1 || status.Status.Failed != 0 {
		t.Fatalf("final queue status = %#v, err=%v", status, err)
	}
	photo, err := data.PhotoDAO.GetByID(ctx, "queue-photo")
	if err != nil || !strings.Contains(photo.Description, "山景") {
		t.Fatalf("VLM writeback = %#v, err=%v", photo, err)
	}
}

func TestVlmQueueEndToEndFailure(t *testing.T) {
	ctx, tempDir := setupUserPathTest(t)
	if err := os.MkdirAll(conf.C.Storage.PhotoSrc, 0755); err != nil {
		t.Fatal(err)
	}
	image, err := base64.StdEncoding.DecodeString("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9k=")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(conf.C.Storage.PhotoSrc, "failed.jpg"), image, 0644); err != nil {
		t.Fatal(err)
	}
	if err := data.PhotoDAO.Add(ctx, &data.PhotoDO{ID: "failed-photo", Filename: "failed.jpg", FilePath: "failed.jpg", FileType: "jpg"}); err != nil {
		t.Fatal(err)
	}
	promptPath := filepath.Join(tempDir, "prompt.txt")
	if err := os.WriteFile(promptPath, []byte("describe"), 0644); err != nil {
		t.Fatal(err)
	}
	vlm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"error":{"code":"Internal","message":"controlled failure","type":"test"}}`))
	}))
	defer vlm.Close()
	conf.C.VLM.BaseURL, conf.C.VLM.Prompt, conf.C.VLM.MaxImageSizeMB = vlm.URL, promptPath, 0
	server := VlmServer{}
	if _, err := server.StartVlmQueue(context.Background(), &api.StartVlmQueueRequest{}); err != nil {
		t.Fatal(err)
	}
	if !vlmQueue.waitExit(3 * time.Second) {
		t.Fatal("VLM worker did not exit")
	}
	status, _ := server.GetVlmQueueStatus(context.Background(), &api.Empty{})
	if status.Status.Failed != 1 || status.Status.Completed != 0 {
		t.Fatalf("final queue status = %#v", status.Status)
	}
	var failures int64
	if err := pdb.GetGormDB().Table("ai_processing_history").Where("photo_id = ? AND status = ?", "failed-photo", aiStatusFailed).Count(&failures).Error; err != nil || failures != 1 {
		t.Fatalf("failure history = %d, err=%v", failures, err)
	}
}

func TestVlmQueueStopLeavesUnclaimedPhotosRetryable(t *testing.T) {
	ctx, tempDir := setupUserPathTest(t)
	if err := os.MkdirAll(conf.C.Storage.PhotoSrc, 0755); err != nil {
		t.Fatal(err)
	}
	image, err := base64.StdEncoding.DecodeString("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9k=")
	if err != nil {
		t.Fatal(err)
	}
	for i := 1; i <= 5; i++ {
		filename := fmt.Sprintf("stop-%d.jpg", i)
		if err := os.WriteFile(filepath.Join(conf.C.Storage.PhotoSrc, filename), image, 0644); err != nil {
			t.Fatal(err)
		}
		if err := data.PhotoDAO.Add(ctx, &data.PhotoDO{ID: fmt.Sprintf("stop-%d", i), Filename: filename, FilePath: filename, FileType: "jpg"}); err != nil {
			t.Fatal(err)
		}
	}
	promptPath := filepath.Join(tempDir, "prompt.txt")
	if err := os.WriteFile(promptPath, []byte("describe"), 0644); err != nil {
		t.Fatal(err)
	}
	started := make(chan struct{}, 4)
	release := make(chan struct{})
	vlm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		started <- struct{}{}
		<-release
		_, _ = w.Write([]byte("{\"model\":\"local-vlm\",\"output\":[{\"type\":\"message\",\"content\":[{\"type\":\"output_text\",\"text\":\"山景\\n```json\\n{\\\"subject\\\":{\\\"main_objects\\\":[\\\"山\\\"]}}\\n```\"}]}]}"))
	}))
	defer vlm.Close()
	conf.C.VLM.BaseURL, conf.C.VLM.Prompt, conf.C.VLM.MaxImageSizeMB = vlm.URL, promptPath, 0
	server := VlmServer{}
	if _, err := server.StartVlmQueue(context.Background(), &api.StartVlmQueueRequest{}); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 4; i++ {
		select {
		case <-started:
		case <-time.After(3 * time.Second):
			t.Fatal("workers did not start")
		}
	}
	if _, err := server.StopVlmQueue(context.Background(), &api.Empty{}); err != nil {
		t.Fatal(err)
	}
	close(release)
	if !vlmQueue.waitExit(3 * time.Second) {
		t.Fatal("VLM worker did not exit after stop")
	}
	untouched, err := data.PhotoDAO.GetByID(ctx, "stop-5")
	if err != nil || untouched.Description != "" {
		t.Fatalf("unclaimed photo = %#v, err=%v", untouched, err)
	}
	status, _ := server.GetVlmQueueStatus(context.Background(), &api.Empty{})
	if status.Status.Running || status.Status.Completed != 4 || status.Status.Failed != 0 {
		t.Fatalf("final queue status = %#v", status.Status)
	}
}

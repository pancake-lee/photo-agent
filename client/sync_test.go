package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

// TestFetchStorageInfo 验证 storage/info 请求与 JSON 解析。
func TestFetchStorageInfo(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/storage/info" {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"root":"/tmp/root","jpg_count":1247,"nef_count":89,"months":["202608"],"activities":["202608-山西旅游"],"last_sync":"2026-08-10T14:30:00Z"}`)
	}))
	defer server.Close()

	info, err := fetchStorageInfo(server.URL)
	if err != nil {
		t.Fatalf("fetchStorageInfo failed: %v", err)
	}
	if info.JpgCount != 1247 || info.NefCount != 89 {
		t.Fatalf("unexpected counts: jpg=%d nef=%d", info.JpgCount, info.NefCount)
	}
	if len(info.Months) != 1 || info.Months[0] != "202608" {
		t.Fatalf("unexpected months: %v", info.Months)
	}
	if len(info.Activities) != 1 || info.Activities[0] != "202608-山西旅游" {
		t.Fatalf("unexpected activities: %v", info.Activities)
	}
}

// TestSyncLikeDir 验证并行上传 like/ 目录、folder 字段与统计。
func TestSyncLikeDir(t *testing.T) {
	staging := t.TempDir()
	likeDir := filepath.Join(staging, "like", testFolder)
	if err := os.MkdirAll(likeDir, 0755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(likeDir, "IMG_0001.JPG"), []byte("jpeg-data"))
	writeFile(t, filepath.Join(likeDir, "IMG_0001.NEF"), []byte("nef-data"))
	writeFile(t, filepath.Join(likeDir, "IMG_0002.NEF"), []byte("nef-data-2"))

	// 收集上传请求，记录 folder 与 original_name
	var mu sync.Mutex
	type upload struct {
		name   string
		folder string
	}
	var uploads []upload

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/photos/upload" {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		if err := r.ParseMultipartForm(32 << 20); err != nil {
			t.Errorf("parse multipart failed: %v", err)
			return
		}
		mu.Lock()
		uploads = append(uploads, upload{
			name:   r.FormValue("original_name"),
			folder: r.FormValue("folder"),
		})
		mu.Unlock()
		// 读取 file 字段，确认文件内容随请求上传
		file, header, err := r.FormFile("file")
		if err != nil {
			t.Errorf("missing file field: %v", err)
			return
		}
		file.Close()
		if header.Filename == "" {
			t.Errorf("empty file filename")
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"stored","photo_id":"id-1"}`)
	}))
	defer server.Close()

	result, err := syncLikeDir(staging, testFolder, server.URL, "", nil)
	if err != nil {
		t.Fatalf("syncLikeDir failed: %v", err)
	}

	if result.Total != 3 {
		t.Fatalf("expected total 3, got %d", result.Total)
	}
	if result.Succeeded != 3 || result.Failed != 0 {
		t.Fatalf("unexpected result: succeeded=%d failed=%d", result.Succeeded, result.Failed)
	}

	mu.Lock()
	defer mu.Unlock()
	if len(uploads) != 3 {
		t.Fatalf("expected 3 uploads, got %d", len(uploads))
	}
	seen := map[string]bool{}
	for _, u := range uploads {
		if u.folder != testFolder {
			t.Errorf("unexpected folder: %q", u.folder)
		}
		if u.name == "" {
			t.Errorf("empty original_name")
		}
		seen[u.name] = true
	}
	for _, want := range []string{"IMG_0001.JPG", "IMG_0001.NEF", "IMG_0002.NEF"} {
		if !seen[want] {
			t.Errorf("missing upload for %s", want)
		}
	}
}

// TestSyncLikeDirEmpty 验证 like/ 为空时不报错。
func TestSyncLikeDirEmpty(t *testing.T) {
	staging := t.TempDir()
	if err := os.MkdirAll(filepath.Join(staging, "like", testFolder), 0755); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	defer server.Close()

	result, err := syncLikeDir(staging, testFolder, server.URL, "", nil)
	if err != nil {
		t.Fatalf("syncLikeDir failed: %v", err)
	}
	if result.Total != 0 || result.Succeeded != 0 {
		t.Fatalf("unexpected result: %+v", result)
	}
}

// TestUploadOneFileMultipart 验证 multipart 内容结构（file + original_name + folder + mod_time）。
func TestUploadOneFileMultipart(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "IMG_0001.NEF")
	writeFile(t, path, []byte("nef-bytes"))

	var got map[string]string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseMultipartForm(32 << 20)
		got = map[string]string{
			"original_name":    r.FormValue("original_name"),
			"folder":           r.FormValue("folder"),
			"mod_time":         r.FormValue("mod_time"),
			"original_shot_at": r.FormValue("original_shot_at"),
		}
		if f, h, err := r.FormFile("file"); err == nil {
			f.Close()
			got["file"] = h.Filename
		}
		// 确认 multipart boundary 正确
		if _, ok := r.MultipartForm.Value["original_name"]; !ok {
			t.Errorf("missing original_name field")
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"stored"}`)
	}))
	defer server.Close()

	status, errMsg := uploadOneFile(server.URL, "202608", path, "")
	if status != "stored" || errMsg != "" {
		t.Fatalf("unexpected: status=%q err=%q", status, errMsg)
	}
	if got["original_name"] != "IMG_0001.NEF" {
		t.Errorf("unexpected original_name: %q", got["original_name"])
	}
	if got["folder"] != "202608" {
		t.Errorf("unexpected folder: %q", got["folder"])
	}
	if got["file"] != "IMG_0001.NEF" {
		t.Errorf("unexpected file filename: %q", got["file"])
	}
	if got["mod_time"] == "" {
		t.Errorf("expected non-empty mod_time field")
	}
	if _, err := time.Parse(time.RFC3339, got["mod_time"]); err != nil {
		t.Errorf("mod_time not valid RFC3339: %q (%v)", got["mod_time"], err)
	}
	// 无 EXIF 的假 NEF 不应携带 original_shot_at
	if got["original_shot_at"] != "" {
		t.Errorf("expected empty original_shot_at, got %q", got["original_shot_at"])
	}
}

// TestUploadOneFileSendsShotAt 验证带 EXIF 的 JPG 会携带 original_shot_at 与 mod_time。
func TestUploadOneFileSendsShotAt(t *testing.T) {
	dir := t.TempDir()
	shotAt := time.Date(2026, 8, 8, 13, 13, 38, 0, time.UTC)
	path := filepath.Join(dir, "DSC_2916.JPG")
	writeFile(t, path, buildExifJpeg(shotAt))

	var got map[string]string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseMultipartForm(32 << 20)
		got = map[string]string{
			"mod_time":         r.FormValue("mod_time"),
			"original_shot_at": r.FormValue("original_shot_at"),
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"stored"}`)
	}))
	defer server.Close()

	status, errMsg := uploadOneFile(server.URL, "202608", path, "")
	if status != "stored" || errMsg != "" {
		t.Fatalf("unexpected: status=%q err=%q", status, errMsg)
	}
	if got["original_shot_at"] == "" {
		t.Fatal("expected original_shot_at field with EXIF shot time")
	}
	gotShot, err := time.Parse(time.RFC3339, got["original_shot_at"])
	if err != nil {
		t.Fatalf("original_shot_at not valid RFC3339: %q (%v)", got["original_shot_at"], err)
	}
	// EXIF 时间为无时区字符串，比较本地时区下的墙钟时间即可
	if gotShot.In(time.Local).Format("2006-01-02 15:04:05") != shotAt.Format("2006-01-02 15:04:05") {
		t.Errorf("original_shot_at mismatch: got %v, want %v", gotShot, shotAt)
	}
	if got["mod_time"] == "" {
		t.Errorf("expected non-empty mod_time field")
	}
}

// TestUploadOneFileSendsConflictResolution 验证 resolution 非空时携带 conflict_resolution 字段。
func TestUploadOneFileSendsConflictResolution(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "IMG_0001.NEF")
	writeFile(t, path, []byte("nef-bytes"))

	var gotResolution string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseMultipartForm(32 << 20)
		gotResolution = r.FormValue("conflict_resolution")
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"stored"}`)
	}))
	defer server.Close()

	status, errMsg := uploadOneFile(server.URL, "202608", path, "overwrite")
	if status != "stored" || errMsg != "" {
		t.Fatalf("unexpected: status=%q err=%q", status, errMsg)
	}
	if gotResolution != "overwrite" {
		t.Errorf("expected conflict_resolution=overwrite, got %q", gotResolution)
	}
}

// TestSyncLikeDirSkipExisting 验证 skip 模式：重名文件不传输，仅上传新文件并单独计数 Skipped。
func TestSyncLikeDirSkipExisting(t *testing.T) {
	staging := t.TempDir()
	likeDir := filepath.Join(staging, "like", testFolder)
	if err := os.MkdirAll(likeDir, 0755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(likeDir, "IMG_0001.JPG"), []byte("jpeg-data"))
	writeFile(t, filepath.Join(likeDir, "IMG_0001.NEF"), []byte("nef-data"))
	writeFile(t, filepath.Join(likeDir, "IMG_0002.NEF"), []byte("nef-data-2"))

	var mu sync.Mutex
	var uploaded []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/v1/storage/conflicts":
			fmt.Fprint(w, `{"total":3,"existing":["IMG_0001.JPG","IMG_0001.NEF"],"new":["IMG_0002.NEF"]}`)
		case "/api/v1/photos/upload":
			_ = r.ParseMultipartForm(32 << 20)
			mu.Lock()
			uploaded = append(uploaded, r.FormValue("original_name"))
			mu.Unlock()
			fmt.Fprint(w, `{"status":"stored"}`)
		}
	}))
	defer server.Close()

	result, err := syncLikeDir(staging, testFolder, server.URL, "skip", nil)
	if err != nil {
		t.Fatalf("syncLikeDir failed: %v", err)
	}
	if result.Total != 3 {
		t.Fatalf("expected total 3, got %d", result.Total)
	}
	if result.Succeeded != 1 || result.Skipped != 2 || result.Failed != 0 {
		t.Fatalf("unexpected result: succeeded=%d skipped=%d failed=%d", result.Succeeded, result.Skipped, result.Failed)
	}

	mu.Lock()
	defer mu.Unlock()
	if len(uploaded) != 1 || uploaded[0] != "IMG_0002.NEF" {
		t.Fatalf("expected only IMG_0002.NEF uploaded, got %v", uploaded)
	}
}

// TestSyncLikeDirProgress 验证上传过程中 onProgress 回调按文件逐次触发，completed 从 1 递增到 total。
func TestSyncLikeDirProgress(t *testing.T) {
	staging := t.TempDir()
	likeDir := filepath.Join(staging, "like", testFolder)
	if err := os.MkdirAll(likeDir, 0755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(likeDir, "IMG_0001.JPG"), []byte("jpeg-data"))
	writeFile(t, filepath.Join(likeDir, "IMG_0002.NEF"), []byte("nef-data"))
	writeFile(t, filepath.Join(likeDir, "IMG_0003.NEF"), []byte("nef-data-3"))

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `{"status":"stored"}`)
	}))
	defer server.Close()

	var mu sync.Mutex
	var progresses []SyncProgress
	result, err := syncLikeDir(staging, testFolder, server.URL, "", func(p SyncProgress) {
		mu.Lock()
		progresses = append(progresses, p)
		mu.Unlock()
	})
	if err != nil {
		t.Fatalf("syncLikeDir failed: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()
	if len(progresses) != 3 {
		t.Fatalf("expected 3 progress callbacks, got %d", len(progresses))
	}
	seen := map[int]bool{}
	for _, p := range progresses {
		if p.Total != 3 {
			t.Errorf("unexpected total: %d", p.Total)
		}
		if p.Completed < 1 || p.Completed > 3 {
			t.Errorf("unexpected completed: %d", p.Completed)
		}
		seen[p.Completed] = true
	}
	for i := 1; i <= 3; i++ {
		if !seen[i] {
			t.Errorf("missing progress completed=%d", i)
		}
	}
	if result.Succeeded != 3 {
		t.Errorf("expected succeeded 3, got %d", result.Succeeded)
	}
}

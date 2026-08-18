package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// ================================================================
// 上传同步：客户端读取本地 like/ 目录，并行 POST 到服务端。
// 服务端接口：GET /api/v1/storage/info、POST /api/v1/photos/upload。
// 纯函数、不依赖 Wails，便于单元测试。绑定方法见 app.go。
// ================================================================

// syncConcurrency 上传并发数。
const syncConcurrency = 3

// uploadTimeout 单个文件上传超时（NEF 体积较大，给足时间）。
const uploadTimeout = 10 * time.Minute

// storageInfoTimeout 服务端状态查询（连接并验证）超时。
const storageInfoTimeout = 2 * time.Second

// StorageInfo 服务端存储目录状态（对应 GET /api/v1/storage/info）。
type StorageInfo struct {
	Root       string   `json:"root"`
	JpgCount   int64    `json:"jpg_count"`
	NefCount   int64    `json:"nef_count"`
	Months     []string `json:"months"`
	Activities []string `json:"activities"`
	LastSync   string   `json:"last_sync"`
	Warning    string   `json:"warning,omitempty"`
}

// SyncFileResult 单个文件的上传结果。
type SyncFileResult struct {
	Name   string `json:"name"`
	Status string `json:"status"` // stored / conflict / skipped / failed
	Error  string `json:"error,omitempty"`
}

// SyncResult 一次同步的整体结果。
type SyncResult struct {
	Total     int              `json:"total"`
	Succeeded int              `json:"succeeded"`
	Skipped   int              `json:"skipped"`
	Failed    int              `json:"failed"`
	ElapsedMs int64            `json:"elapsed_ms"`
	Files     []SyncFileResult `json:"files"`
}

// SyncProgress 单个文件完成上传/跳过后向前端推送的进度信息。
type SyncProgress struct {
	Completed int    `json:"completed"`
	Total     int    `json:"total"`
	Name      string `json:"name"`
	Status    string `json:"status"`
}

// joinURL 拼接服务地址与接口路径，忽略服务地址末尾斜杠。
func joinURL(base, path string) string {
	return strings.TrimRight(base, "/") + path
}

// fetchStorageInfo 查询服务端存储目录状态。
func fetchStorageInfo(serverURL string) (*StorageInfo, error) {
	if strings.TrimSpace(serverURL) == "" {
		return nil, fmt.Errorf("服务器地址为空")
	}
	log.Printf("storage/info: querying %s", serverURL)
	client := &http.Client{Timeout: storageInfoTimeout}
	resp, err := client.Get(joinURL(serverURL, "/api/v1/storage/info"))
	if err != nil {
		return nil, fmt.Errorf("请求 storage/info 失败: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("读取 storage/info 响应失败: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("storage/info 返回 HTTP %d: %s", resp.StatusCode, string(body))
	}

	info := &StorageInfo{}
	if err := json.Unmarshal(body, info); err != nil {
		return nil, fmt.Errorf("解析 storage/info 响应失败: %w", err)
	}
	return info, nil
}

// ConflictCheck 重名文件检查结果（对应 POST /api/v1/storage/conflicts）。
type ConflictCheck struct {
	Total    int      `json:"total"`
	Existing []string `json:"existing"`
	New      []string `json:"new"`
}

// checkConflicts 扫描 like/<folderName> 目录，向服务端查询哪些文件名已存在。
func checkConflicts(stagingPath, folderName, serverURL string) (*ConflictCheck, error) {
	likeDir := filepath.Join(stagingPath, "like", folderName)
	files, err := scanDir(likeDir, func(name string) bool {
		return isJpg(name) || isNef(name)
	})
	if err != nil {
		return nil, fmt.Errorf("扫描 like 目录失败: %w", err)
	}
	names := make([]string, 0, len(files))
	for _, f := range files {
		names = append(names, f.Name)
	}

	body, _ := json.Marshal(map[string]any{"names": names})
	client := &http.Client{Timeout: storageInfoTimeout}
	resp, err := client.Post(joinURL(serverURL, "/api/v1/storage/conflicts"), "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("请求 storage/conflicts 失败: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("storage/conflicts 返回 HTTP %d: %s", resp.StatusCode, string(b))
	}
	var check ConflictCheck
	if err := json.NewDecoder(resp.Body).Decode(&check); err != nil {
		return nil, fmt.Errorf("解析 storage/conflicts 响应失败: %w", err)
	}
	return &check, nil
}

// syncLikeDir 将 like/<folderName> 目录下的 JPG 与 NEF 并行上传到服务端 folderName 归档目录。
// resolution 控制重名处理：
//   - "skip"：跳过服务端已存在的文件（不传输），仅上传新文件；
//   - "overwrite"：覆盖服务端现有文件；
//   - ""：不指定，沿用服务端冲突检测（已存在文件返回 conflict）。
//
// onProgress 非空时，每完成一个文件（上传成功/失败/跳过）回调一次，用于向前端推送进度。
func syncLikeDir(stagingPath, folderName, serverURL, resolution string, onProgress func(SyncProgress)) (*SyncResult, error) {
	likeDir := filepath.Join(stagingPath, "like", folderName)
	log.Printf("sync: scanning like dir %s (resolution=%s)", likeDir, resolution)
	files, err := scanDir(likeDir, func(name string) bool {
		return isJpg(name) || isNef(name)
	})
	if err != nil {
		return nil, fmt.Errorf("扫描 like 目录失败: %w", err)
	}
	log.Printf("sync: %d files to upload", len(files))

	// 跳过模式：先查服务端重名文件，本地过滤，避免重复传输。
	skipSet := map[string]bool{}
	if resolution == "skip" {
		check, err := checkConflicts(stagingPath, folderName, serverURL)
		if err != nil {
			return nil, fmt.Errorf("查询重名文件失败: %w", err)
		}
		for _, name := range check.Existing {
			skipSet[name] = true
		}
		log.Printf("sync: skip %d existing files", len(skipSet))
	}

	result := &SyncResult{
		Total: len(files),
		Files: make([]SyncFileResult, len(files)),
	}
	start := time.Now()

	// 完成计数（含跳过与失败），每完成一个文件回调一次进度。
	var completed int64
	report := func(name, status string) {
		c := atomic.AddInt64(&completed, 1)
		if onProgress != nil {
			onProgress(SyncProgress{Completed: int(c), Total: len(files), Name: name, Status: status})
		}
	}

	sem := make(chan struct{}, syncConcurrency)
	var wg sync.WaitGroup
	for i, f := range files {
		if skipSet[f.Name] {
			result.Files[i] = SyncFileResult{Name: f.Name, Status: "skipped"}
			result.Skipped++
			report(f.Name, "skipped")
			continue
		}
		wg.Add(1)
		sem <- struct{}{}
		go func(idx int, name string) {
			defer wg.Done()
			defer func() { <-sem }()
			status, errMsg := uploadOneFile(serverURL, folderName, filepath.Join(likeDir, name), resolution)
			result.Files[idx] = SyncFileResult{Name: name, Status: status}
			if errMsg != "" {
				result.Files[idx].Error = errMsg
			}
			report(name, status)
		}(i, f.Name)
	}
	wg.Wait()

	for _, fr := range result.Files {
		if fr.Status == "stored" {
			result.Succeeded++
		} else if fr.Status != "skipped" {
			result.Failed++
		}
	}
	result.ElapsedMs = time.Since(start).Milliseconds()
	return result, nil
}

// uploadOneFile 上传单个文件到服务端。返回状态与错误信息（错误信息为空表示成功）。
// 同时读取文件修改时间与 EXIF 拍摄时间，随请求发送，供服务端回写文件时间戳。
// resolution 非空时作为 conflict_resolution 随请求发送（skip / overwrite）。
func uploadOneFile(serverURL, folder, filePath, resolution string) (status string, errMsg string) {
	name := filepath.Base(filePath)
	log.Printf("sync: uploading %s", name)

	file, err := os.Open(filePath)
	if err != nil {
		log.Printf("sync: %s open failed: %v", name, err)
		return "failed", err.Error()
	}
	defer file.Close()

	modTime := ""
	if info, err := file.Stat(); err == nil {
		modTime = info.ModTime().UTC().Format(time.RFC3339)
	}
	// 仅 JPG 读取 EXIF 拍摄时间：NEF 的拍摄时间由服务端 doNefUpload/createPhotoRecord
	// 入库时读取（实测 113 个 NEF 均正常、无卡死），客户端无需重复读取。
	shotAt := ""
	if isJpg(name) {
		if t, ok := exifShotAt(filePath); ok {
			shotAt = t.UTC().Format(time.RFC3339)
		}
	}

	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)

	fw, err := w.CreateFormFile("file", name)
	if err != nil {
		return "failed", err.Error()
	}
	if _, err := io.Copy(fw, file); err != nil {
		return "failed", err.Error()
	}
	if err := w.WriteField("original_name", name); err != nil {
		return "failed", err.Error()
	}
	if folder != "" {
		if err := w.WriteField("folder", folder); err != nil {
			return "failed", err.Error()
		}
	}
	if resolution != "" {
		if err := w.WriteField("conflict_resolution", resolution); err != nil {
			return "failed", err.Error()
		}
	}
	if shotAt != "" {
		if err := w.WriteField("original_shot_at", shotAt); err != nil {
			return "failed", err.Error()
		}
	}
	if modTime != "" {
		if err := w.WriteField("mod_time", modTime); err != nil {
			return "failed", err.Error()
		}
	}
	if err := w.Close(); err != nil {
		return "failed", err.Error()
	}

	req, err := http.NewRequest(http.MethodPost, joinURL(serverURL, "/api/v1/photos/upload"), &buf)
	if err != nil {
		return "failed", err.Error()
	}
	req.Header.Set("Content-Type", w.FormDataContentType())

	client := &http.Client{Timeout: uploadTimeout}
	log.Printf("sync: sending %s", name)
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("sync: %s request failed: %v", name, err)
		return "failed", err.Error()
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return "failed", fmt.Sprintf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	var parsed struct {
		Status string `json:"status"`
	}
	if err := json.Unmarshal(body, &parsed); err != nil {
		// 非 JSON 响应按成功处理
		return "stored", ""
	}
	if parsed.Status == "" {
		parsed.Status = "stored"
	}
	log.Printf("sync: uploaded %s -> %s", name, parsed.Status)
	return parsed.Status, ""
}

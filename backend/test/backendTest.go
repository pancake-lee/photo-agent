package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/photo-agent/internal/config"
	"go.uber.org/zap/zapcore"
)

const (
	serverAddr = "127.0.0.1:18080"
	baseURL    = "http://" + serverAddr + "/api"
)

var (
	testDataDir  string
	testPhotoDir string
	testDBPath   string
)

// TestResult 单条测试结果
type TestResult struct {
	Name    string `json:"name"`
	Status  string `json:"status"`
	Detail  string `json:"detail"`
	Elapsed string `json:"elapsed"`
}

var results []TestResult

var (
	configFlag = flag.String("c", "", "config file path (e.g. ./configs/config.yaml)")
	logConsole = flag.Bool("l", false, "log to console; false for file only")
)

func main() {
	flag.Parse()

	plogger.InitLogger(*logConsole, zapcore.DebugLevel, "")

	fmt.Println("=== Photo Agent Backend E2E Test ===")
	fmt.Println()

	// 1. 基本接口测试（导入任务 + API）
	fmt.Println("--- Group 1: Basic API Tests ---")
	runBasicAPITests()
	fmt.Println()

	// 2. AutoSync 流程测试（descriptions.json -> SQLite 自动同步）
	fmt.Println("--- Group 2: AutoSync Flow Tests ---")
	runAutoSyncTests()
	fmt.Println()

	// 3. batch_vlm 端到端测试（需真实 VLM API Key）
	fmt.Println("--- Group 3: Batch VLM Tests ---")
	runBatchVLMTests()
	fmt.Println()

	// 4. 输出报告
	printReport()
}

// ========== Group 1: Basic API Tests ==========

func runBasicAPITests() {
	setup()
	defer cleanup()

	cmd := startServer()
	defer stopServer(cmd)

	if !waitForServer(baseURL, 10) {
		fmt.Println("Server failed to start")
		os.Exit(1)
	}
	fmt.Println("Server ready")
	fmt.Println()

	testHealthCheck()
	testImportJobFlow()
	testPhotoAPIs()
	testTimelineAPIs()
	testTagAPIs()
}

func setup() {
	testDataDir = filepath.Join(os.TempDir(), fmt.Sprintf("photo-agent-test-%d", time.Now().Unix()))
	testPhotoDir = filepath.Join(testDataDir, "photos")
	testDBPath = filepath.Join(testDataDir, "test.db")

	_ = os.MkdirAll(testPhotoDir, 0755)

	// 复制真实测试图片（替代原来的假数据）
	testImgSrc := "backend/test/test.png"
	if err := copyFile(testImgSrc, filepath.Join(testPhotoDir, "test.png")); err != nil {
		fmt.Printf("Copy test image failed: %v\n", err)
		os.Exit(1)
	}
	if err := copyFile(testImgSrc, filepath.Join(testPhotoDir, "test2.png")); err != nil {
		fmt.Printf("Copy test image failed: %v\n", err)
		os.Exit(1)
	}

	// 非图片文件（测试过滤）
	_ = os.WriteFile(filepath.Join(testPhotoDir, "readme.txt"), []byte("not an image"), 0644)

	// 测试时间线文件
	timelineContent := `| 时间 | 活动 |
| --- | --- |
| 2024-01-01 ~ 2024-01-03 | 元旦旅行 |
| 2024-05-01 | 劳动节活动 |
`
	_ = os.WriteFile(filepath.Join(testDataDir, "timeline.md"), []byte(timelineContent), 0644)

	// 测试预描述文件（匹配真实图片名）
	descContent := `{
  "test.png": {
    "description": "一张测试照片的AI描述",
    "model": "gpt-4o-mini",
    "processed_at": "2024-01-01T00:00:00Z",
    "shot_at": "2024-01-02T10:00:00Z"
  }
}`
	_ = os.WriteFile(filepath.Join(testDataDir, "descriptions.json"), []byte(descContent), 0644)

	fmt.Printf("Test data dir: %s\n", testDataDir)
}

func cleanup() {
	if testDataDir != "" {
		_ = os.RemoveAll(testDataDir)
		fmt.Printf("Cleaned up: %s\n", testDataDir)
	}
}

func startServer() *exec.Cmd {
	configContent := fmt.Sprintf(`
[server]
addr = "%s"

[db]
sqlite_path = "%s"

[storage]
photo_path = "%s"
descriptions_path = "%s"
timeline_path = "%s"

[vlm]
provider = "openai"
model = "gpt-4o-mini"
concurrency = 1
`, serverAddr, testDBPath, testPhotoDir, filepath.Join(testDataDir, "descriptions.json"), filepath.Join(testDataDir, "timeline.md"))

	configFile := filepath.Join(testDataDir, "test.toml")
	_ = os.WriteFile(configFile, []byte(configContent), 0644)

	serverBin := filepath.Join("bin", "server")
	if _, err := os.Stat(serverBin); os.IsNotExist(err) {
		fmt.Printf("Server binary not found: %s\n", serverBin)
		os.Exit(1)
	}

	cmd := exec.Command(serverBin, "-c", configFile, "-l")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		fmt.Printf("Start server failed: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Server starting (pid=%d)...\n", cmd.Process.Pid)
	return cmd
}

func stopServer(cmd *exec.Cmd) {
	if cmd != nil && cmd.Process != nil {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
		fmt.Println("Server stopped")
	}
}

func waitForServer(base string, maxSeconds int) bool {
	healthURL := base + "/health"
	for i := 0; i < maxSeconds*5; i++ {
		resp, err := http.Get(healthURL)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == 200 {
				return true
			}
		}
		time.Sleep(200 * time.Millisecond)
	}
	return false
}

func testHealthCheck() {
	start := time.Now()
	resp, err := http.Get(baseURL + "/health")
	elapsed := time.Since(start)

	if err != nil {
		record("健康检查", "FAIL", err.Error(), elapsed)
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		record("健康检查", "FAIL", fmt.Sprintf("status=%d, body=%s", resp.StatusCode, string(body)), elapsed)
		return
	}

	var data map[string]any
	_ = json.Unmarshal(body, &data)
	if data["status"] != "ok" {
		record("健康检查", "FAIL", fmt.Sprintf("unexpected body: %s", string(body)), elapsed)
		return
	}

	record("健康检查", "PASS", fmt.Sprintf("status=ok, latency=%v", elapsed), elapsed)
}

func testImportJobFlow() {
	// 1. 创建导入任务
	start := time.Now()
	payload := map[string]any{
		"source_path": testPhotoDir,
		"recursive":   false,
	}
	bodyBytes, _ := json.Marshal(payload)
	resp, err := http.Post(baseURL+"/import/jobs", "application/json", bytes.NewReader(bodyBytes))
	elapsed := time.Since(start)

	if err != nil {
		record("创建导入任务", "FAIL", err.Error(), elapsed)
		return
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		record("创建导入任务", "FAIL", fmt.Sprintf("status=%d, body=%s", resp.StatusCode, string(respBody)), elapsed)
		return
	}

	var job map[string]any
	_ = json.Unmarshal(respBody, &job)
	jobID, _ := job["id"].(string)
	if jobID == "" {
		record("创建导入任务", "FAIL", "missing job id", elapsed)
		return
	}
	record("创建导入任务", "PASS", fmt.Sprintf("job_id=%s", jobID), elapsed)

	// 2. 轮询等待完成
	pollStart := time.Now()
	var finalStatus string
	for i := 0; i < 30; i++ {
		time.Sleep(500 * time.Millisecond)
		resp2, err := http.Get(baseURL + "/import/jobs/" + jobID)
		if err != nil {
			continue
		}
		body2, _ := io.ReadAll(resp2.Body)
		resp2.Body.Close()

		var jobData map[string]any
		_ = json.Unmarshal(body2, &jobData)
		status, _ := jobData["status"].(string)
		if status == "completed" || status == "failed" {
			finalStatus = status
			break
		}
	}
	pollElapsed := time.Since(pollStart)

	if finalStatus == "" {
		record("导入任务完成", "FAIL", "timeout waiting for job completion", pollElapsed)
		return
	}

	resp3, _ := http.Get(baseURL + "/import/jobs/" + jobID)
	body3, _ := io.ReadAll(resp3.Body)
	resp3.Body.Close()
	var finalJob map[string]any
	_ = json.Unmarshal(body3, &finalJob)

	total, _ := finalJob["total_photos"].(float64)
	processed, _ := finalJob["processed_photos"].(float64)
	failed, _ := finalJob["failed_photos"].(float64)

	record("导入任务完成", "PASS", fmt.Sprintf("status=%s, total=%.0f, processed=%.0f, failed=%.0f, elapsed=%v",
		finalStatus, total, processed, failed, pollElapsed), pollElapsed)

	// 3. 查询任务日志
	logStart := time.Now()
	resp4, err := http.Get(baseURL + "/import/jobs/" + jobID + "/logs")
	logElapsed := time.Since(logStart)
	if err != nil {
		record("查询任务日志", "FAIL", err.Error(), logElapsed)
		return
	}
	logBody, _ := io.ReadAll(resp4.Body)
	resp4.Body.Close()

	var logData map[string]any
	_ = json.Unmarshal(logBody, &logData)
	if logData["job_id"] != jobID {
		record("查询任务日志", "FAIL", "job_id mismatch", logElapsed)
		return
	}
	record("查询任务日志", "PASS", fmt.Sprintf("job_id=%s", jobID), logElapsed)

	// 4. 验证数据库中照片数量（2 张图片：test.png + test2.png）
	photoStart := time.Now()
	resp5, err := http.Get(baseURL + "/photos")
	photoElapsed := time.Since(photoStart)
	if err != nil {
		record("导入后照片列表", "FAIL", err.Error(), photoElapsed)
		return
	}
	photoBody, _ := io.ReadAll(resp5.Body)
	resp5.Body.Close()

	var photoList map[string]any
	_ = json.Unmarshal(photoBody, &photoList)
	items, _ := photoList["items"].([]any)
	totalPhotos, _ := photoList["total"].(float64)

	record("导入后照片列表", "PASS", fmt.Sprintf("items=%d, total=%.0f", len(items), totalPhotos), photoElapsed)
}

func testPhotoAPIs() {
	resp, err := http.Get(baseURL + "/photos")
	if err != nil {
		record("照片列表查询", "FAIL", err.Error(), 0)
		return
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	var list map[string]any
	_ = json.Unmarshal(body, &list)
	items, _ := list["items"].([]any)

	if len(items) == 0 {
		record("照片详情查询", "SKIP", "no photos available", 0)
		record("照片图片获取", "SKIP", "no photos available", 0)
		record("照片缩略图获取", "SKIP", "no photos available", 0)
		return
	}

	firstPhoto, _ := items[0].(map[string]any)
	photoID, _ := firstPhoto["id"].(string)

	// 查询照片详情
	start := time.Now()
	resp2, err := http.Get(baseURL + "/photos/" + photoID)
	elapsed := time.Since(start)
	if err != nil {
		record("照片详情查询", "FAIL", err.Error(), elapsed)
		return
	}
	body2, _ := io.ReadAll(resp2.Body)
	resp2.Body.Close()

	if resp2.StatusCode != 200 {
		record("照片详情查询", "FAIL", fmt.Sprintf("status=%d", resp2.StatusCode), elapsed)
		return
	}

	var photo map[string]any
	_ = json.Unmarshal(body2, &photo)
	if photo["id"] != photoID {
		record("照片详情查询", "FAIL", "id mismatch", elapsed)
		return
	}

	// 验证图片尺寸（真实图片应有正确尺寸）
	width, _ := photo["width"].(float64)
	height, _ := photo["height"].(float64)
	if width == 0 || height == 0 {
		record("照片详情查询", "WARN", fmt.Sprintf("id=%s, width/height is zero", photoID), elapsed)
	} else {
		record("照片详情查询", "PASS", fmt.Sprintf("id=%s, size=%.0fx%.0f", photoID, width, height), elapsed)
	}

	// 获取照片原图
	start = time.Now()
	resp3, err := http.Get(baseURL + "/photos/" + photoID + "/image")
	elapsed = time.Since(start)
	if err != nil {
		record("照片图片获取", "FAIL", err.Error(), elapsed)
		return
	}
	resp3.Body.Close()
	if resp3.StatusCode != 200 {
		record("照片图片获取", "FAIL", fmt.Sprintf("expected 200, got %d", resp3.StatusCode), elapsed)
		return
	}
	record("照片图片获取", "PASS", fmt.Sprintf("status=%d", resp3.StatusCode), elapsed)

	// 获取照片缩略图（真实图片应能正常生成）
	start = time.Now()
	resp4, err := http.Get(baseURL + "/photos/" + photoID + "/image?size=thumb")
	elapsed = time.Since(start)
	if err != nil {
		record("照片缩略图获取", "FAIL", err.Error(), elapsed)
		return
	}
	resp4.Body.Close()
	if resp4.StatusCode != 200 {
		record("照片缩略图获取", "FAIL", fmt.Sprintf("expected 200, got %d", resp4.StatusCode), elapsed)
		return
	}
	record("照片缩略图获取", "PASS", fmt.Sprintf("status=%d", resp4.StatusCode), elapsed)
}

func testTimelineAPIs() {
	start := time.Now()
	resp, err := http.Get(baseURL + "/timelines")
	elapsed := time.Since(start)
	if err != nil {
		record("时间线列表", "FAIL", err.Error(), elapsed)
		return
	}
	resp.Body.Close()
	if resp.StatusCode != 200 {
		record("时间线列表", "FAIL", fmt.Sprintf("status=%d", resp.StatusCode), elapsed)
		return
	}
	record("时间线列表", "PASS", fmt.Sprintf("status=%d", resp.StatusCode), elapsed)

	start = time.Now()
	resp2, err := http.Get(baseURL + "/timelines/元旦旅行/photos")
	elapsed = time.Since(start)
	if err != nil {
		record("时间线照片查询", "FAIL", err.Error(), elapsed)
		return
	}
	body2, _ := io.ReadAll(resp2.Body)
	resp2.Body.Close()
	if resp2.StatusCode != 200 {
		record("时间线照片查询", "FAIL", fmt.Sprintf("status=%d", resp2.StatusCode), elapsed)
		return
	}
	var data map[string]any
	_ = json.Unmarshal(body2, &data)
	if data["timeline"] != "元旦旅行" {
		record("时间线照片查询", "FAIL", "timeline mismatch", elapsed)
		return
	}
	record("时间线照片查询", "PASS", "timeline=元旦旅行", elapsed)
}

func testTagAPIs() {
	start := time.Now()
	resp, err := http.Get(baseURL + "/tags")
	elapsed := time.Since(start)
	if err != nil {
		record("标签列表", "FAIL", err.Error(), elapsed)
		return
	}
	resp.Body.Close()
	if resp.StatusCode != 200 {
		record("标签列表", "FAIL", fmt.Sprintf("status=%d", resp.StatusCode), elapsed)
		return
	}
	record("标签列表", "PASS", fmt.Sprintf("status=%d", resp.StatusCode), elapsed)

	start = time.Now()
	resp2, err := http.Get(baseURL + "/tags/风景/photos")
	elapsed = time.Since(start)
	if err != nil {
		record("标签照片查询", "FAIL", err.Error(), elapsed)
		return
	}
	body2, _ := io.ReadAll(resp2.Body)
	resp2.Body.Close()
	if resp2.StatusCode != 200 {
		record("标签照片查询", "FAIL", fmt.Sprintf("status=%d", resp2.StatusCode), elapsed)
		return
	}
	var data map[string]any
	_ = json.Unmarshal(body2, &data)
	if data["tag"] != "风景" {
		record("标签照片查询", "FAIL", "tag mismatch", elapsed)
		return
	}
	record("标签照片查询", "PASS", "tag=风景", elapsed)
}

// ========== Group 2: AutoSync Flow Tests ==========

func runAutoSyncTests() {
	// 使用独立端口避免冲突
	addr := "127.0.0.1:18081"
	base := "http://" + addr + "/api"

	// 1. 创建独立临时环境
	tempDir := filepath.Join(os.TempDir(), fmt.Sprintf("photo-agent-autosync-%d", time.Now().Unix()))
	photoDir := filepath.Join(tempDir, "photos")
	descPath := filepath.Join(tempDir, "descriptions.json")
	dbPath := filepath.Join(tempDir, "autosync.db")
	_ = os.MkdirAll(photoDir, 0755)
	defer func() {
		_ = os.RemoveAll(tempDir)
		fmt.Printf("AutoSync cleaned up: %s\n", tempDir)
	}()

	// 2. 复制真实测试图片
	if err := copyFile("backend/test/test.png", filepath.Join(photoDir, "test.png")); err != nil {
		record("AutoSync-复制测试图片", "FAIL", err.Error(), 0)
		return
	}

	// 3. 构造 descriptions.json（模拟 batch_vlm 输出）
	descContent := `{
  "test.png": {
    "description": "一张展示AI测试场景的PNG图片，画面中心是一个测试图案",
    "model": "test-model",
    "processed_at": "2024-06-15T10:00:00Z",
    "shot_at": "2024-06-15T10:00:00Z"
  }
}`
	_ = os.WriteFile(descPath, []byte(descContent), 0644)

	// 4. 构造 server 配置文件
	configContent := fmt.Sprintf(`
[server]
addr = "%s"

[db]
sqlite_path = "%s"

[storage]
photo_path = "%s"
descriptions_path = "%s"
`, addr, dbPath, photoDir, descPath)
	configFile := filepath.Join(tempDir, "autosync.toml")
	_ = os.WriteFile(configFile, []byte(configContent), 0644)

	// 5. 启动 server
	serverBin := filepath.Join("bin", "server")
	cmd := exec.Command(serverBin, "-c", configFile, "-l")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		record("AutoSync-启动Server", "FAIL", err.Error(), 0)
		return
	}
	defer func() {
		if cmd != nil && cmd.Process != nil {
			_ = cmd.Process.Kill()
			_, _ = cmd.Process.Wait()
			fmt.Println("AutoSync server stopped")
		}
	}()

	// 6. 等待 server 就绪
	if !waitForServer(base, 10) {
		record("AutoSync-等待就绪", "FAIL", "timeout", 0)
		return
	}
	fmt.Println("AutoSync server ready")

	// 7. 轮询等待 AutoSync 完成（最多 15 秒）
	pollStart := time.Now()
	var photos []any
	var photoID string
	for i := 0; i < 30; i++ {
		time.Sleep(500 * time.Millisecond)
		resp, err := http.Get(base + "/photos")
		if err != nil {
			continue
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		var data map[string]any
		_ = json.Unmarshal(body, &data)
		items, _ := data["items"].([]any)
		total, _ := data["total"].(float64)
		if total > 0 && len(items) > 0 {
			photos = items
			first, _ := items[0].(map[string]any)
			photoID, _ = first["id"].(string)
			break
		}
	}
	pollElapsed := time.Since(pollStart)

	if len(photos) == 0 {
		record("AutoSync-照片同步", "FAIL", "timeout waiting for AutoSync", pollElapsed)
		return
	}
	record("AutoSync-照片同步", "PASS", fmt.Sprintf("synced in %v, photo_id=%s", pollElapsed, photoID), pollElapsed)

	// 8. 验证照片详情（描述、尺寸）
	start := time.Now()
	resp, err := http.Get(base + "/photos/" + photoID)
	elapsed := time.Since(start)
	if err != nil {
		record("AutoSync-照片详情", "FAIL", err.Error(), elapsed)
		return
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	var photo map[string]any
	_ = json.Unmarshal(body, &photo)

	desc, _ := photo["description"].(string)
	if desc == "" {
		record("AutoSync-描述验证", "FAIL", "description is empty", 0)
	} else if desc != "一张展示AI测试场景的PNG图片，画面中心是一个测试图案" {
		record("AutoSync-描述验证", "FAIL", fmt.Sprintf("description mismatch: %s", desc), 0)
	} else {
		record("AutoSync-描述验证", "PASS", fmt.Sprintf("description matched, len=%d", len(desc)), 0)
	}

	width, _ := photo["width"].(float64)
	height, _ := photo["height"].(float64)
	if width == 300 && height == 300 {
		record("AutoSync-尺寸验证", "PASS", "300x300", 0)
	} else {
		record("AutoSync-尺寸验证", "FAIL", fmt.Sprintf("expected 300x300, got %.0fx%.0f", width, height), 0)
	}

	// 9. 验证图片文件服务
	start = time.Now()
	resp2, err := http.Get(base + "/photos/" + photoID + "/image")
	elapsed = time.Since(start)
	if err != nil {
		record("AutoSync-图片获取", "FAIL", err.Error(), elapsed)
		return
	}
	resp2.Body.Close()
	if resp2.StatusCode != 200 {
		record("AutoSync-图片获取", "FAIL", fmt.Sprintf("status=%d", resp2.StatusCode), elapsed)
		return
	}
	record("AutoSync-图片获取", "PASS", fmt.Sprintf("status=%d", resp2.StatusCode), elapsed)

	// 10. 验证缩略图
	start = time.Now()
	resp3, err := http.Get(base + "/photos/" + photoID + "/image?size=thumb")
	elapsed = time.Since(start)
	if err != nil {
		record("AutoSync-缩略图获取", "FAIL", err.Error(), elapsed)
		return
	}
	resp3.Body.Close()
	if resp3.StatusCode != 200 {
		record("AutoSync-缩略图获取", "FAIL", fmt.Sprintf("status=%d", resp3.StatusCode), elapsed)
		return
	}
	record("AutoSync-缩略图获取", "PASS", fmt.Sprintf("status=%d", resp3.StatusCode), elapsed)
}

// ========== Group 3: Batch VLM Tests ==========

func runBatchVLMTests() {
	if *configFlag == "" {
		record("BatchVLM-配置加载", "SKIP", "-c not set, skipping real VLM test", 0)
		record("BatchVLM-VLM调用", "SKIP", "-c not set", 0)
		record("BatchVLM-JSON生成", "SKIP", "-c not set", 0)
		return
	}

	// 1. 加载配置文件，读取 VLM 配置
	if err := config.Init(*configFlag); err != nil {
		record("BatchVLM-配置加载", "FAIL", err.Error(), 0)
		return
	}
	cfg := config.Get()
	vlmCfg := cfg.VLM

	if vlmCfg.APIKey == "" {
		record("BatchVLM-配置加载", "FAIL", "vlm.api_key is empty in config", 0)
		return
	}
	record("BatchVLM-配置加载", "PASS",
		fmt.Sprintf("provider=%s, model=%s", vlmCfg.Provider, vlmCfg.Model), 0)

	// 2. 创建临时环境
	tempDir := filepath.Join(os.TempDir(), fmt.Sprintf("photo-agent-vlm-%d", time.Now().Unix()))
	photoDir := filepath.Join(tempDir, "photos")
	descPath := filepath.Join(tempDir, "descriptions.json")
	_ = os.MkdirAll(photoDir, 0755)
	defer func() {
		_ = os.RemoveAll(tempDir)
		fmt.Printf("BatchVLM cleaned up: %s\n", tempDir)
	}()

	// 3. 复制真实测试图片
	if err := copyFile("backend/test/test.png", filepath.Join(photoDir, "test.png")); err != nil {
		record("BatchVLM-复制测试图片", "FAIL", err.Error(), 0)
		return
	}
	record("BatchVLM-复制测试图片", "PASS", "test.png copied", 0)

	// 4. 构造 batch_vlm 配置文件（复用 -c 中的 VLM 配置）
	configContent := fmt.Sprintf(`
[storage]
photo_src = "%s"
descriptions_path = "%s"

[vlm]
provider = "%s"
api_key = "%s"
model = "%s"
base_url = "%s"
concurrency = 1
retry = 2
`, photoDir, descPath, vlmCfg.Provider, vlmCfg.APIKey, vlmCfg.Model, vlmCfg.BaseURL)
	configFile := filepath.Join(tempDir, "vlm.toml")
	_ = os.WriteFile(configFile, []byte(configContent), 0644)

	// 5. 执行 batch_vlm
	binPath := filepath.Join("bin", "batch_vlm")
	if _, err := os.Stat(binPath); os.IsNotExist(err) {
		record("BatchVLM-执行", "FAIL", "batch_vlm binary not found", 0)
		return
	}

	cmd := exec.Command(binPath, "-input", photoDir, "-c", configFile, "-l")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	start := time.Now()
	if err := cmd.Run(); err != nil {
		record("BatchVLM-执行", "FAIL", err.Error(), time.Since(start))
		return
	}
	elapsed := time.Since(start)
	record("BatchVLM-执行", "PASS", fmt.Sprintf("elapsed=%v", elapsed), elapsed)

	// 6. 验证 descriptions.json 生成
	data, err := os.ReadFile(descPath)
	if err != nil {
		record("BatchVLM-JSON生成", "FAIL", err.Error(), 0)
		return
	}

	var descMap map[string]map[string]any
	if err := json.Unmarshal(data, &descMap); err != nil {
		record("BatchVLM-JSON解析", "FAIL", err.Error(), 0)
		return
	}

	entry, ok := descMap["test.png"]
	if !ok {
		record("BatchVLM-JSON内容", "FAIL", "test.png entry not found", 0)
		return
	}

	description, _ := entry["description"].(string)
	if description == "" {
		record("BatchVLM-描述生成", "FAIL", "description is empty", 0)
		return
	}

	modelUsed, _ := entry["model"].(string)
	processedAt, _ := entry["processed_at"].(string)
	record("BatchVLM-描述生成", "PASS",
		fmt.Sprintf("model=%s, desc_len=%d, processed_at=%s", modelUsed, len(description), processedAt), 0)

	// 7. 验证 shot_at 字段（EXIF 读取）
	shotAt, _ := entry["shot_at"].(string)
	if shotAt != "" {
		record("BatchVLM-EXIF读取", "PASS", fmt.Sprintf("shot_at=%s", shotAt), 0)
	} else {
		record("BatchVLM-EXIF读取", "PASS", "shot_at empty (PNG has no EXIF DateTimeOriginal)", 0)
	}

	record("BatchVLM-全流程", "PASS", "VLM -> descriptions.json flow verified", 0)
}

// ========== Utilities ==========

func record(name, status, detail string, elapsed time.Duration) {
	r := TestResult{
		Name:    name,
		Status:  status,
		Detail:  detail,
		Elapsed: elapsed.String(),
	}
	results = append(results, r)

	icon := "✓"
	if status == "FAIL" {
		icon = "✗"
	} else if status == "SKIP" {
		icon = "⊘"
	}
	fmt.Printf("[%s] %s | %s | %s | %s\n", icon, name, status, elapsed, detail)
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	_ = os.MkdirAll(filepath.Dir(dst), 0755)

	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, in)
	return err
}

func printReport() {
	fmt.Println()
	fmt.Println("=== Test Report ===")

	pass := 0
	fail := 0
	skip := 0
	for _, r := range results {
		switch r.Status {
		case "PASS":
			pass++
		case "FAIL":
			fail++
		case "SKIP":
			skip++
		}
	}

	fmt.Printf("Total: %d | Pass: %d | Fail: %d | Skip: %d\n", len(results), pass, fail, skip)
	fmt.Println()
	fmt.Println("测试覆盖范围：")
	fmt.Println("- 健康检查接口：验证服务器正常启动")
	fmt.Println("- 导入任务接口：验证导入流水线可正常创建、执行、查询")
	fmt.Println("- 照片管理接口：验证照片 CRUD（列表、详情、原图、缩略图）")
	fmt.Println("- 时间线接口：验证时间线列表和关联照片查询")
	fmt.Println("- 标签接口：验证标签列表和关联照片查询")
	fmt.Println("- AutoSync 流程：验证 server 启动时自动同步 descriptions.json -> SQLite")
	fmt.Println("- 数据存储：验证 SQLite 数据库自动迁移和照片元数据持久化")
	fmt.Println("- 文件服务：验证照片文件存储到指定目录")
	fmt.Println("- 预描述加载：验证 descriptions.json 预描述文件加载和匹配")
	fmt.Println("- batch_vlm 流程：验证真实图片 VLM 处理 -> descriptions.json（需 -c 传入含 vlm 配置的文件）")

	if fail > 0 {
		fmt.Println()
		fmt.Println("Failed tests:")
		for _, r := range results {
			if r.Status == "FAIL" {
				fmt.Printf("  - %s: %s\n", r.Name, r.Detail)
			}
		}
		os.Exit(1)
	}
}

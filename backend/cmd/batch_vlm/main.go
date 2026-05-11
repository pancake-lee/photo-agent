package main

import (
	"encoding/json"
	"errors"
	"flag"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/vlm"
	"go.uber.org/zap/zapcore"
)

var (
	inputFlag  = flag.String("input", "", "input photo directory")
	configFlag = flag.String("c", "", "config file path (e.g. pancake.yaml)")
	dryRun     = flag.Bool("dry-run", false, "dry run, test config only")
	logConsole = flag.Bool("l", false, "log to console; false for file only")
	force      = flag.Bool("force", false, "force reprocess all images")
)

func main() {
	flag.Parse()
	plogger.InitLogger(*logConsole, zapcore.DebugLevel, "")

	if *inputFlag == "" {
		plogger.Fatal("-input is required")
	}

	if *configFlag != "" {
		if err := config.Init(*configFlag); err != nil {
			plogger.Fatalf("config init failed: %v", err)
		}
	} else {
		if err := config.Init(); err != nil {
			plogger.Fatalf("config init failed: %v", err)
		}
	}

	cfg := config.Get()
	outputPath := cfg.Storage.DescriptionsPath
	concurrency := cfg.VLM.Concurrency
	if concurrency <= 0 {
		concurrency = 3
	}
	retry := cfg.VLM.Retry
	if retry <= 0 {
		retry = 3
	}

	if *dryRun {
		plogger.Infof("Dry run mode")
		plogger.Infof("VLM Provider: %s", cfg.VLM.Provider)
		plogger.Infof("VLM Model: %s", cfg.VLM.Model)
		plogger.Infof("VLM BaseURL: %s", cfg.VLM.BaseURL)
		plogger.Infof("API Key exists: %v", cfg.VLM.APIKey != "")
		return
	}

	images, err := scanImages(*inputFlag)
	if err != nil {
		plogger.Fatalf("scan images failed: %v", err)
	}
	if len(images) == 0 {
		plogger.Info("no images found")
		return
	}

	plogger.Infof("Found %d images, concurrency=%d, retry=%d", len(images), concurrency, retry)

	result := make(map[string]vlmDescEntry)
	var mu sync.Mutex

	// 加载已有结果
	if data, err := os.ReadFile(outputPath); err == nil {
		_ = json.Unmarshal(data, &result)
	}

	// force 模式：清理已有压缩文件和描述条目
	if *force {
		for _, img := range images {
			_ = os.Remove(vlm.GetCompressedPath(img))
		}
		mu.Lock()
		for _, img := range images {
			relPath, _ := filepath.Rel(*inputFlag, img)
			if relPath == "" {
				relPath = filepath.Base(img)
			}
			relPath = filepath.ToSlash(relPath)
			delete(result, relPath)
		}
		mu.Unlock()
		plogger.Info("Force mode: cleared existing compressed images and descriptions")
	}

	sem := make(chan struct{}, concurrency)
	var wg sync.WaitGroup

	start := time.Now()
	successCount := 0
	failCount := 0
	skippedCount := 0
	var countMu sync.Mutex

	for i, img := range images {
		wg.Add(1)
		sem <- struct{}{}

		go func(idx int, imgPath string) {
			defer wg.Done()
			defer func() { <-sem }()

			relPath, _ := filepath.Rel(*inputFlag, imgPath)
			if relPath == "" {
				relPath = filepath.Base(imgPath)
			}
			relPath = filepath.ToSlash(relPath)

			// 检查是否已有描述
			if !*force {
				mu.Lock()
				_, exists := result[relPath]
				mu.Unlock()
				if exists {
					plogger.Infof("[%d/%d] Skipped (already described): %s", idx+1, len(images), relPath)
					countMu.Lock()
					skippedCount++
					countMu.Unlock()
					return
				}
			}

			plogger.Infof("[%d/%d] Processing: %s", idx+1, len(images), relPath)

			var desc, modelName string
			err := papp.NewRunner("batch_vlm").RunRetry(retry, 2*time.Second, func() error {
				var e error
				desc, modelName, e = vlm.DescribeImage(imgPath)
				return e
			})

			if err != nil {
				if errors.Is(err, vlm.ErrQuotaExceeded) {
					plogger.Fatalf("Quota exceeded, stopping: %v", err)
				}
				plogger.Warnf("Failed %s: %v", relPath, err)
				countMu.Lock()
				failCount++
				countMu.Unlock()
				return
			}

			mu.Lock()
			result[relPath] = vlmDescEntry{
				Description: desc,
				Model:       modelName,
				ProcessedAt: time.Now().UTC().Format(time.RFC3339),
			}
			mu.Unlock()

			countMu.Lock()
			successCount++
			countMu.Unlock()

			// 每处理 10 张保存一次中间结果
			if (idx+1)%10 == 0 {
				mu.Lock()
				snapshot := make(map[string]vlmDescEntry, len(result))
				for k, v := range result {
					snapshot[k] = v
				}
				mu.Unlock()
				_ = saveResult(outputPath, snapshot)
			}
		}(i, img)
	}

	wg.Wait()

	// 最终保存
	if err := saveResult(outputPath, result); err != nil {
		plogger.Fatalf("save result failed: %v", err)
	}

	elapsed := time.Since(start)
	plogger.Infof("Batch VLM done: success=%d, failed=%d, skipped=%d, total=%d, elapsed=%v",
		successCount, failCount, skippedCount, len(images), elapsed)
	plogger.Infof("Output: %s", outputPath)
}

func scanImages(root string) ([]string, error) {
	var images []string
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if info.IsDir() {
			return nil
		}
		ext := filepath.Ext(path)
		ext = strings.ToLower(ext)
		if ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".webp" {
			images = append(images, path)
		}
		return nil
	})
	return images, err
}

type vlmDescEntry struct {
	Description string `json:"description"`
	Model       string `json:"model"`
	ProcessedAt string `json:"processed_at"`
}

func saveResult(path string, result map[string]vlmDescEntry) error {
	dir := filepath.Dir(path)
	if dir != "" && dir != "." {
		_ = os.MkdirAll(dir, 0755)
	}
	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return err
	}
	tmpPath := path + ".tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil {
		return err
	}
	return os.Rename(tmpPath, path)
}

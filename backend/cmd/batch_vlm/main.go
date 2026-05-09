package main

import (
	"encoding/json"
	"flag"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/vlm"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

var (
	inputFlag   = flag.String("input", "", "input photo directory")
	outputFlag  = flag.String("output", "./data/descriptions.json", "output descriptions json file")
	concurrency = flag.Int("concurrency", 3, "max concurrency")
	retry       = flag.Int("retry", 3, "retry times on failure")
	dryRun      = flag.Bool("dry-run", false, "dry run, test config only")
)

func main() {
	flag.Parse()
	plogger.InitConsoleLogger()

	if *inputFlag == "" {
		plogger.Fatal("-input is required")
	}

	if err := config.Init(); err != nil {
		plogger.Fatalf("config init failed: %v", err)
	}

	if *dryRun {
		cfg := config.Get()
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

	plogger.Infof("Found %d images, concurrency=%d, retry=%d", len(images), *concurrency, *retry)

	result := make(map[string]vlmDescEntry)
	var mu sync.Mutex

	sem := make(chan struct{}, *concurrency)
	var wg sync.WaitGroup

	start := time.Now()
	successCount := 0
	failCount := 0
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

			plogger.Infof("[%d/%d] Processing: %s", idx+1, len(images), relPath)

			var desc, modelName string
			err := papp.NewRunner("batch_vlm").RunRetry(*retry, 2*time.Second, func() error {
				var e error
				desc, modelName, e = vlm.DescribeImage(imgPath)
				return e
			})

			if err != nil {
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
				_ = saveResult(*outputFlag, result)
			}
		}(i, img)
	}

	wg.Wait()

	// 最终保存
	if err := saveResult(*outputFlag, result); err != nil {
		plogger.Fatalf("save result failed: %v", err)
	}

	elapsed := time.Since(start)
	plogger.Infof("Batch VLM done: success=%d, failed=%d, total=%d, elapsed=%v",
		successCount, failCount, len(images), elapsed)
	plogger.Infof("Output: %s", *outputFlag)
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
	return os.WriteFile(path, data, 0644)
}

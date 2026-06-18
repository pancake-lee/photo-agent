package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/service"
	"github.com/pancake-lee/photo-agent/internal/vlm"
	"go.uber.org/zap/zapcore"
)

var (
	inputFlag  = flag.String("input", "", "input photo directory or single image file")
	configFlag = flag.String("c", "", "config file path (e.g. ./configs/config.yaml)")
	dryRun     = flag.Bool("dry-run", false, "dry run, test config only")
	logConsole = flag.Bool("l", false, "log to console; false for file only")
	force      = flag.Bool("force", false, "force reprocess all images")
	noDedup    = flag.Bool("no-dedup", false, "disable MD5 dedup check")
	limitFlag  = flag.Int("n", 0, "max images to process (0 = no limit)")
)

func main() {
	flag.Parse()
	plogger.InitLogger(*logConsole, zapcore.DebugLevel, "")

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

	// -input 为空时，从配置文件读取 storage.photo_src
	if *inputFlag == "" {
		if cfg.Storage.PhotoSrc != "" {
			*inputFlag = cfg.Storage.PhotoSrc
			plogger.Infof("Using photo_src from config: %s", *inputFlag)
		} else {
			plogger.Fatal("-input is required (or set storage.photo_src in config)")
		}
	}

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

	// 判断输入是单文件还是目录（影响 relPath 计算方式）
	inputInfo, _ := os.Stat(*inputFlag)
	inputIsFile := inputInfo != nil && !inputInfo.IsDir()

	// -n 限制处理数量（对目录输入有意义，单文件忽略）
	if *limitFlag > 0 && len(images) > *limitFlag {
		images = images[:*limitFlag]
		plogger.Infof("Limited to %d images by -n flag", *limitFlag)
	}

	plogger.Infof("Found %d images, concurrency=%d, retry=%d", len(images), concurrency, retry)

	result := make(map[string]vlmDescEntry)
	var mu sync.Mutex

	// 加载已有结果
	if data, err := os.ReadFile(outputPath); err == nil {
		_ = json.Unmarshal(data, &result)
	}

	// MD5 去重
	var dedupReg *service.DedupRegistry
	if !*noDedup {
		dedupPath := filepath.Join(filepath.Dir(outputPath), "dedup_hashes.json")
		dedupReg = service.LoadDedupRegistry(dedupPath)
		plogger.Infof("Dedup registry: %d hashes loaded", dedupReg.Count())
	}

	// force 模式：清理已有压缩文件和描述条目
	if *force {
		for _, img := range images {
			_ = os.Remove(vlm.GetCompressedPath(img))
		}
		mu.Lock()
		for _, img := range images {
			relPath := computeRelPath(*inputFlag, img, inputIsFile)
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

			relPath := computeRelPath(*inputFlag, imgPath, inputIsFile)

				// MD5 去重检查
				if dedupReg != nil {
					fileMD5, err := service.ComputeFileMD5(imgPath)
					if err == nil {
						if firstPath, exists := dedupReg.Exists(fileMD5); exists {
							plogger.Infof("[%d/%d] Dedup skip (same as %s): %s", idx+1, len(images), firstPath, relPath)
							countMu.Lock()
							skippedCount++
							countMu.Unlock()
							return
						}
					} else {
						plogger.Warnf("MD5 compute failed %s: %v", relPath, err)
					}
				}

			// 检查是否已有描述
			if !*force {
				mu.Lock()
				entry, exists := result[relPath]
				mu.Unlock()
				if exists {
					// 已有描述：检查是否已有 shot_at
					if entry.ShotAt != "" {
						plogger.Infof("[%d/%d] Skipped (already described): %s", idx+1, len(images), relPath)
						countMu.Lock()
						skippedCount++
						countMu.Unlock()
						return
					}
					// 已有描述但无 shot_at：补充 shot_at，跳过 VLM
					shotAt := service.GetExifShotAt(imgPath)
					shotAtStr := ""
					if shotAt != nil {
						shotAtStr = shotAt.UTC().Format(time.RFC3339)
					}
					mu.Lock()
					entry.ShotAt = shotAtStr
					result[relPath] = entry
					mu.Unlock()
					plogger.Infof("[%d/%d] ShotAt appended (skip VLM): %s", idx+1, len(images), relPath)
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

			// 读取 EXIF 拍摄时间
			shotAt := service.GetExifShotAt(imgPath)
			shotAtStr := ""
			if shotAt != nil {
				shotAtStr = shotAt.UTC().Format(time.RFC3339)
			}

			mu.Lock()
			result[relPath] = vlmDescEntry{
				Description: desc,
				Model:       modelName,
				ProcessedAt: time.Now().UTC().Format(time.RFC3339),
				ShotAt:      shotAtStr,
			}
			mu.Unlock()

				// 注册 MD5 去重
				if dedupReg != nil {
					if fileMD5, err := service.ComputeFileMD5(imgPath); err == nil {
						dedupReg.Register(fileMD5, relPath)
					}
				}

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

	// 保存去重注册表
	if dedupReg != nil {
		if err := dedupReg.Save(); err != nil {
			plogger.Warnf("Dedup registry save failed: %v", err)
		}
	}

	// 最终保存
	if err := saveResult(outputPath, result); err != nil {
		plogger.Fatalf("save result failed: %v", err)
	}

	elapsed := time.Since(start)
	plogger.Infof("Batch VLM done: success=%d, failed=%d, skipped=%d, total=%d, elapsed=%v",
		successCount, failCount, skippedCount, len(images), elapsed)
	plogger.Infof("Output: %s", outputPath)
}

// computeRelPath 计算相对路径。单文件输入时返回文件名，目录输入时返回相对于 inputPath 的路径。
func computeRelPath(inputPath, imgPath string, inputIsFile bool) string {
	if inputIsFile {
		return filepath.Base(imgPath)
	}
	relPath, _ := filepath.Rel(inputPath, imgPath)
	if relPath == "" {
		relPath = filepath.Base(imgPath)
	}
	return filepath.ToSlash(relPath)
}

func scanImages(path string) ([]string, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, err
	}

	if !info.IsDir() {
		// 单文件输入：校验扩展名
		ext := strings.ToLower(filepath.Ext(path))
		if ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".webp" {
			return []string{path}, nil
		}
		return nil, fmt.Errorf("unsupported image format: %s", ext)
	}

	// 目录输入：递归扫描
	var images []string
	err = filepath.Walk(path, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if info.IsDir() {
			return nil
		}
		ext := strings.ToLower(filepath.Ext(p))
		if ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".webp" {
			images = append(images, p)
		}
		return nil
	})
	return images, err
}

type vlmDescEntry struct {
	Description string `json:"description"`
	Model       string `json:"model"`
	ProcessedAt string `json:"processed_at"`
	ShotAt      string `json:"shot_at"` // EXIF 拍摄时间，RFC3339 格式
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

package service

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/model"
	"github.com/pancake-lee/photo-agent/internal/vlm"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

// VlmPipeline 共享 VLM 处理管线，同时服务 CLI（batch_vlm）和 Web（VLM 队列）。
// 仅封装"单张处理 + 结果写入"的核心逻辑，扫描/并发控制由调用方自行管理。

// VlmResult 单张 VLM 处理结果
type VlmResult struct {
	Description string `json:"description"`
	Model       string `json:"model"`
}

// ProcessAndSave 对单张图片执行 VLM 描述，并将结果写入 descriptions.json 和 SQLite。
// imagePath: 图片绝对路径
// photoID: 数据库中照片 ID（Web 队列使用）或空字符串（CLI 使用，仅写文件）
// relPath: 照片相对路径，作为 descriptions.json 的 key
func ProcessAndSave(imagePath, photoID, relPath string) (*VlmResult, error) {
	if relPath == "" {
		relPath = filepath.Base(imagePath)
	}
	relPath = filepath.ToSlash(relPath)

	// 1. VLM 描述
	desc, modelName, err := vlm.DescribeImage(imagePath)
	if err != nil {
		return nil, fmt.Errorf("vlm describe failed: %w", err)
	}

	result := &VlmResult{
		Description: desc,
		Model:       modelName,
	}

	// 2. 读取 EXIF 拍摄时间
	shotAt := GetExifShotAt(imagePath)
	shotAtStr := ""
	if shotAt != nil {
		shotAtStr = shotAt.UTC().Format(time.RFC3339)
	}

	// 3. 写入 descriptions.json
	if err := saveToDescriptionsFile(relPath, desc, modelName, shotAtStr); err != nil {
		plogger.Warnf("Save to descriptions.json failed %s: %v", relPath, err)
		// 不阻塞——VLM 结果已拿到，文件写入失败不致命
	}

	// 4. 更新 SQLite（仅 Web 队列场景有 photoID）
	if photoID != "" {
		if err := updatePhotoDescription(photoID, desc, modelName); err != nil {
			plogger.Warnf("Update photo description in DB failed %s: %v", photoID, err)
		}
	}

	return result, nil
}

// saveToDescriptionsFile 将单条描述写入 descriptions.json（线程安全）。
func saveToDescriptionsFile(relPath, desc, model, shotAt string) error {
	outputPath := config.Get().ResolvePath(config.Get().Storage.DescriptionsPath)
	if outputPath == "" {
		return fmt.Errorf("descriptions_path not configured")
	}

	dir := filepath.Dir(outputPath)
	if dir != "" && dir != "." {
		_ = os.MkdirAll(dir, 0755)
	}

	// 加载已有数据
	result := make(map[string]interface{})
	if data, err := os.ReadFile(outputPath); err == nil {
		_ = json.Unmarshal(data, &result)
	}

	result[relPath] = map[string]interface{}{
		"description": desc,
		"model":       model,
		"processed_at": time.Now().UTC().Format(time.RFC3339),
		"shot_at":     shotAt,
	}

	// 原子写入（先写 tmp 再 rename）
	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal descriptions failed: %w", err)
	}

	tmpPath := outputPath + ".tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil {
		return fmt.Errorf("write tmp file failed: %w", err)
	}
	return os.Rename(tmpPath, outputPath)
}

// updatePhotoDescription 更新 SQLite 中照片的描述字段。
func updatePhotoDescription(photoID, desc, modelName string) error {
	_ = modelName // 当前 model.Photo 无 model_name 字段，仅更新 description
	return db.Model(&model.Photo{}).Where("id = ?", photoID).
		Update("description", desc).Error
}

// ScanImagesForPipeline 扫描目录下所有图片文件。
// 返回绝对路径列表。
func ScanImagesForPipeline(root string) ([]string, error) {
	var images []string

	info, err := os.Stat(root)
	if err != nil {
		return nil, err
	}

	if !info.IsDir() {
		ext := strings.ToLower(filepath.Ext(root))
		if ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".webp" {
			return []string{root}, nil
		}
		return nil, fmt.Errorf("unsupported image format: %s", ext)
	}

	err = filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
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

// ComputeRelPath 计算相对路径。
// inputIsFile: 输入是单文件时返回文件名，否则返回相对于 inputPath 的路径。
func ComputeRelPath(inputPath, imgPath string, inputIsFile bool) string {
	if inputIsFile {
		return filepath.Base(imgPath)
	}
	relPath, _ := filepath.Rel(inputPath, imgPath)
	if relPath == "" {
		relPath = filepath.Base(imgPath)
	}
	return filepath.ToSlash(relPath)
}

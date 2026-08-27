package service

import (
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"os/exec"
	"path/filepath"
)

// maybeCompressImage 检查图片大小，超过限制时压缩为 JPEG。
// 压缩产物使用请求级临时文件；未超限时返回经过预检的 JPG 原路径。
func maybeCompressImage(imagePath string, maxSizeMB float64) (string, func(), error) {
	if err := validateVlmInput(imagePath); err != nil {
		return "", nil, err
	}

	if maxSizeMB <= 0 {
		return imagePath, nil, nil
	}

	info, err := os.Stat(imagePath)
	if err != nil {
		return "", nil, fmt.Errorf("stat image failed: %w", err)
	}

	maxBytes := int64(maxSizeMB * 1024 * 1024)
	if info.Size() <= maxBytes {
		return imagePath, nil, nil
	}

	outputPath, cleanup, err := resolveCompressOutput(imagePath)
	if err != nil {
		return "", nil, err
	}

	dir := filepath.Dir(outputPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		if cleanup != nil {
			cleanup()
		}
		return "", nil, fmt.Errorf("mkdir failed: %w", err)
	}

	cmd := exec.Command("convert", imagePath,
		"-resize", "512x512>",
		"-quality", "85",
		"-format", "jpg",
		outputPath,
	)
	if out, err := cmd.CombinedOutput(); err != nil {
		if cleanup != nil {
			cleanup()
		}
		return "", nil, fmt.Errorf("imagemagick compress failed: %w, output: %s", err, string(out))
	}

	return outputPath, cleanup, nil
}

// validateVlmInput 在调用 VLM 前执行零 Token 输入预检。
// VLM 只接收可解码的 JPG/JPEG，避免把 NEF 或损坏文件送入模型。
func validateVlmInput(imagePath string) error {
	ext := filepath.Ext(imagePath)
	if ext != ".jpg" && ext != ".jpeg" && ext != ".JPG" && ext != ".JPEG" {
		return fmt.Errorf("VLM only accepts JPG/JPEG input, got %q", imagePath)
	}

	file, err := os.Open(imagePath)
	if err != nil {
		return fmt.Errorf("open VLM input failed: %w", err)
	}
	defer file.Close()

	config, format, err := image.DecodeConfig(file)
	if err != nil {
		return fmt.Errorf("decode VLM input failed: %w", err)
	}
	if format != "jpeg" {
		return fmt.Errorf("VLM input extension/content mismatch: extension=%q format=%q", ext, format)
	}
	if config.Width <= 0 || config.Height <= 0 {
		return fmt.Errorf("VLM input has invalid dimensions: %dx%d", config.Width, config.Height)
	}
	return nil
}

// resolveCompressOutput 为每次 VLM 请求创建独立临时文件。
// 不按基础文件名落盘，避免同名照片或 JPG/NEF 互相覆盖、误复用。
func resolveCompressOutput(inputPath string) (string, func(), error) {
	tmpFile, err := os.CreateTemp("", "photo-agent-compress-*.jpg")
	if err != nil {
		return "", nil, fmt.Errorf("create temp file failed: %w", err)
	}
	tmpFile.Close()
	return tmpFile.Name(), func() { _ = os.Remove(tmpFile.Name()) }, nil
}

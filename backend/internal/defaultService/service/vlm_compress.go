package service

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"backend/internal/defaultService/conf"
)

// maybeCompressImage 检查图片大小，超过限制时压缩为 JPEG。
// PhotoSrc 下的文件输出到 PhotoPath 对应路径，其他使用临时文件。
// 未超限时返回原路径和 nil cleanup。
func maybeCompressImage(imagePath string, maxSizeMB float64) (string, func(), error) {
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

	if fi, err := os.Stat(outputPath); err == nil && fi.Size() > 0 {
		return outputPath, cleanup, nil
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

// resolveCompressOutput 解析压缩输出路径。
// PhotoSrc 下的文件映射到 PhotoPath 对应路径，其他使用临时文件。
func resolveCompressOutput(inputPath string) (string, func(), error) {
	absPhotoSrc, _ := filepath.Abs(conf.C.Storage.PhotoSrc)
	if absPhotoSrc != "" && strings.HasPrefix(inputPath, absPhotoSrc+string(filepath.Separator)) {
		rel := strings.TrimPrefix(inputPath, absPhotoSrc+string(filepath.Separator))
		base := strings.TrimSuffix(filepath.Base(rel), filepath.Ext(rel))
		outputPath := filepath.Join(conf.C.Storage.PhotoPath, base+".jpg")
		return outputPath, nil, nil
	}

	tmpFile, err := os.CreateTemp("", "photo-agent-compress-*.jpg")
	if err != nil {
		return "", nil, fmt.Errorf("create temp file failed: %w", err)
	}
	tmpFile.Close()
	return tmpFile.Name(), func() { _ = os.Remove(tmpFile.Name()) }, nil
}

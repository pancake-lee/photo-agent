package vlm

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/pancake-lee/photo-agent/internal/config"
)

// MaybeCompressImage 检查图片大小，超过限制时压缩为 JPEG。
// /root/project/ 下的文件输出到 PhotoPath 对应路径，其他使用临时文件。
// 未超限时返回原路径和 nil cleanup。
func MaybeCompressImage(imagePath string, maxSizeMB float64) (string, func(), error) {
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

	// 已有压缩文件直接复用
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

// GetCompressedPath 返回输入图片对应的压缩后路径（无压缩操作）。
func GetCompressedPath(inputPath string) string {
	outputPath, _, _ := resolveCompressOutput(inputPath)
	return outputPath
}

// resolveCompressOutput 解析压缩输出路径。
// /root/project/ 下的文件映射到 PhotoPath 对应路径，其他使用临时文件。
func resolveCompressOutput(inputPath string) (string, func(), error) {
	const projectPrefix = "/root/project/"
	if strings.HasPrefix(inputPath, projectPrefix) {
		rel := strings.TrimPrefix(inputPath, projectPrefix)
		base := strings.TrimSuffix(filepath.Base(rel), filepath.Ext(rel))
		outputPath := filepath.Join(config.Get().Storage.PhotoPath, base+".jpg")
		return outputPath, nil, nil
	}

	tmpFile, err := os.CreateTemp("", "photo-agent-compress-*.jpg")
	if err != nil {
		return "", nil, fmt.Errorf("create temp file failed: %w", err)
	}
	tmpFile.Close()
	return tmpFile.Name(), func() { _ = os.Remove(tmpFile.Name()) }, nil
}

func getMimeType(path string) string {
	ext := filepath.Ext(path)
	switch ext {
	case ".png":
		return "image/png"
	case ".jpg", ".jpeg":
		return "image/jpeg"
	case ".webp":
		return "image/webp"
	default:
		return "image/jpeg"
	}
}

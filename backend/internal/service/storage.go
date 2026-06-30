package service

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/satori/go.uuid"
)

// StorePhoto 将照片复制到存储目录，返回存储后的相对路径。
// 如果源文件已在 PhotoPath 下，或存在对应压缩版本，直接返回已有路径不再拷贝。
func StorePhoto(sourcePath, timeline string) (string, error) {
	_ = timeline
	cfg := config.Get().Storage

	absPhotoPath, _ := filepath.Abs(cfg.PhotoPath)
	absSourcePath, _ := filepath.Abs(sourcePath)

	// 已在 PhotoPath 下，直接返回相对路径
	if strings.HasPrefix(absSourcePath, absPhotoPath+string(filepath.Separator)) {
		relPath, _ := filepath.Rel(absPhotoPath, absSourcePath)
		plogger.Infof("Photo already in storage: %s", relPath)
		return relPath, nil
	}

	// 若是 photo_src 下的文件，检查对应压缩版本是否已在 photo_path 中
	absPhotoSrc, _ := filepath.Abs(cfg.PhotoSrc)
	if absPhotoSrc != "" && strings.HasPrefix(absSourcePath, absPhotoSrc+string(filepath.Separator)) {
		rel := strings.TrimPrefix(absSourcePath, absPhotoSrc+string(filepath.Separator))
		base := strings.TrimSuffix(filepath.Base(rel), filepath.Ext(rel))
		compressedPath := filepath.Join(absPhotoPath, base+".jpg")
		if _, err := os.Stat(compressedPath); err == nil {
			relPath, _ := filepath.Rel(absPhotoPath, compressedPath)
			plogger.Infof("Using compressed photo: %s", relPath)
			return relPath, nil
		}
	}

	// 拷贝到 PhotoPath 根目录
	targetDir := cfg.PhotoPath
	if err := os.MkdirAll(targetDir, 0755); err != nil {
		return "", fmt.Errorf("create target dir failed: %w", err)
	}

	originalName := filepath.Base(sourcePath)
	ext := filepath.Ext(originalName)
	nameWithoutExt := originalName[:len(originalName)-len(ext)]
	newName := fmt.Sprintf("%s_%s%s", nameWithoutExt, uuid.NewV4().String()[:8], ext)
	targetPath := filepath.Join(targetDir, newName)

	src, err := os.Open(sourcePath)
	if err != nil {
		return "", fmt.Errorf("open source file failed: %w", err)
	}
	defer src.Close()

	dst, err := os.Create(targetPath)
	if err != nil {
		return "", fmt.Errorf("create target file failed: %w", err)
	}
	defer dst.Close()

	if _, err := io.Copy(dst, src); err != nil {
		return "", fmt.Errorf("copy file failed: %w", err)
	}

	relPath, _ := filepath.Rel(cfg.PhotoPath, targetPath)
	plogger.Infof("Stored photo: %s -> %s", sourcePath, targetPath)
	return relPath, nil
}

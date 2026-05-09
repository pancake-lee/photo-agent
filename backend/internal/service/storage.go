package service

import (
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/satori/go.uuid"
)

// StorePhoto 将照片复制到存储目录，返回存储后的相对路径
func StorePhoto(sourcePath, timeline string) (string, error) {
	cfg := config.Get().Storage

	// 目标目录：data/photos/{timeline}/
	targetDir := filepath.Join(cfg.PhotoPath, timeline)
	if err := os.MkdirAll(targetDir, 0755); err != nil {
		return "", fmt.Errorf("create target dir failed: %w", err)
	}

	// 生成唯一文件名避免冲突
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

	// 返回相对路径（相对于 photo_path）
	relPath, _ := filepath.Rel(cfg.PhotoPath, targetPath)
	plogger.Infof("Stored photo: %s -> %s", sourcePath, targetPath)
	return relPath, nil
}

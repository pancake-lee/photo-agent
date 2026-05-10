package service

import (
	"crypto/md5"
	"fmt"
	"os"
	"path/filepath"

	"github.com/disintegration/imaging"
	"github.com/pancake-lee/photo-agent/internal/config"
)

// thumbnailWidth 缩略图宽度（像素）
const thumbnailWidth = 300

// GetThumbnail 获取图片缩略图路径，不存在时自动生成并缓存
func GetThumbnail(imagePath string) (string, error) {
	cfg := config.Get().Storage

	// 缩略图缓存目录
	thumbDir := filepath.Join(filepath.Dir(cfg.PhotoPath), "thumbnails")
	if err := os.MkdirAll(thumbDir, 0755); err != nil {
		return "", fmt.Errorf("create thumbnail dir failed: %w", err)
	}

	// 缓存文件名：原图路径 MD5 + .jpg
	hash := md5.Sum([]byte(imagePath))
	cacheName := fmt.Sprintf("%x.jpg", hash)
	cachePath := filepath.Join(thumbDir, cacheName)

	// 缓存命中直接返回
	if _, err := os.Stat(cachePath); err == nil {
		return cachePath, nil
	}

	// 打开原图
	src, err := imaging.Open(imagePath)
	if err != nil {
		return "", fmt.Errorf("open image failed: %w", err)
	}

	// 等比缩放到 thumbnailWidth
	thumb := imaging.Resize(src, thumbnailWidth, 0, imaging.Lanczos)

	// 保存为 JPEG
	if err := imaging.Save(thumb, cachePath, imaging.JPEGQuality(85)); err != nil {
		return "", fmt.Errorf("save thumbnail failed: %w", err)
	}

	return cachePath, nil
}

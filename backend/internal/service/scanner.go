package service

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/pancake-lee/pgo/pkg/plogger"
)

// ImageInfo 扫描到的图片信息
type ImageInfo struct {
	SourcePath string
	Filename   string
	Timeline   string
}

// ScanDirectory 扫描目录下的图片文件
func ScanDirectory(root string, recursive bool) ([]ImageInfo, error) {
	var images []ImageInfo

	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, fmt.Errorf("read dir failed: %w", err)
	}

	// 时间线标签 = 文件夹名
	timeline := filepath.Base(root)

	for _, entry := range entries {
		if entry.IsDir() {
			if recursive {
				subImages, err := ScanDirectory(filepath.Join(root, entry.Name()), true)
				if err != nil {
					plogger.Warnf("scan subdir %s failed: %v", entry.Name(), err)
					continue
				}
				images = append(images, subImages...)
			}
			continue
		}

		if !isImageFile(entry.Name()) {
			continue
		}

		images = append(images, ImageInfo{
			SourcePath: filepath.Join(root, entry.Name()),
			Filename:   entry.Name(),
			Timeline:   timeline,
		})
	}

	plogger.Infof("Scanned %d images from %s", len(images), root)
	return images, nil
}

func isImageFile(name string) bool {
	ext := strings.ToLower(filepath.Ext(name))
	return ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".webp"
}

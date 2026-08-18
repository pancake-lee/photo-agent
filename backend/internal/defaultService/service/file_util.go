package service

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	uuid "github.com/satori/go.uuid"
)

// sanitizeFilename 清理文件名，只保留安全字符
func sanitizeFilename(originalName, ext string) string {
	if originalName == "" {
		return fmt.Sprintf("photo_%s%s", uuid.NewV4().String()[:8], ext)
	}

	base := filepath.Base(originalName)
	baseWithoutExt := strings.TrimSuffix(base, filepath.Ext(base))
	if baseWithoutExt == "" {
		baseWithoutExt = fmt.Sprintf("photo_%s", uuid.NewV4().String()[:8])
	}

	baseWithoutExt = strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') || r == '-' || r == '_' {
			return r
		}
		return '_'
	}, baseWithoutExt)

	return baseWithoutExt + ext
}

// saveUploadedFile 将上传的文件内容写入指定目录，modTime 非空时回写文件修改时间。
func saveUploadedFile(src io.Reader, filename string, targetDir string, modTime *time.Time) error {
	if err := os.MkdirAll(targetDir, 0755); err != nil {
		return fmt.Errorf("create target dir failed: %w", err)
	}

	targetPath := filepath.Join(targetDir, filename)
	dst, err := os.Create(targetPath)
	if err != nil {
		return fmt.Errorf("create file failed: %w", err)
	}
	defer dst.Close()

	if _, err := io.Copy(dst, src); err != nil {
		return fmt.Errorf("write file failed: %w", err)
	}

	if modTime != nil {
		if err := os.Chtimes(targetPath, *modTime, *modTime); err != nil {
			return fmt.Errorf("set file mtime failed: %w", err)
		}
	}

	return nil
}

// compressInPlace 用 ImageMagick 原地压缩 JPEG（保留 EXIF）
func compressInPlace(path string) error {
	tmpPath := path + ".tmp"
	cmd := exec.Command("convert", path,
		"-resize", "512x512>",
		"-quality", "85",
		"-format", "jpg",
		tmpPath,
	)
	if out, err := cmd.CombinedOutput(); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("imagemagick compress failed: %w, output: %s", err, string(out))
	}

	if err := os.Rename(tmpPath, path); err != nil {
		os.Remove(tmpPath)
		return fmt.Errorf("rename compressed failed: %w", err)
	}

	return nil
}

// copyFileContents 复制文件内容
func copyFileContents(src, dst string) error {
	srcFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer srcFile.Close()

	dstFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer dstFile.Close()

	if _, err := io.Copy(dstFile, srcFile); err != nil {
		return err
	}
	return dstFile.Sync()
}

// processToPhotoPath 从 photo_src 复制到 photo_path，超过限制时用 ImageMagick 压缩，
// modTime 非空时在复制/压缩后回写文件修改时间。
func processToPhotoPath(srcPath, filename, photoPath string, maxBytes int64, modTime *time.Time) error {
	targetPath := filepath.Join(photoPath, filename)

	if err := os.MkdirAll(photoPath, 0755); err != nil {
		return fmt.Errorf("create photo_path dir failed: %w", err)
	}

	if err := copyFileContents(srcPath, targetPath); err != nil {
		return fmt.Errorf("copy to photo_path failed: %w", err)
	}

	info, err := os.Stat(targetPath)
	if err != nil {
		return fmt.Errorf("stat target failed: %w", err)
	}

	if maxBytes > 0 && info.Size() > maxBytes {
		if err := compressInPlace(targetPath); err != nil {
			return err
		}
	}

	if modTime != nil {
		if err := os.Chtimes(targetPath, *modTime, *modTime); err != nil {
			return fmt.Errorf("set thumb mtime failed: %w", err)
		}
	}

	return nil
}

// addSuffix 在文件名基础部分加序号后缀
func addSuffix(filename string) string {
	ext := filepath.Ext(filename)
	base := strings.TrimSuffix(filename, ext)
	return fmt.Sprintf("%s-2%s", base, ext)
}

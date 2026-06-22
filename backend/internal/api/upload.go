package api

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/service"
	uuid "github.com/satori/go.uuid"
)

// UploadPhoto 上传图片。
// POST /api/v1/photos/upload
// 表单字段：
//
//	file                原图文件（multipart）
//	original_name        原始文件名
//	original_shot_at     前端读取的 EXIF 拍摄时间（RFC 3339，可选）
//	conflict_resolution  冲突处理策略（可选，"overwrite"|"skip"|"keep_both"）
//
// 流程：原图 → photo_src → ImageMagick 压缩（保留 EXIF）→ photo_path → 入库
func UploadPhoto(c *gin.Context) {
	cfg := config.Get()

	// 解析 multipart 表单
	originalName := c.PostForm("original_name")
	originalShotAt := c.PostForm("original_shot_at")
	conflictResolution := c.PostForm("conflict_resolution")

	file, header, err := c.Request.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "missing file field"})
		return
	}
	defer file.Close()

	// 确定目标文件名
	ext := strings.ToLower(filepath.Ext(header.Filename))
	if ext == "" {
		ext = ".jpg"
	}
	targetFilename := sanitizeFilename(originalName, ext)

	// 检查是否已有同名文件 → 去重判断
	existingPhoto := findPhotoByFilename(targetFilename)
	if existingPhoto != nil {
		// 解析新文件的拍摄时间
		newShotAt := parseShotAt(originalShotAt)

		resolution := conflictResolution
		if resolution == "" {
			// 返回冲突信息，等待前端用户选择
			c.JSON(http.StatusOK, gin.H{
				"status":   "conflict",
				"photo_id": "",
				"conflict": buildConflictInfo(existingPhoto, targetFilename, newShotAt),
			})
			return
		}

		// 已有冲突处理策略
		switch resolution {
		case "overwrite":
			// 保存原图到 photo_src
			if err := saveUploadedFile(file, targetFilename, cfg.Storage.PhotoSrc); err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
				return
			}
			// 压缩到 photo_path
			srcPath := filepath.Join(cfg.Storage.PhotoSrc, targetFilename)
			if err := processToPhotoPath(srcPath, targetFilename); err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
				return
			}
			// 删除 photo_path 旧文件（与 compress 输出路径一致）
			oldPath := filepath.Join(cfg.Storage.PhotoPath, existingPhoto.FilePath)
			if oldPath != filepath.Join(cfg.Storage.PhotoPath, targetFilename) {
				_ = os.Remove(oldPath)
			}
			updatePhotoAfterOverwrite(existingPhoto.ID, targetFilename, newShotAt)
			c.JSON(http.StatusOK, gin.H{"status": "stored", "photo_id": existingPhoto.ID})

		case "skip":
			c.JSON(http.StatusOK, gin.H{"status": "skipped", "photo_id": existingPhoto.ID})

		case "keep_both":
			newFilename := addSuffix(targetFilename)
			if err := saveUploadedFile(file, newFilename, cfg.Storage.PhotoSrc); err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
				return
			}
			srcPath := filepath.Join(cfg.Storage.PhotoSrc, newFilename)
			if err := processToPhotoPath(srcPath, newFilename); err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
				return
			}
			photoID := createPhotoFromUpload(newFilename, originalName, newShotAt)
			c.JSON(http.StatusOK, gin.H{"status": "stored", "photo_id": photoID})

		default:
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid conflict_resolution"})
		}
		return
	}

	// 无冲突：保存原图到 photo_src，压缩到 photo_path，入库
	if err := saveUploadedFile(file, targetFilename, cfg.Storage.PhotoSrc); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	srcPath := filepath.Join(cfg.Storage.PhotoSrc, targetFilename)
	if err := processToPhotoPath(srcPath, targetFilename); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	newShotAt := parseShotAt(originalShotAt)
	photoID := createPhotoFromUpload(targetFilename, originalName, newShotAt)

	plogger.Infof("Photo uploaded: %s → id=%s", targetFilename, photoID)
	c.JSON(http.StatusOK, gin.H{"status": "stored", "photo_id": photoID})
}

// sanitizeFilename 清理文件名，只保留安全字符。
func sanitizeFilename(originalName, ext string) string {
	if originalName == "" {
		return fmt.Sprintf("photo_%s%s", uuid.NewV4().String()[:8], ext)
	}

	// 取基础名（去掉路径分隔符）
	base := filepath.Base(originalName)

	// 去掉已有的扩展名，统一使用传入的 ext
	baseWithoutExt := strings.TrimSuffix(base, filepath.Ext(base))
	if baseWithoutExt == "" {
		baseWithoutExt = fmt.Sprintf("photo_%s", uuid.NewV4().String()[:8])
	}

	// 替换不安全字符
	baseWithoutExt = strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') || r == '-' || r == '_' {
			return r
		}
		return '_'
	}, baseWithoutExt)

	return baseWithoutExt + ext
}

// parseShotAt 解析 RFC 3339 格式的拍摄时间。
func parseShotAt(s string) *time.Time {
	if s == "" {
		return nil
	}
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		return nil
	}
	return &t
}

// saveUploadedFile 将上传的文件内容写入指定目录。
func saveUploadedFile(src io.Reader, filename string, targetDir string) error {
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

	return nil
}

// processToPhotoPath 从 photo_src 复制到 photo_path，超过限制时用 ImageMagick 压缩。
// ImageMagick convert 默认保留 EXIF，因此后续 GetExifInfo 可获取完整元数据。
func processToPhotoPath(srcPath, filename string) error {
	cfg := config.Get()
	targetPath := filepath.Join(cfg.Storage.PhotoPath, filename)

	// 确保 photo_path 目录存在
	if err := os.MkdirAll(cfg.Storage.PhotoPath, 0755); err != nil {
		return fmt.Errorf("create photo_path dir failed: %w", err)
	}

	// 先复制原图到 photo_path
	if err := copyFileContents(srcPath, targetPath); err != nil {
		return fmt.Errorf("copy to photo_path failed: %w", err)
	}

	// 检查是否需要压缩
	info, err := os.Stat(targetPath)
	if err != nil {
		return fmt.Errorf("stat target failed: %w", err)
	}

	maxBytes := int64(cfg.VLM.MaxImageSizeMB * 1024 * 1024)
	if maxBytes > 0 && info.Size() > maxBytes {
		// 用 ImageMagick 压缩（与 CLI 保持一致，保留 EXIF）
		return compressInPlace(targetPath)
	}

	return nil
}

// compressInPlace 用 ImageMagick 原地压缩 JPEG（保留 EXIF）。
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

// copyFileContents 复制文件内容（不保留权限位）。
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

// createPhotoFromUpload 为上传的文件创建数据库记录。
// has_description 默认为 false，后续通过 VLM 队列生成。
func createPhotoFromUpload(filename, originalName string, shotAt *time.Time) string {
	if originalName == "" {
		originalName = filename
	}

	// 读取 EXIF（从 photo_path 中的文件，ImageMagick 压缩后保留完整 EXIF）
	cfg := config.Get()
	fullPath := filepath.Join(cfg.Storage.PhotoPath, filename)
	exifInfo := service.GetExifInfo(fullPath)
	if exifInfo == nil {
		exifInfo = &service.ExifInfo{}
	}

	// 优先使用前端传来的 shotAt
	if shotAt != nil {
		exifInfo.ShotAt = shotAt
	}

	// 拍摄时间匹配活动
	timeline := ""
	if exifInfo.ShotAt != nil {
		timeline = service.FindEventByTime(*exifInfo.ShotAt)
	}

	// 获取图片尺寸
	width, height := service.GetImageSize(fullPath)

	// 存入数据库
	photo, err := service.SavePhoto(filename, filename, timeline, "", "", width, height, exifInfo, "", "", "", "", "", "")
	if err != nil {
		plogger.Warnf("Create photo record failed: %v", err)
		return ""
	}

	return photo.ID
}

// findPhotoByFilename 根据文件名查找已有照片。
func findPhotoByFilename(filename string) *photoInfo {
	photos, _, err := service.ListPhotos(service.ListPhotosParams{Page: 1, PageSize: 1})
	if err != nil {
		return nil
	}

	// 通过文件名精确匹配
	for i := range photos {
		if photos[i].Filename == filename {
			return &photoInfo{
				ID:       photos[i].ID,
				Filename: photos[i].Filename,
				FilePath: photos[i].FilePath,
				ShotAt:   photos[i].ShotAt,
			}
		}
	}

	// 精确查询
	photo, err := service.GetPhotoByFilename(filename)
	if err == nil && photo != nil {
		return &photoInfo{
			ID:       photo.ID,
			Filename: photo.Filename,
			FilePath: photo.FilePath,
			ShotAt:   photo.ShotAt,
		}
	}

	return nil
}

type photoInfo struct {
	ID       string
	Filename string
	FilePath string
	ShotAt   *time.Time
}

// buildConflictInfo 构建冲突响应信息。
func buildConflictInfo(existing *photoInfo, _ string, newShotAt *time.Time) gin.H {
	existingShotAt := ""
	if existing.ShotAt != nil {
		existingShotAt = existing.ShotAt.UTC().Format(time.RFC3339)
	}
	newShotAtStr := ""
	if newShotAt != nil {
		newShotAtStr = newShotAt.UTC().Format(time.RFC3339)
	}

	return gin.H{
		"existing_photo_id":    existing.ID,
		"existing_filename":    existing.Filename,
		"existing_image_url":   fmt.Sprintf("/api/v1/photos/%s/image", existing.ID),
		"existing_shot_at":     existingShotAt,
		"new_shot_at":          newShotAtStr,
	}
}

// updatePhotoAfterOverwrite 覆盖模式：更新已有照片记录。
func updatePhotoAfterOverwrite(photoID, newFilename string, newShotAt *time.Time) {
	cfg := config.Get()
	fullPath := filepath.Join(cfg.Storage.PhotoPath, newFilename)
	exifInfo := service.GetExifInfo(fullPath)
	if exifInfo == nil {
		exifInfo = &service.ExifInfo{}
	}
	if newShotAt != nil {
		exifInfo.ShotAt = newShotAt
	}

	timeline := ""
	if exifInfo.ShotAt != nil {
		timeline = service.FindEventByTime(*exifInfo.ShotAt)
	}

	width, height := service.GetImageSize(fullPath)

	// 更新记录
	updates := map[string]any{
		"description": "", // 覆盖后清空描述，需重新 VLM
	}
	if timeline != "" {
		updates["timeline"] = timeline
	}
	if exifInfo.Brand != "" {
		updates["brand"] = exifInfo.Brand
	}
	if exifInfo.Model != "" {
		updates["model"] = exifInfo.Model
	}
	if exifInfo.Lens != "" {
		updates["lens"] = exifInfo.Lens
	}
	if exifInfo.FocalLength != "" {
		updates["focal_length"] = exifInfo.FocalLength
	}
	if exifInfo.Aperture != "" {
		updates["aperture"] = exifInfo.Aperture
	}
	if exifInfo.ISO != 0 {
		updates["iso"] = exifInfo.ISO
	}
	if exifInfo.ExposureTime != "" {
		updates["exposure_time"] = exifInfo.ExposureTime
	}
	if width > 0 && height > 0 {
		updates["width"] = width
		updates["height"] = height
	}

	db := service.GetDB()
	if err := db.Model(&photoRecord{}).Where("id = ?", photoID).Updates(updates).Error; err != nil {
		plogger.Warnf("Update photo after overwrite failed: %v", err)
	}
}

type photoRecord struct {
	ID string `gorm:"primaryKey"`
}

func (photoRecord) TableName() string {
	return "photos"
}

// addSuffix 在文件名基础部分加序号后缀。
func addSuffix(filename string) string {
	ext := filepath.Ext(filename)
	base := strings.TrimSuffix(filename, ext)
	return fmt.Sprintf("%s-2%s", base, ext)
}

package api

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/service"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/satori/go.uuid"
)

// UploadPhoto 上传图片。
// POST /api/v1/photos/upload
// 表单字段：
//
//	file                压缩后的 JPEG（multipart）
//	original_name        原始文件名
//	original_shot_at     前端读取的 EXIF 拍摄时间（RFC 3339，可选）
//	conflict_resolution  冲突处理策略（可选，"overwrite"|"skip"|"keep_both"）
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
			// 删除旧文件，使用原名存储
			oldPath := filepath.Join(cfg.Storage.PhotoPath, existingPhoto.FilePath)
			_ = os.Remove(oldPath)
			// 更新已有照片记录
			if err := saveUploadedFile(file, targetFilename, cfg); err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
				return
			}
			updatePhotoAfterOverwrite(existingPhoto.ID, targetFilename, newShotAt)
			c.JSON(http.StatusOK, gin.H{"status": "stored", "photo_id": existingPhoto.ID})

		case "skip":
			c.JSON(http.StatusOK, gin.H{"status": "skipped", "photo_id": existingPhoto.ID})

		case "keep_both":
			newFilename := addSuffix(targetFilename)
			if err := saveUploadedFile(file, newFilename, cfg); err != nil {
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

	// 无冲突：直接存储
	if err := saveUploadedFile(file, targetFilename, cfg); err != nil {
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

// saveUploadedFile 将上传的文件内容写入 photo_path。
func saveUploadedFile(src io.Reader, filename string, cfg *config.Config) error {
	targetDir := cfg.Storage.PhotoPath
	if err := os.MkdirAll(targetDir, 0755); err != nil {
		return fmt.Errorf("create photo dir failed: %w", err)
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

// createPhotoFromUpload 为上传的文件创建数据库记录。
// has_description 默认为 false，后续通过 VLM 队列生成。
func createPhotoFromUpload(filename, originalName string, shotAt *time.Time) string {
	if originalName == "" {
		originalName = filename
	}

	// 读取 EXIF（从已存储的文件中）
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
	photo, err := service.SavePhoto(filename, filename, timeline, "", "", width, height, exifInfo)
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
		"existing_photo_id":      existing.ID,
		"existing_filename":      existing.Filename,
		"existing_thumbnail_url": fmt.Sprintf("/api/v1/photos/%s/image?size=thumb", existing.ID),
		"existing_shot_at":       existingShotAt,
		"new_shot_at":            newShotAtStr,
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

package api

import (
	"net/http"
	"os"
	"path/filepath"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/model"
	"github.com/pancake-lee/photo-agent/internal/service"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

// PhotoListItem 照片列表项（含 has_description 计算字段）
type PhotoListItem struct {
	model.Photo
	HasDescription bool   `json:"has_description"`
	ThumbnailURL   string `json:"thumbnail_url"`
}

// photoToListItem 将 Photo 转为列表项
func photoToListItem(p model.Photo) PhotoListItem {
	return PhotoListItem{
		Photo:          p,
		HasDescription: p.Description != "",
		ThumbnailURL:   "/api/v1/photos/" + p.ID + "/image",
	}
}

// PhotoDetailResponse 照片详情（含 has_description 和 description_model）
type PhotoDetailResponse struct {
	model.Photo
	HasDescription  bool   `json:"has_description"`
	ThumbnailURL    string `json:"thumbnail_url"`
	ImageURL        string `json:"image_url"`
	DescriptionModel string `json:"description_model"`
	DescriptionTime  string `json:"description_time"`
}

// ListPhotos 照片列表（分页、过滤）
func ListPhotos(c *gin.Context) {
	page, _ := strconv.Atoi(c.Query("page"))
	pageSize, _ := strconv.Atoi(c.Query("page_size"))
	isoMin, _ := strconv.Atoi(c.Query("iso_min"))
	isoMax, _ := strconv.Atoi(c.Query("iso_max"))
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 20
	}

	params := service.ListPhotosParams{
		Page:        page,
		PageSize:    pageSize,
		Timeline:    c.Query("timeline"),
		Tag:         c.Query("tag"),
		Keyword:     c.Query("keyword"),
		Brand:       c.Query("brand"),
		Lens:        c.Query("lens"),
		FocalMin:    c.Query("focal_min"),
		FocalMax:    c.Query("focal_max"),
		ISOMin:      isoMin,
		ISOMax:      isoMax,
		ShotAtStart:  c.Query("shot_at_start"),
		ShotAtEnd:    c.Query("shot_at_end"),
		SortBy:       c.Query("sort_by"),
		SortOrder:    c.Query("sort_order"),
	}

	photos, total, err := service.ListPhotos(params)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	items := make([]PhotoListItem, len(photos))
	for i, p := range photos {
		items[i] = photoToListItem(p)
	}

	c.JSON(http.StatusOK, gin.H{
		"items":       items,
		"total":       total,
		"page":        page,
		"page_size":   pageSize,
		"total_pages": (int(total) + pageSize - 1) / pageSize,
	})
}

// GetPhotoStats 照片综合统计
func GetPhotoStats(c *gin.Context) {
	stats, err := service.GetPhotoStats()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, stats)
}

// GetPhoto 单张照片详情
func GetPhoto(c *gin.Context) {
	id := c.Param("id")
	photo, err := service.GetPhotoByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "photo not found"})
		return
	}

	// 从 descriptions.json 获取 VLM 模型和时间
	descEntry, _ := service.GetDescriptionEntry(photo.FilePath)

	resp := PhotoDetailResponse{
		Photo:           *photo,
		HasDescription:  photo.Description != "",
		ThumbnailURL:    "/api/v1/photos/" + photo.ID + "/image",
		ImageURL:        "/api/v1/photos/" + photo.ID + "/image",
		DescriptionModel: descEntry.Model,
		DescriptionTime:  descEntry.ProcessedAt,
	}

	c.JSON(http.StatusOK, resp)
}

// UpdatePhotoTags 更新照片结构化标签
func UpdatePhotoTags(c *gin.Context) {
	id := c.Param("id")
	var body struct {
		Tags string `json:"tags"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}

	if err := service.UpdatePhotoTags(id, body.Tags); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

// DeletePhoto 删除照片（含原图文件 + 数据库记录）
func DeletePhoto(c *gin.Context) {
	id := c.Param("id")

	photo, err := service.DeletePhoto(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "photo not found"})
		return
	}

	// 删除磁盘上的原图文件
	cfg := config.Get().Storage
	fullPath := filepath.Join(cfg.PhotoPath, photo.FilePath)
	if err := os.Remove(fullPath); err != nil && !os.IsNotExist(err) {
		plogger.Warnf("Failed to delete photo file %s: %v", fullPath, err)
	}

	c.JSON(http.StatusOK, gin.H{"status": "deleted", "id": id})
}

// GetPhotoImage 获取图片文件。
// 直接返回 photo_path 中的原图，前端通过 CSS object-fit 实现缩略图裁剪效果。
func GetPhotoImage(c *gin.Context) {
	id := c.Param("id")

	photo, err := service.GetPhotoByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "photo not found"})
		return
	}

	photoPath := config.Get().Storage.PhotoPath
	fullPath := filepath.Join(photoPath, photo.FilePath)

	c.File(fullPath)
}

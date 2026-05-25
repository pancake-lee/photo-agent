package api

import (
	"net/http"
	"path/filepath"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/service"
)

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
		Page:     page,
		PageSize: pageSize,
		Timeline: c.Query("timeline"),
		Tag:      c.Query("tag"),
		Keyword:  c.Query("keyword"),
		Brand:    c.Query("brand"),
		Lens:     c.Query("lens"),
		FocalMin: c.Query("focal_min"),
		FocalMax: c.Query("focal_max"),
		ISOMin:   isoMin,
		ISOMax:   isoMax,
	}

	photos, total, err := service.ListPhotos(params)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"items":       photos,
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

	c.JSON(http.StatusOK, photo)
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

// GetPhotoImage 获取图片文件（支持缩略图）
func GetPhotoImage(c *gin.Context) {
	id := c.Param("id")
	size := c.Query("size")

	photo, err := service.GetPhotoByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "photo not found"})
		return
	}

	photoPath := config.Get().Storage.PhotoPath
	fullPath := filepath.Join(photoPath, photo.FilePath)

	// 缩略图模式
	if size == "thumb" {
		thumbPath, err := service.GetThumbnail(fullPath)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "generate thumbnail failed: " + err.Error()})
			return
		}
		c.File(thumbPath)
		return
	}

	c.File(fullPath)
}

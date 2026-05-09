package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/service"
)

// ListPhotos 照片列表（分页、过滤）
func ListPhotos(c *gin.Context) {
	timeline := c.Query("timeline")
	tag := c.Query("tag")
	keyword := c.Query("keyword")
	_ = timeline
	_ = tag
	_ = keyword

	// TODO: Day 2 实现分页和过滤
	c.JSON(http.StatusOK, gin.H{
		"items": []any{},
		"total": 0,
	})
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

// GetPhotoImage 获取图片文件（支持缩略图）
func GetPhotoImage(c *gin.Context) {
	id := c.Param("id")
	size := c.Query("size")
	_ = size

	photo, err := service.GetPhotoByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "photo not found"})
		return
	}

	// TODO: Day 2 实现缩略图
	c.JSON(http.StatusNotImplemented, gin.H{"error": "not implemented", "photo_id": photo.ID})
}

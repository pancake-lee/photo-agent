package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/service"
)

// ListTags 所有标签列表
func ListTags(c *gin.Context) {
	tags, err := service.ListDistinctTags()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, tags)
}

// GetPhotosByTag 某标签下的照片
func GetPhotosByTag(c *gin.Context) {
	name := c.Param("name")

	photos, err := service.GetPhotosByTag(name)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"tag":   name,
		"items": photos,
		"total": len(photos),
	})
}

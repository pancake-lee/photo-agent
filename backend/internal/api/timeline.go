package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/service"
)

// ListTimelines 所有时间线列表
func ListTimelines(c *gin.Context) {
	timelines, err := service.ListDistinctTimelines()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, timelines)
}

// GetPhotosByTimeline 某时间线下的照片
func GetPhotosByTimeline(c *gin.Context) {
	name := c.Param("name")

	photos, err := service.GetPhotosByTimeline(name)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"timeline": name,
		"items":    photos,
		"total":    len(photos),
	})
}

package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// ListTimelines 所有时间线列表
func ListTimelines(c *gin.Context) {
	// TODO: Day 2 实现
	c.JSON(http.StatusOK, []string{})
}

// GetPhotosByTimeline 某时间线下的照片
func GetPhotosByTimeline(c *gin.Context) {
	name := c.Param("name")
	_ = name
	// TODO: Day 2 实现
	c.JSON(http.StatusOK, gin.H{
		"timeline": name,
		"items":    []any{},
	})
}

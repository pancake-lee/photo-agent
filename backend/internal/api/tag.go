package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// ListTags 所有标签列表
func ListTags(c *gin.Context) {
	// TODO: Day 2 实现
	c.JSON(http.StatusOK, []string{})
}

// GetPhotosByTag 某标签下的照片
func GetPhotosByTag(c *gin.Context) {
	name := c.Param("name")
	_ = name
	// TODO: Day 2 实现
	c.JSON(http.StatusOK, gin.H{
		"tag":   name,
		"items": []any{},
	})
}

package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// HealthCheck 健康检查接口
func HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status": "ok",
	})
}

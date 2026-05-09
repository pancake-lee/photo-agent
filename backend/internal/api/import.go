package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/service"
)

// CreateImportJobRequest 创建导入任务请求
type CreateImportJobRequest struct {
	SourcePath string `json:"sourcePath" binding:"required"`
	Recursive  bool   `json:"recursive"`
}

// CreateImportJob 创建导入任务
func CreateImportJob(c *gin.Context) {
	var req CreateImportJobRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	job, err := service.CreateImportJob(req.SourcePath, req.Recursive)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, job)
}

// GetImportJob 查询导入任务
func GetImportJob(c *gin.Context) {
	id := c.Param("id")
	job, err := service.GetImportJob(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "job not found"})
		return
	}

	c.JSON(http.StatusOK, job)
}

// GetImportJobLogs 查询导入任务日志
func GetImportJobLogs(c *gin.Context) {
	id := c.Param("id")
	job, err := service.GetImportJob(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "job not found"})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"job_id": id,
		"log":    job.Log,
	})
}

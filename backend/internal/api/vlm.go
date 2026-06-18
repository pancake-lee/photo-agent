package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/service"
)

// StartVlmQueue 启动 VLM 队列处理（全局开关）。
// POST /api/v1/vlm/queue/start
func StartVlmQueue(c *gin.Context) {
	var body struct {
		Force bool `json:"force"`
	}
	_ = c.ShouldBindJSON(&body)

	var photoIDs []string
	var err error

	if body.Force {
		// Force 模式：查询所有照片（含已有描述的）
		photoIDs, err = service.GetAllPhotoIDs()
	} else {
		// 默认：仅查询无描述的照片
		photoIDs, err = service.GetUndescribedPhotoIDs()
	}

	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	if len(photoIDs) == 0 {
		c.JSON(http.StatusOK, gin.H{
			"task_id": "",
			"total":   0,
			"message": "no photos to process",
		})
		return
	}

	q := service.GetVlmQueue()
	taskID, err := q.Start(photoIDs)
	if err != nil {
		c.JSON(http.StatusConflict, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"task_id": taskID,
		"total":   len(photoIDs),
	})
}

// StopVlmQueue 中止 VLM 队列处理。
// POST /api/v1/vlm/queue/stop
func StopVlmQueue(c *gin.Context) {
	q := service.GetVlmQueue()
	q.Stop()
	c.JSON(http.StatusOK, gin.H{"stopped": true})
}

// GetVlmQueueStatus 查询 VLM 队列状态。
// GET /api/v1/vlm/queue/status
func GetVlmQueueStatus(c *gin.Context) {
	q := service.GetVlmQueue()
	status := q.Status()
	c.JSON(http.StatusOK, status)
}

// DescribePhoto 单张照片触发 VLM 描述。
// POST /api/v1/photos/:id/describe
func DescribePhoto(c *gin.Context) {
	photoID := c.Param("id")

	// 验证照片存在
	_, err := service.GetPhotoByID(photoID)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "photo not found"})
		return
	}

	q := service.GetVlmQueue()
	if err := q.Enqueue(photoID); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"queued": true})
}

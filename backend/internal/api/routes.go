package api

import (
	"github.com/gin-gonic/gin"
)

// SetupRoutes 配置所有路由
func SetupRoutes(r *gin.Engine) {
	api := r.Group("/api")
	{
		api.GET("/health", HealthCheck)

		// 照片管理
		api.GET("/photos", ListPhotos)
		api.GET("/photos/stats", GetPhotoStats)
		api.GET("/photos/:id", GetPhoto)
		api.GET("/photos/:id/image", GetPhotoImage)

		// 时间线
		api.GET("/timelines", ListTimelines)
		api.GET("/timelines/:name/photos", GetPhotosByTimeline)

		// 标签
		api.GET("/tags", ListTags)
		api.GET("/tags/:name/photos", GetPhotosByTag)

		// 导入任务
		api.POST("/import/jobs", CreateImportJob)
		api.GET("/import/jobs/:id", GetImportJob)
		api.GET("/import/jobs/:id/logs", GetImportJobLogs)
	}
}

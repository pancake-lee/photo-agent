package api

import (
	"github.com/gin-gonic/gin"
)

// SetupRoutes 配置所有路由
func SetupRoutes(r *gin.Engine) {
	// v1 API 路由
	setupV1Routes(r.Group("/api/v1"))

	// OpenAPI 文档
	r.GET("/v1/openapi.json", OpenAPIDoc)
}

// setupV1Routes 注册 v1 版本业务路由
func setupV1Routes(api *gin.RouterGroup) {
	api.GET("/health", HealthCheck)

	// 照片管理
	api.GET("/photos", ListPhotos)
	api.GET("/photos/stats", GetPhotoStats)
	api.GET("/photos/:id", GetPhoto)
	api.GET("/photos/:id/image", GetPhotoImage)
	api.PUT("/photos/:id/tags", UpdatePhotoTags)
	api.DELETE("/photos/:id", DeletePhoto)

	// 照片上传
	api.POST("/photos/upload", UploadPhoto)

	// VLM 队列控制
	vlmGroup := api.Group("/vlm/queue")
	{
		vlmGroup.POST("/start", StartVlmQueue)
		vlmGroup.POST("/stop", StopVlmQueue)
		vlmGroup.GET("/status", GetVlmQueueStatus)
	}

	// 单张 VLM 描述
	api.POST("/photos/:id/describe", DescribePhoto)

	// 通用 SQL 查询
	api.POST("/query/sql", ExecuteSQL)

	// 表结构 & 属性值
	api.GET("/schema/photos", GetPhotoSchema)
	api.GET("/photos/attribute-values", GetAttributeValues)

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

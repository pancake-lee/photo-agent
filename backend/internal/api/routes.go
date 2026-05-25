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

	// 通用 SQL 查询
	api.POST("/query/sql", ExecuteSQL)

	// 表结构
	api.GET("/schema/photos", GetPhotoSchema)

	// 时间线
	api.GET("/timelines", ListTimelines)
	api.GET("/timelines/:name/photos", GetPhotosByTimeline)

	// 标签
	api.GET("/tags", ListTags)
	api.GET("/tags/:name/photos", GetPhotosByTag)

	// 导入任务
	// TODO 这个“导入”，其实是指定一个目录，然后做一遍batch_vlm的事情
	// 但这是重复的代码，而且这里的版本有些问题
	// 又考虑到这个“batch_vlm”放在service也合适，
	// 可以编程在聊天中去触发这个工作，也可以配套一个Cli或者管理后台来处理
	// 所以先留下接口，但是后面和batch_vlm的逻辑代码肯定是要合并的
	api.POST("/import/jobs", CreateImportJob)
	api.GET("/import/jobs/:id", GetImportJob)
	api.GET("/import/jobs/:id/logs", GetImportJobLogs)
}

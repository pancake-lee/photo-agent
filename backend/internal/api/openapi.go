package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// OpenAPIDoc 返回手写的 OpenAPI 3.0 文档，描述 Go 后端所有可用接口。
// 供 Python AI Service 自动解析，转换为 LLM Function Calling 可用的工具定义。
func OpenAPIDoc(c *gin.Context) {
	doc := gin.H{
		"openapi": "3.0.3",
		"info": gin.H{
			"title":       "Photo Agent API",
			"version":     "1.0.0",
			"description": "照片管理后端接口，支持照片查询、统计、SQL 查询、导入任务管理",
		},
		"servers": []gin.H{
			{"url": "/api/v1", "description": "业务 API v1"},
		},
		"paths": gin.H{
			"/photos": gin.H{
				"get": gin.H{
					"summary":     "照片列表",
					"description": "分页查询照片，支持多种过滤条件。",
					"parameters": []gin.H{
						{"name": "page", "in": "query", "schema": gin.H{"type": "integer", "default": 1}, "description": "页码"},
						{"name": "page_size", "in": "query", "schema": gin.H{"type": "integer", "default": 20}, "description": "每页数量"},
						{"name": "keyword", "in": "query", "schema": gin.H{"type": "string"}, "description": "关键词过滤（描述 LIKE）"},
						{"name": "brand", "in": "query", "schema": gin.H{"type": "string"}, "description": "相机品牌"},
						{"name": "lens", "in": "query", "schema": gin.H{"type": "string"}, "description": "镜头（LIKE）"},
						{"name": "focal_min", "in": "query", "schema": gin.H{"type": "string"}, "description": "焦距下限（mm）"},
						{"name": "focal_max", "in": "query", "schema": gin.H{"type": "string"}, "description": "焦距上限（mm）"},
						{"name": "iso_min", "in": "query", "schema": gin.H{"type": "integer"}, "description": "ISO 下限"},
						{"name": "iso_max", "in": "query", "schema": gin.H{"type": "integer"}, "description": "ISO 上限"},
						{"name": "timeline", "in": "query", "schema": gin.H{"type": "string"}, "description": "时间线过滤"},
						{"name": "tag", "in": "query", "schema": gin.H{"type": "string"}, "description": "标签过滤"},
					},
					"responses": gin.H{
						"200": gin.H{
							"description": "照片列表",
							"content": gin.H{
								"application/json": gin.H{
									"schema": gin.H{
										"type": "object",
										"properties": gin.H{
											"items":  gin.H{"type": "array", "description": "照片列表"},
											"total":  gin.H{"type": "integer"},
											"page":   gin.H{"type": "integer"},
											"page_size":   gin.H{"type": "integer"},
											"total_pages": gin.H{"type": "integer"},
										},
									},
								},
							},
						},
					},
				},
			},
			"/photos/stats": gin.H{
				"get": gin.H{
					"summary":     "照片综合统计",
					"description": "返回总数量、品牌分布、镜头分布、焦距段、GPS、月度、时段七维度统计。",
					"responses": gin.H{
						"200": gin.H{"description": "统计结果"},
					},
				},
			},
			"/photos/{id}": gin.H{
				"get": gin.H{
					"summary":     "单张照片详情",
					"description": "根据 ID 获取照片完整元数据。",
					"parameters": []gin.H{
						{"name": "id", "in": "path", "required": true, "schema": gin.H{"type": "string"}, "description": "照片 ID"},
					},
					"responses": gin.H{
						"200": gin.H{"description": "照片详情"},
						"404": gin.H{"description": "照片不存在"},
					},
				},
			},
			"/query/sql": gin.H{
				"post": gin.H{
					"summary":     "SQL 查询",
					"description": "执行 SELECT SQL 查询，仅允许 SELECT 语句。",
					"requestBody": gin.H{
						"required": true,
						"content": gin.H{
							"application/json": gin.H{
								"schema": gin.H{
									"type": "object",
									"properties": gin.H{
										"sql": gin.H{"type": "string", "description": "SELECT SQL 语句"},
									},
									"required": []string{"sql"},
								},
							},
						},
					},
					"responses": gin.H{
						"200": gin.H{"description": "查询结果"},
					},
				},
			},
			"/schema/photos": gin.H{
				"get": gin.H{
					"summary":     "photos 表结构",
					"description": "返回 photos 表的字段结构信息，用于 Text-to-SQL 生成。",
					"responses": gin.H{
						"200": gin.H{"description": "表结构"},
					},
				},
			},
			"/timelines": gin.H{
				"get": gin.H{
					"summary":     "时间线列表",
					"description": "返回所有不重复的时间线名称。",
					"responses": gin.H{
						"200": gin.H{"description": "时间线列表"},
					},
				},
			},
			"/timelines/{name}/photos": gin.H{
				"get": gin.H{
					"summary":     "时间线下的照片",
					"description": "获取指定时间线下的所有照片。",
					"parameters": []gin.H{
						{"name": "name", "in": "path", "required": true, "schema": gin.H{"type": "string"}, "description": "时间线名称"},
					},
					"responses": gin.H{
						"200": gin.H{"description": "照片列表"},
					},
				},
			},
			"/tags": gin.H{
				"get": gin.H{
					"summary":     "标签列表",
					"description": "返回所有不重复的标签。",
					"responses": gin.H{
						"200": gin.H{"description": "标签列表"},
					},
				},
			},
			"/tags/{name}/photos": gin.H{
				"get": gin.H{
					"summary":     "标签下的照片",
					"description": "获取指定标签下的所有照片。",
					"parameters": []gin.H{
						{"name": "name", "in": "path", "required": true, "schema": gin.H{"type": "string"}, "description": "标签名称"},
					},
					"responses": gin.H{
						"200": gin.H{"description": "照片列表"},
					},
				},
			},
			"/import/jobs": gin.H{
				"post": gin.H{
					"summary":     "创建导入任务",
					"description": "批量导入指定目录下的照片。",
					"requestBody": gin.H{
						"required": true,
						"content": gin.H{
							"application/json": gin.H{
								"schema": gin.H{
									"type": "object",
									"properties": gin.H{
										"source_path": gin.H{"type": "string", "description": "源目录路径"},
										"recursive":   gin.H{"type": "boolean", "description": "是否递归子目录"},
									},
									"required": []string{"source_path"},
								},
							},
						},
					},
					"responses": gin.H{
						"200": gin.H{"description": "导入任务"},
					},
				},
			},
		},
	}
	c.JSON(http.StatusOK, doc)
}

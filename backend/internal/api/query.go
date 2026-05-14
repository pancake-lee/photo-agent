package api

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/service"
)

// SQLQueryRequest SQL 查询请求。
type SQLQueryRequest struct {
	SQL string `json:"sql" binding:"required"`
}

// SQLQueryResponse SQL 查询响应。
type SQLQueryResponse struct {
	Columns []string                 `json:"columns"`
	Rows    []map[string]interface{} `json:"rows"`
	Count   int                      `json:"count"`
}

// ExecuteSQL 执行 SELECT SQL 查询。
//
// POST /api/query/sql
// Request: { "sql": "SELECT * FROM photos WHERE brand = 'NIKON' LIMIT 20" }
// Response: { "columns": [...], "rows": [...], "count": 5 }
func ExecuteSQL(c *gin.Context) {
	var req SQLQueryRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request: " + err.Error()})
		return
	}

	// 默认限制 100 条
	limitStr := c.DefaultQuery("limit", "100")
	limit, err := strconv.Atoi(limitStr)
	if err != nil || limit < 1 {
		limit = 100
	}
	if limit > 1000 {
		limit = 1000
	}

	result, err := service.ExecuteSelectSQL(req.SQL, limit)
	if err != nil {
		// 安全校验失败返回 400，执行错误返回 500
		status := http.StatusInternalServerError
		if service.ValidateSelectOnly(req.SQL) != nil {
			status = http.StatusBadRequest
		}
		c.JSON(status, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, result)
}

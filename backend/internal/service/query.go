package service

import (
	"fmt"
	"regexp"
	"strings"
)

// forbiddenKeywords 禁止出现在 SQL 中的危险关键字。
var forbiddenKeywords = []string{
	"INSERT", "UPDATE", "DELETE",
	"DROP", "CREATE", "ALTER", "TRUNCATE", "REPLACE",
	"ATTACH", "DETACH", "PRAGMA",
}

// forbiddenRegexps 预编译的危险关键字正则（全词匹配）。
var forbiddenRegexps []*regexp.Regexp

func init() {
	for _, kw := range forbiddenKeywords {
		forbiddenRegexps = append(
			forbiddenRegexps,
			regexp.MustCompile(`\b`+regexp.QuoteMeta(kw)+`\b`),
		)
	}
}

// ValidateSelectOnly 校验 SQL 是否仅为 SELECT 查询。
// 返回 nil 表示安全，否则返回错误原因。
func ValidateSelectOnly(sqlStr string) error {
	if strings.TrimSpace(sqlStr) == "" {
		return fmt.Errorf("SQL 为空")
	}

	// 提取第一行有效语句（跳过注释和空行）
	lines := strings.Split(sqlStr, "\n")
	var firstLine string
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		// 去除行注释 --
		if idx := strings.Index(line, "--"); idx != -1 {
			line = strings.TrimSpace(line[:idx])
		}
		if line != "" {
			firstLine = line
			break
		}
	}

	// 去除块注释前缀 /* ... */
	for strings.HasPrefix(firstLine, "/*") {
		end := strings.Index(firstLine, "*/")
		if end == -1 {
			return fmt.Errorf("未闭合的块注释")
		}
		firstLine = strings.TrimSpace(firstLine[end+2:])
	}

	// 必须以 SELECT 开头（不区分大小写）
	upper := strings.ToUpper(firstLine)
	if !strings.HasPrefix(upper, "SELECT") {
		return fmt.Errorf("SQL 必须以 SELECT 开头")
	}

	// 全文扫描禁止危险关键字
	upperSQL := strings.ToUpper(sqlStr)
	for _, re := range forbiddenRegexps {
		if re.MatchString(upperSQL) {
			matched := re.FindString(upperSQL)
			return fmt.Errorf("禁止的危险关键字: %s", matched)
		}
	}

	return nil
}

// QueryResult SQL 查询结果。
type QueryResult struct {
	Columns []string                 `json:"columns"`
	Rows    []map[string]interface{} `json:"rows"`
	Count   int                      `json:"count"`
}

// ExecuteSelectSQL 安全执行 SELECT 查询。
func ExecuteSelectSQL(sqlStr string, limit int) (*QueryResult, error) {
	if err := ValidateSelectOnly(sqlStr); err != nil {
		return nil, err
	}

	// 获取底层 *sql.DB
	sqlDB, err := GetDB().DB()
	if err != nil {
		return nil, fmt.Errorf("get underlying db failed: %w", err)
	}

	rows, err := sqlDB.Query(sqlStr)
	if err != nil {
		return nil, fmt.Errorf("execute query failed: %w", err)
	}
	defer rows.Close()

	// 获取列名
	columns, err := rows.Columns()
	if err != nil {
		return nil, fmt.Errorf("get columns failed: %w", err)
	}

	// 扫描结果
	var resultRows []map[string]interface{}
	count := 0
	for rows.Next() {
		if count >= limit {
			break
		}

		// 创建值接收器
		values := make([]interface{}, len(columns))
		valuePtrs := make([]interface{}, len(columns))
		for i := range values {
			valuePtrs[i] = &values[i]
		}

		if err := rows.Scan(valuePtrs...); err != nil {
			return nil, fmt.Errorf("scan row failed: %w", err)
		}

		rowMap := make(map[string]interface{})
		for i, col := range columns {
			rowMap[col] = values[i]
		}
		resultRows = append(resultRows, rowMap)
		count++
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate rows failed: %w", err)
	}

	return &QueryResult{
		Columns: columns,
		Rows:    resultRows,
		Count:   count,
	}, nil
}

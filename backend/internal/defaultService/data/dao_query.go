package data

import (
	"fmt"
	"reflect"
	"strings"
	"time"

	"backend/internal/pkg/db"
	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"gorm.io/gen/field"
)

// SQLQueryResult 是只读 SQL 查询的原始结果，供 Service 转换为 API 响应。
type SQLQueryResult struct {
	Columns []string
	Rows    []map[string]any
}

// ExecuteReadOnlySQL 用只读连接执行已由 Service 校验过的查询，并限制返回行数。
func ExecuteReadOnlySQL(ctx *papp.AppCtx, sql string, limit int) (*SQLQueryResult, error) {
	sqlDB, err := pdb.GetDB_RO()
	if err != nil {
		return nil, fmt.Errorf("get read-only db failed: %w", err)
	}
	rows, err := sqlDB.QueryContext(ctx, sql)
	if err != nil {
		return nil, fmt.Errorf("execute query failed: %w", err)
	}
	defer rows.Close()

	columns, err := rows.Columns()
	if err != nil {
		return nil, fmt.Errorf("get columns failed: %w", err)
	}
	result := &SQLQueryResult{Columns: columns, Rows: make([]map[string]any, 0)}
	for rows.Next() {
		if len(result.Rows) >= limit {
			break
		}
		values := make([]any, len(columns))
		valuePtrs := make([]any, len(columns))
		for i := range values {
			valuePtrs[i] = &values[i]
		}
		if err := rows.Scan(valuePtrs...); err != nil {
			return nil, fmt.Errorf("scan row failed: %w", err)
		}
		rowMap := make(map[string]any, len(columns))
		for i, column := range columns {
			rowMap[column] = normalizeSQLValue(values[i])
		}
		result.Rows = append(result.Rows, rowMap)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate rows failed: %w", err)
	}
	return result, nil
}

// PhotoSchemaField 描述 photos 表模型中一个可导出的字段。
type PhotoSchemaField struct {
	Name     string
	GoType   string
	SQLType  string
	JSONTag  string
	GORMTag  string
	Nullable bool
}

// GetPhotoSchema 返回 photos 模型的字段定义。
func GetPhotoSchema() []PhotoSchemaField {
	typ := reflect.TypeOf(model.Photo{})
	fields := make([]PhotoSchemaField, 0, typ.NumField())
	for i := 0; i < typ.NumField(); i++ {
		field := typ.Field(i)
		if !field.IsExported() {
			continue
		}
		fields = append(fields, PhotoSchemaField{
			Name: field.Name, GoType: field.Type.String(), SQLType: goTypeToSQLType(field.Type),
			JSONTag: field.Tag.Get("json"), GORMTag: field.Tag.Get("gorm"), Nullable: field.Type.Kind() == reflect.Ptr,
		})
	}
	return fields
}

func normalizeSQLValue(value any) any {
	switch v := value.(type) {
	case []byte:
		return string(v)
	case time.Time:
		return v.Format(time.RFC3339)
	default:
		return value
	}
}

func goTypeToSQLType(t reflect.Type) string {
	switch t.Kind() {
	case reflect.String:
		return "TEXT"
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64,
		reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		return "INTEGER"
	case reflect.Float32, reflect.Float64:
		return "REAL"
	case reflect.Ptr:
		return goTypeToSQLType(t.Elem())
	default:
		return "TEXT"
	}
}

// AttributeValuesDTO 结构化属性的去重值集合，供 Text-to-SQL prompt 动态拼入。
type AttributeValuesDTO struct {
	Objects     []string
	Colors      []string
	Scene       []string
	Lighting    []string
	Mood        []string
	Composition []string
}

// GetDistinctAttributeValues 查询所有结构化属性的去重值。
//
// 字段分类硬编码在 DAO 层：
//   - 单值字段：scene, lighting, mood，直接 SELECT DISTINCT 即可
//   - 多值字段：objects, colors, composition，逗号分隔，需拆分后去重
func GetDistinctAttributeValues(ctx *papp.AppCtx) (*AttributeValuesDTO, error) {
	p := db.GetQuery().Photo // gen 生成的类型安全字段表达式
	result := &AttributeValuesDTO{}

	// 单值字段
	err := p.WithContext(ctx).Where(p.Scene.Neq("")).Distinct().Pluck(p.Scene, &result.Scene)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	err = p.WithContext(ctx).Where(p.Lighting.Neq("")).Distinct().Pluck(p.Lighting, &result.Lighting)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	err = p.WithContext(ctx).Where(p.Mood.Neq("")).Distinct().Pluck(p.Mood, &result.Mood)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 逗号分隔多值字段
	result.Objects = pluckDistinctMulti(ctx, p.Objects)
	result.Colors = pluckDistinctMulti(ctx, p.Colors)
	result.Composition = pluckDistinctMulti(ctx, p.Composition)

	return result, nil
}

// pluckDistinctMulti 查询逗号分隔字段的拆分去重值。
// objects/colors/composition 是逗号分隔的多值字段，返回拆分后的独立值。
func pluckDistinctMulti(ctx *papp.AppCtx, col field.String) []string {
	q := db.GetQuery().Photo
	var rows []string
	err := q.WithContext(ctx).Where(col.Neq("")).Distinct().Pluck(col, &rows)
	if err != nil {
		ctx.Log.Warnf("pluckDistinctMulti: %v", err)
		return nil
	}

	seen := make(map[string]struct{})
	result := make([]string, 0)
	for _, r := range rows {
		for _, part := range strings.Split(r, ",") {
			part = strings.TrimSpace(part)
			if part == "" {
				continue
			}
			_, ok := seen[part]
			if !ok {
				seen[part] = struct{}{}
				result = append(result, part)
			}
		}
	}
	return result
}

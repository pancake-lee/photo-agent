package api

import (
	"net/http"
	"reflect"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/model"
)

// SchemaField 字段定义。
type SchemaField struct {
	Name     string `json:"name"`
	GoType   string `json:"go_type"`
	SQLType  string `json:"sql_type"`
	JSONTag  string `json:"json_tag"`
	GORMTag  string `json:"gorm_tag"`
	Nullable bool   `json:"nullable"`
}

// TableSchema 表结构定义。
type TableSchema struct {
	TableName string        `json:"table_name"`
	Fields    []SchemaField `json:"fields"`
	Notes     []string      `json:"notes"`
}

// goTypeToSQLType 将 Go 反射类型映射为 SQLite 类型。
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

// isNullable 判断类型是否为可空（指针类型）。
func isNullable(t reflect.Type) bool {
	return t.Kind() == reflect.Ptr
}

// buildPhotoSchema 通过反射从 model.Photo 构建表结构。
func buildPhotoSchema() *TableSchema {
	schema := &TableSchema{
		TableName: "photos",
		Fields:    make([]SchemaField, 0),
	}

	typ := reflect.TypeOf(model.Photo{})
	for i := 0; i < typ.NumField(); i++ {
		field := typ.Field(i)

		// 跳过未导出字段
		if !field.IsExported() {
			continue
		}

		schema.Fields = append(schema.Fields, SchemaField{
			Name:     field.Name,
			GoType:   field.Type.String(),
			SQLType:  goTypeToSQLType(field.Type),
			JSONTag:  field.Tag.Get("json"),
			GORMTag:  field.Tag.Get("gorm"),
			Nullable: isNullable(field.Type),
		})
	}

	schema.Notes = []string{
		"tags 是 JSON 字符串，用 LIKE '%\"风景\"%' 进行标签匹配",
		"focal_length 存储为 \"35mm\" 文本格式，数值比较需先去除 \"mm\"",
		"shot_at 和 imported_at 是 ISO8601 格式，可用 strftime 提取年月",
		"brand 字段可能为空字符串",
		"经纬度(latitude/longitude/altitude)为 NULL 表示无 GPS 信息",
	}

	return schema
}

// GetPhotoSchema 返回 photos 表结构。
//
// GET /api/schema/photos
func GetPhotoSchema(c *gin.Context) {
	schema := buildPhotoSchema()
	c.JSON(http.StatusOK, schema)
}

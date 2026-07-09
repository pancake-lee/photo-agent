package service

import (
	"context"
	"fmt"
	"reflect"
	"strings"
	"time"

	"backend-new/internal/defaultService/data"
	"backend-new/internal/pkg/api"
	"backend-new/internal/pkg/db/model"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"google.golang.org/protobuf/types/known/structpb"
)

// QueryServer 通用查询服务（SQL 查询 + 表结构 + 属性值）
type QueryServer struct {
	api.UnimplementedQueryServiceServer
}

func (s *QueryServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if grpcSrv != nil {
		api.RegisterQueryServiceServer(grpcSrv, s)
	}
	if httpSrv != nil {
		api.RegisterQueryServiceHTTPServer(httpSrv, s)
	}
}

// ================================================================
// ExecuteSQL
// ================================================================

// ExecuteSQL 执行 SELECT 查询。通过只读数据库连接执行，SQLite 内核层面拒绝任何写操作。
func (s *QueryServer) ExecuteSQL(_ctx context.Context, req *api.ExecuteSQLRequest) (*api.ExecuteSQLResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	if strings.TrimSpace(req.Sql) == "" {
		return nil, ctx.Log.LogErr(fmt.Errorf("SQL 为空"))
	}

	limit := int(req.Limit)
	if limit <= 0 {
		limit = 100
	}
	if limit > 1000 {
		limit = 1000
	}

	sqlDB, err := pdb.GetDB_RO()
	if err != nil {
		return nil, ctx.Log.LogErr(fmt.Errorf("get read-only db failed: %w", err))
	}

	rows, err := sqlDB.Query(req.Sql)
	if err != nil {
		return nil, ctx.Log.LogErr(fmt.Errorf("execute query failed: %w", err))
	}
	defer rows.Close()

	columns, err := rows.Columns()
	if err != nil {
		return nil, ctx.Log.LogErr(fmt.Errorf("get columns failed: %w", err))
	}

	var resultRows []*structpb.Struct
	count := int32(0)
	for rows.Next() {
		if count >= int32(limit) {
			break
		}

		values := make([]interface{}, len(columns))
		valuePtrs := make([]interface{}, len(columns))
		for i := range values {
			valuePtrs[i] = &values[i]
		}

		if err := rows.Scan(valuePtrs...); err != nil {
			return nil, ctx.Log.LogErr(fmt.Errorf("scan row failed: %w", err))
		}

		rowMap := make(map[string]interface{}, len(columns))
		for i, col := range columns {
			rowMap[col] = normalizeSQLValue(values[i])
		}

		st, err := structpb.NewStruct(rowMap)
		if err != nil {
			return nil, ctx.Log.LogErr(fmt.Errorf("convert row to struct failed: %w", err))
		}
		resultRows = append(resultRows, st)
		count++
	}

	if err := rows.Err(); err != nil {
		return nil, ctx.Log.LogErr(fmt.Errorf("iterate rows failed: %w", err))
	}

	return &api.ExecuteSQLResponse{
		Columns: columns,
		Rows:    resultRows,
		Count:   count,
	}, nil
}

// TODO 应该由pgo.pdb提供
// normalizeSQLValue 将 SQL 扫描值转换为 structpb.NewValue 可接受的类型。
// database/sql 扫描到 interface{} 时，[]byte 和 time.Time 需要显式转换。
func normalizeSQLValue(v interface{}) interface{} {
	switch val := v.(type) {
	case []byte:
		return string(val)
	case time.Time:
		return val.Format(time.RFC3339)
	default:
		return v
	}
}

// ================================================================
// GetPhotoSchema
// ================================================================

// TODO 应该由pgo.pdb提供
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

func (s *QueryServer) GetPhotoSchema(_ctx context.Context, _ *api.Empty) (*api.GetPhotoSchemaResponse, error) {
	typ := reflect.TypeOf(model.Photo{})
	fields := make([]*api.SchemaField, 0, typ.NumField())

	for i := 0; i < typ.NumField(); i++ {
		field := typ.Field(i)
		if !field.IsExported() {
			continue
		}

		fields = append(fields, &api.SchemaField{
			Name:     field.Name,
			GoType:   field.Type.String(),
			SqlType:  goTypeToSQLType(field.Type),
			JsonTag:  field.Tag.Get("json"),
			GormTag:  field.Tag.Get("gorm"),
			Nullable: field.Type.Kind() == reflect.Ptr,
		})
	}

	return &api.GetPhotoSchemaResponse{
		TableName: "photos",
		Fields:    fields,
	}, nil
}

// ================================================================
// GetAttributeValues
// ================================================================

func (s *QueryServer) GetAttributeValues(_ctx context.Context, _ *api.Empty) (*api.GetAttributeValuesResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	dto, err := data.GetDistinctAttributeValues(ctx)
	if err != nil {
		return nil, err // DAO 层已打日志
	}

	return &api.GetAttributeValuesResponse{
		Values: &api.AttributeValues{
			Objects:     dto.Objects,
			Colors:      dto.Colors,
			Scene:       dto.Scene,
			Lighting:    dto.Lighting,
			Mood:        dto.Mood,
			Composition: dto.Composition,
		},
	}, nil
}

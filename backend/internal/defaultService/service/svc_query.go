package service

import (
	"context"
	"fmt"
	"strings"

	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
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

	result, err := data.ExecuteReadOnlySQL(ctx, req.Sql, limit)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	var resultRows []*structpb.Struct
	for _, rowMap := range result.Rows {
		st, err := structpb.NewStruct(rowMap)
		if err != nil {
			return nil, ctx.Log.LogErr(fmt.Errorf("convert row to struct failed: %w", err))
		}
		resultRows = append(resultRows, st)
	}

	return &api.ExecuteSQLResponse{
		Columns: result.Columns,
		Rows:    resultRows,
		Count:   int32(len(resultRows)),
	}, nil
}

// ================================================================
// GetPhotoSchema
// ================================================================

func (s *QueryServer) GetPhotoSchema(_ctx context.Context, _ *api.Empty) (*api.GetPhotoSchemaResponse, error) {
	schemaFields := data.GetPhotoSchema()
	fields := make([]*api.SchemaField, 0, len(schemaFields))
	for _, field := range schemaFields {
		fields = append(fields, &api.SchemaField{
			Name: field.Name, GoType: field.GoType, SqlType: field.SQLType,
			JsonTag: field.JSONTag, GormTag: field.GORMTag, Nullable: field.Nullable,
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

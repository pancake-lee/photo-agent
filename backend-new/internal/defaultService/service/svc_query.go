package service

import (
	"context"

	"backend-new/internal/pkg/api"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

// QueryServer 通用查询服务（脚手架，业务逻辑待迁移）
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

func (s *QueryServer) ExecuteSQL(_ctx context.Context, req *api.ExecuteSQLRequest) (*api.ExecuteSQLResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.ExecuteSQLResponse{}, nil
}

func (s *QueryServer) GetPhotoSchema(_ctx context.Context, _ *api.Empty) (*api.GetPhotoSchemaResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.GetPhotoSchemaResponse{}, nil
}

func (s *QueryServer) GetAttributeValues(_ctx context.Context, _ *api.Empty) (*api.GetAttributeValuesResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.GetAttributeValuesResponse{}, nil
}

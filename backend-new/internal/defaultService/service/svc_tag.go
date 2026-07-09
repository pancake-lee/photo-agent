package service

import (
	"context"

	"backend-new/internal/pkg/api"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

// TagServer 标签服务（脚手架，业务逻辑待迁移）
type TagServer struct {
	api.UnimplementedTagServiceServer
}

func (s *TagServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if grpcSrv != nil {
		api.RegisterTagServiceServer(grpcSrv, s)
	}
	if httpSrv != nil {
		api.RegisterTagServiceHTTPServer(httpSrv, s)
	}
}

func (s *TagServer) ListTags(_ctx context.Context, _ *api.Empty) (*api.ListTagsResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.ListTagsResponse{}, nil
}

func (s *TagServer) GetPhotosByTag(_ctx context.Context, req *api.GetPhotosByTagRequest) (*api.GetPhotosByTagResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.GetPhotosByTagResponse{Tag: req.Name}, nil
}

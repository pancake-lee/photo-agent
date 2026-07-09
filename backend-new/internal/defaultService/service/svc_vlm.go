package service

import (
	"context"

	"backend-new/internal/pkg/api"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

// VlmServer VLM 队列服务（脚手架，业务逻辑待迁移）
type VlmServer struct {
	api.UnimplementedVlmServiceServer
}

func (s *VlmServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if grpcSrv != nil {
		api.RegisterVlmServiceServer(grpcSrv, s)
	}
	if httpSrv != nil {
		api.RegisterVlmServiceHTTPServer(httpSrv, s)
	}
}

func (s *VlmServer) StartVlmQueue(_ctx context.Context, req *api.StartVlmQueueRequest) (*api.StartVlmQueueResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.StartVlmQueueResponse{Message: "not implemented"}, nil
}

func (s *VlmServer) StopVlmQueue(_ctx context.Context, _ *api.Empty) (*api.StopVlmQueueResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.StopVlmQueueResponse{Stopped: true}, nil
}

func (s *VlmServer) GetVlmQueueStatus(_ctx context.Context, _ *api.Empty) (*api.GetVlmQueueStatusResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.GetVlmQueueStatusResponse{
		Status: &api.VlmQueueStatus{},
	}, nil
}

func (s *VlmServer) DescribePhoto(_ctx context.Context, req *api.DescribePhotoRequest) (*api.DescribePhotoResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.DescribePhotoResponse{}, nil
}

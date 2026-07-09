package service

import (
	"context"

	"backend-new/internal/pkg/api"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

// TimelineServer 时间线服务（脚手架，业务逻辑待迁移）
type TimelineServer struct {
	api.UnimplementedTimelineServiceServer
}

func (s *TimelineServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if grpcSrv != nil {
		api.RegisterTimelineServiceServer(grpcSrv, s)
	}
	if httpSrv != nil {
		api.RegisterTimelineServiceHTTPServer(httpSrv, s)
	}
}

func (s *TimelineServer) ListTimelines(_ctx context.Context, _ *api.Empty) (*api.ListTimelinesResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.ListTimelinesResponse{}, nil
}

func (s *TimelineServer) GetPhotosByTimeline(_ctx context.Context, req *api.GetPhotosByTimelineRequest) (*api.GetPhotosByTimelineResponse, error) {
	// TODO: 迁移业务逻辑
	return &api.GetPhotosByTimelineResponse{Timeline: req.Name}, nil
}

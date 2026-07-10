package service

import (
	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

// HealthServer 健康检查服务。
type HealthServer struct{}

// Reg 向 Kratos HTTP 服务器注册健康检查路由。
func (s *HealthServer) Reg(_ *grpc.Server, httpSrv *khttp.Server) {
	if httpSrv != nil {
		r := httpSrv.Route("/")
		r.GET("/api/v1/health", s.handleHealth)
	}
}

// handleHealth 返回简单的健康状态。
func (s *HealthServer) handleHealth(ctx khttp.Context) error {
	return ctx.Result(200, map[string]string{"status": "ok"})
}

package service

import (
	api "backend-new/internal/pkg/api"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	"github.com/go-kratos/kratos/v2/transport/http"
)

type AbandonCodeCURDServer struct {
	api.UnimplementedAbandonCodeCURDServer
}

func (s *AbandonCodeCURDServer) Reg(grpcSrv *grpc.Server, httpSrv *http.Server) {
	if grpcSrv != nil {
		api.RegisterAbandonCodeCURDServer(grpcSrv, s)
	}
	if httpSrv != nil {
		api.RegisterAbandonCodeCURDHTTPServer(httpSrv, s)
	}
}

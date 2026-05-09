package main

import (
	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/api"
	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/service"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

func main() {
	plogger.InitConsoleLogger()

	if err := config.Init(); err != nil {
		plogger.Fatalf("config init failed: %v", err)
	}

	if err := service.InitDB(); err != nil {
		plogger.Fatalf("db init failed: %v", err)
	}

	cfg := config.Get()

	r := gin.Default()
	api.SetupRoutes(r)

	plogger.Infof("Server starting on %s", cfg.Server.Addr)
	if err := r.Run(cfg.Server.Addr); err != nil {
		plogger.Fatalf("server run failed: %v", err)
	}
}

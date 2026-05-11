package main

import (
	"flag"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/api"
	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/service"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"go.uber.org/zap/zapcore"
)

var (
	configFlag = flag.String("c", "", "config file path (e.g. pancake.yaml)")
	logConsole = flag.Bool("l", false, "log to console; false for file only")
)

func main() {
	flag.Parse()
	plogger.InitLogger(*logConsole, zapcore.DebugLevel, "")

	if *configFlag != "" {
		if err := config.Init(*configFlag); err != nil {
			plogger.Fatalf("config init failed: %v", err)
		}
	} else {
		if err := config.Init(); err != nil {
			plogger.Fatalf("config init failed: %v", err)
		}
	}

	if err := service.InitDB(); err != nil {
		plogger.Fatalf("db init failed: %v", err)
	}

	cfg := config.Get()

	r := gin.Default()
	api.SetupRoutes(r)

	// Embedding 代理（兼容 OpenAI 格式 -> 火山引擎 multimodal）
	r.POST("/v1/embeddings", api.EmbeddingProxy)

	plogger.Infof("Server starting on %s", cfg.Server.Addr)
	if err := r.Run(cfg.Server.Addr); err != nil {
		plogger.Fatalf("server run failed: %v", err)
	}
}

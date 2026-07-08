package main

import (
	"context"
	"flag"
	"net/http"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/photo-agent/internal/api"
	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/service"
	"go.uber.org/zap/zapcore"
)

var (
	configFlag = flag.String("c", "", "config file path (e.g. ./configs/config.yaml)")
	logConsole = flag.Bool("l", false, "log to console; false for file only")
	clearDB    = flag.Bool("clearDB", false, "clear all DB data before AutoSync, rebuild from disk")
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

	// 启动时后台自动同步照片数据（不阻塞 server 启动）
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		if err := service.AutoSync(*clearDB); err != nil {
			plogger.Warnf("auto sync failed: %v", err)
		}
	}()

	cfg := config.Get()

	r := gin.Default()
	api.SetupRoutes(r)

	// Embedding 代理（兼容 OpenAI 格式 -> 火山引擎 multimodal）
	r.POST("/v1/embeddings", api.EmbeddingProxy)

	srv := &http.Server{
		Addr:    cfg.Server.Addr,
		Handler: r,
	}

	// 在 goroutine 中启动服务，主 goroutine 等待信号
	go func() {
		plogger.Infof("Server starting on %s", cfg.Server.Addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			plogger.Fatalf("server listen failed: %v", err)
		}
	}()

	// 监听 SIGINT / SIGTERM
	quit := make(chan struct{})
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	<-ctx.Done()
	plogger.Info("received shutdown signal, stopping gracefully...")

	// 停止接受新请求，等待已有请求处理完（最多 10 秒）
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		plogger.Errorf("server forced to shutdown: %v", err)
	}

	// 等待后台任务完成
	plogger.Info("waiting for background tasks to complete...")
	wg.Wait()

	// 关闭数据库
	if err := service.CloseDB(); err != nil {
		plogger.Errorf("close db failed: %v", err)
	}

	close(quit)
	plogger.Info("server exited gracefully")
}

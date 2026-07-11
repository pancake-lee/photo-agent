package main

import (
	"flag"

	"backend-new/internal/defaultService/conf"
	"backend-new/internal/defaultService/service"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pconfig"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

func main() {
	l := flag.Bool("l", false, "log to console, default is false")
	c := flag.String("c", "",
		"config folder, should have common.yaml and ${execName}.yaml")
	flag.Parse()

	pconfig.MustInitConfig(*c)
	plogger.InitFromConfig(*l)
	pconfig.Log()
	pdb.MustInitSqliteByConfig()

	// 加载服务配置
	err := pconfig.Scan(&conf.C)
	if err != nil {
		plogger.Fatalf("scan config failed: %v", err)
	}

	service.AutoSync() // 阻塞，同步

	// 注册所有服务：genCURD 标准 CRUD + 业务扩展服务
	var defaultSvr service.DefaultCURDServer
	var photoSvr service.PhotoServer
	var vlmSvr service.VlmServer
	var timelineSvr service.TimelineServer
	var tagSvr service.TagServer
	var querySvr service.QueryServer
	var embeddingSvr service.EmbeddingServer
	openapiSvr := service.NewOpenAPIServer("./openapi.yaml")
	var healthSvr service.HealthServer

	papp.SetIgnoreAuth() // 开发阶段，忽略 auth 验证
	papp.RunKratosApp(
		&defaultSvr,
		&photoSvr,
		&vlmSvr,
		&timelineSvr,
		&tagSvr,
		&querySvr,
		&embeddingSvr,
		openapiSvr,
		&healthSvr)
}

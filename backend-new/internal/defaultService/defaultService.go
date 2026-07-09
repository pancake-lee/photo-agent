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
	pdb.MustInitSqliteByConfig()

	// 加载服务配置
	if err := pconfig.Scan(&conf.C); err != nil {
		plogger.Fatalf("scan config failed: %v", err)
	}

	// 注册两个服务：genCURD 标准 CRUD + PhotoService 扩展业务
	var defaultSvr service.DefaultCURDServer
	var photoSvr service.PhotoServer

	papp.RunKratosApp(&defaultSvr, &photoSvr)
}

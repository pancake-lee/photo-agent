// activity-sync runs the same idempotent migration and reconciliation as startup
// without opening service ports or calling any model.
package main

import (
	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/service"
	"backend/internal/pkg/db"
	"context"
	"flag"
	"fmt"
	"github.com/pancake-lee/pgo/pkg/pconfig"
	"github.com/pancake-lee/pgo/pkg/pdb"
)

func main() {
	path := flag.String("c", "", "service config file")
	flag.Parse()
	if *path == "" {
		panic("必须使用 -c 指定配置文件")
	}
	pconfig.MustInitConfig(*path)
	pdb.MustInitSqliteByConfig()
	err := db.Migrate()
	if err != nil {
		panic(err)
	}
	err = pconfig.Scan(&conf.C)
	if err != nil {
		panic(err)
	}
	err = service.SyncActivityDirectories(context.Background())
	if err != nil {
		panic(err)
	}
	sqlDB, err := pdb.GetGormDB().DB()
	if err != nil {
		panic(err)
	}
	err = sqlDB.Close()
	if err != nil {
		panic(err)
	}
	fmt.Println("Activity directories synchronized")
}

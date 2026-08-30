// schema-baseline 显式刷新用户路径测试使用的空 SQLite schema 基线。
// 仅生产迁移可生成该资产；日常测试只复制它，不得自行执行 DDL。
package main

import (
	"flag"
	"os"
	"path/filepath"

	appdb "backend/internal/pkg/db"

	"github.com/pancake-lee/pgo/pkg/pdb"
)

func main() {
	output := flag.String("output", "internal/testutil/testdata/photo_agent_schema.sqlite", "schema baseline output")
	flag.Parse()
	if err := os.MkdirAll(filepath.Dir(*output), 0755); err != nil {
		panic(err)
	}
	if err := os.Remove(*output); err != nil && !os.IsNotExist(err) {
		panic(err)
	}
	if err := pdb.InitSqlite(*output); err != nil {
		panic(err)
	}
	if err := appdb.Migrate(); err != nil {
		panic(err)
	}
	if err := pdb.GetGormDB().Exec("PRAGMA wal_checkpoint(TRUNCATE)").Error; err != nil {
		panic(err)
	}
	sqlDB, err := pdb.GetGormDB().DB()
	if err != nil {
		panic(err)
	}
	if err := sqlDB.Close(); err != nil {
		panic(err)
	}
	if info, err := os.Stat(*output); err != nil || info.Size() == 0 {
		panic("schema baseline was not created")
	}
}

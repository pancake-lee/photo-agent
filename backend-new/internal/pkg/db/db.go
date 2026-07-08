package db

import (
	"backend-new/internal/pkg/db/query"
	"github.com/pancake-lee/pgo/pkg/pdb"
)

// 可以考虑生成gorm时加入gen.WithDefaultQuery，生成SetDefault就不用每次都Use
func GetQuery() *query.Query {
	return query.Use(pdb.GetGormDB())
}

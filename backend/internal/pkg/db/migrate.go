package db

import (
	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/pdb"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

// Migrate 执行数据库迁移，幂等添加新列。
func Migrate() error {
	g := pdb.GetGormDB()
	if g.Migrator().HasColumn(&model.Photo{}, "file_type") {
		plogger.Info("DB migrate: file_type column already exists, skip")
		return nil
	}
	if err := g.Migrator().AddColumn(&model.Photo{}, "FileType"); err != nil {
		return err
	}
	plogger.Info("DB migrate: added file_type column to photos")
	return nil
}

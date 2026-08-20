package db

import (
	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/pdb"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

// Migrate 执行数据库迁移，幂等添加新列/新表。
func Migrate() error {
	g := pdb.GetGormDB()

	// photos 表按需补列
	if !g.Migrator().HasColumn(&model.Photo{}, "file_type") {
		if err := g.Migrator().AddColumn(&model.Photo{}, "FileType"); err != nil {
			return err
		}
		plogger.Info("DB migrate: added file_type column to photos")
	}
	if !g.Migrator().HasColumn(&model.Photo{}, "burst_group_id") {
		if err := g.Migrator().AddColumn(&model.Photo{}, "BurstGroupID"); err != nil {
			return err
		}
		plogger.Info("DB migrate: added burst_group_id column to photos")
	}

	// photo_groups 表按需补建
	if !g.Migrator().HasTable(&model.PhotoGroup{}) {
		if err := g.Migrator().CreateTable(&model.PhotoGroup{}); err != nil {
			return err
		}
		plogger.Info("DB migrate: created photo_groups table")
	}

	return nil
}

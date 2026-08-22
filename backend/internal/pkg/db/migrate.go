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
		// 生成模型丢失了空串默认值(gorm/gen 不输出 default:'')，AddColumn 会生成
		// `ADD burst_group_id text NOT NULL` 无默认值，SQLite 在表已有数据时拒绝。
		// 这里显式带 DEFAULT ''，与 sql/photos.sql 的列定义保持一致。
		if err := g.Exec("ALTER TABLE photos ADD COLUMN burst_group_id TEXT NOT NULL DEFAULT ''").Error; err != nil {
			return err
		}
		plogger.Info("DB migrate: added burst_group_id column to photos")
	}
	if !g.Migrator().HasColumn(&model.Photo{}, "burst_group_coarse_id") {
		// 模糊档分组列，同上显式带 DEFAULT ''
		if err := g.Exec("ALTER TABLE photos ADD COLUMN burst_group_coarse_id TEXT NOT NULL DEFAULT ''").Error; err != nil {
			return err
		}
		plogger.Info("DB migrate: added burst_group_coarse_id column to photos")
	}

	// photo_groups 表按需补建
	if !g.Migrator().HasTable(&model.PhotoGroup{}) {
		if err := g.Migrator().CreateTable(&model.PhotoGroup{}); err != nil {
			return err
		}
		plogger.Info("DB migrate: created photo_groups table")
	}
	if !g.Migrator().HasColumn(&model.PhotoGroup{}, "profile") {
		// 存量组记录由旧版单档参数算出，等价精细档，默认值落 'fine'
		if err := g.Exec("ALTER TABLE photo_groups ADD COLUMN profile TEXT NOT NULL DEFAULT 'fine'").Error; err != nil {
			return err
		}
		plogger.Info("DB migrate: added profile column to photo_groups")
	}

	// app_settings 表按需补建（网页可编辑的运行期配置）
	if !g.Migrator().HasTable(&model.AppSetting{}) {
		if err := g.Migrator().CreateTable(&model.AppSetting{}); err != nil {
			return err
		}
		plogger.Info("DB migrate: created app_settings table")
	}

	// photos 表补 timeline_manual 列（人工指定 timeline，重算时保留）
	if !g.Migrator().HasColumn(&model.Photo{}, "timeline_manual") {
		if err := g.Exec("ALTER TABLE photos ADD COLUMN timeline_manual INTEGER NOT NULL DEFAULT 0").Error; err != nil {
			return err
		}
		plogger.Info("DB migrate: added timeline_manual column to photos")
	}

	// photos 表补 description_model / description_time 列（VLM 实时生成后入库）
	if !g.Migrator().HasColumn(&model.Photo{}, "description_model") {
		if err := g.Exec("ALTER TABLE photos ADD COLUMN description_model TEXT NOT NULL DEFAULT ''").Error; err != nil {
			return err
		}
		plogger.Info("DB migrate: added description_model column to photos")
	}
	if !g.Migrator().HasColumn(&model.Photo{}, "description_time") {
		if err := g.Exec("ALTER TABLE photos ADD COLUMN description_time TEXT NOT NULL DEFAULT ''").Error; err != nil {
			return err
		}
		plogger.Info("DB migrate: added description_time column to photos")
	}

	// timeline_events 表按需补建（时间线事件，从 timeline.json 迁移）
	if !g.Migrator().HasTable(&model.TimelineEvent{}) {
		if err := g.Migrator().CreateTable(&model.TimelineEvent{}); err != nil {
			return err
		}
		plogger.Info("DB migrate: created timeline_events table")
	}

	return nil
}

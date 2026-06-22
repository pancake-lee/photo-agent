package service

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/model"
	"github.com/pancake-lee/pgo/pkg/plogger"

	"github.com/glebarez/sqlite"
	"gorm.io/gorm"
)

var db *gorm.DB

// InitDB 初始化 SQLite 数据库
func InitDB() error {
	cfg := config.Get()
	sqlitePath := cfg.ResolvePath(cfg.DB.SqlitePath)

	// 确保目录存在
	dir := filepath.Dir(sqlitePath)
	if dir != "" && dir != "." {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return fmt.Errorf("create sqlite dir failed: %w", err)
		}
	}

	var err error
	db, err = gorm.Open(sqlite.Open(sqlitePath), &gorm.Config{})
	if err != nil {
		return fmt.Errorf("open sqlite failed: %w", err)
	}

	// 自动迁移表结构
	if err := db.AutoMigrate(&model.Photo{}, &model.ImportJob{}); err != nil {
		return fmt.Errorf("auto migrate failed: %w", err)
	}

	plogger.Info("SQLite initialized, path: " + sqlitePath)
	return nil
}

// GetDB 获取数据库实例
func GetDB() *gorm.DB {
	return db
}

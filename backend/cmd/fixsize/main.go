// fixsize 一次性修复脚本：从 PhotoSrc 原图重新读取尺寸，修正历史入库的缩略图尺寸。
//
// 用法（在 backend 目录下）：
//
//	go run ./cmd/fixsize -c ../.local/pancake.yaml
package main

import (
	"flag"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"path/filepath"

	"backend/internal/defaultService/conf"
	"backend/internal/pkg/db"
	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/pconfig"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

func main() {
	c := flag.String("c", "", "config folder, should have common.yaml and ${execName}.yaml")
	l := flag.Bool("l", true, "log to console")
	flag.Parse()

	pconfig.MustInitConfig(*c)
	plogger.InitFromConfig(*l)
	pdb.MustInitSqliteByConfig()
	if err := db.Migrate(); err != nil {
		plogger.Fatalf("DB migrate failed: %v", err)
	}
	if err := pconfig.Scan(&conf.C); err != nil {
		plogger.Fatalf("scan config failed: %v", err)
	}

	var photos []model.Photo
	if err := pdb.GetGormDB().Where("file_type != ?", "nef").Find(&photos).Error; err != nil {
		plogger.Fatalf("query photos failed: %v", err)
	}

	fixed, skipped, failed := 0, 0, 0
	for _, p := range photos {
		srcPath := filepath.Join(conf.C.Storage.PhotoSrc, p.FilePath)
		w, h := imageSize(srcPath)
		if w <= 0 || h <= 0 {
			plogger.Warnf("跳过 %s（无法读取原图尺寸）", p.FilePath)
			skipped++
			continue
		}
		if int32(w) == p.Width && int32(h) == p.Height {
			continue // 尺寸已正确
		}
		if err := pdb.GetGormDB().Model(&model.Photo{}).
			Where("id = ?", p.ID).
			Updates(map[string]any{"width": int32(w), "height": int32(h)}).Error; err != nil {
			plogger.Warnf("更新 %s 失败: %v", p.FilePath, err)
			failed++
			continue
		}
		plogger.Infof("%s %dx%d → %dx%d", p.FilePath, p.Width, p.Height, w, h)
		fixed++
	}

	plogger.Infof("完成：修正 %d，跳过 %d，失败 %d", fixed, skipped, failed)
}

// imageSize 读取图片原始尺寸（仅 JPEG/PNG，NEF 已在上游排除）。
func imageSize(path string) (int, int) {
	f, err := os.Open(path)
	if err != nil {
		return 0, 0
	}
	defer f.Close()
	cfg, _, err := image.DecodeConfig(f)
	if err != nil {
		return 0, 0
	}
	return cfg.Width, cfg.Height
}

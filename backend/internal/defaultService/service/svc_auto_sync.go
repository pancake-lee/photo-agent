package service

import (
	"context"
	"crypto/md5"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/db"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"
)

// --------------------------------------------------
// AutoSyncServer 启动时后台自动同步照片数据。
// 扫描 photo_path 目录，对比 SQLite 做增量导入。
// --------------------------------------------------

// dedupRegistry MD5 去重注册表，持久化到 JSON 文件。
// key 为文件 MD5（hex），value 为首次出现的 relPath。
type dedupRegistry struct {
	mu       sync.Mutex
	path     string
	hashes   map[string]string // md5 → relPath
	modified bool
}

// runAutoSync 执行自动同步。
func AutoSync() error {
	photoPath := conf.C.Storage.PhotoPath
	if photoPath == "" {
		plogger.Info("AutoSync: photo_path not configured, skipping")
		return nil
	}

	// 清除缓存，确保读取最新文件
	clearTimelineCache()
	ClearDescCache()

	// 加载 descriptions.json
	descMap, _ := loadDescriptions(conf.C.Storage.DescriptionsPath)

	// 加载时间线
	timelineEntries, _ := loadTimeline(conf.C.Storage.TimelinePath)

	// 加载 MD5 去重注册表
	dedupPath := filepath.Join(filepath.Dir(conf.C.Storage.DescriptionsPath), "dedup_hashes.json")
	reg := loadDedupRegistry(dedupPath)

	// 扫描 photo_path 下所有图片
	images, err := scanImagesInPhotoPath(photoPath)
	if err != nil {
		return fmt.Errorf("scan photo path failed: %w", err)
	}
	if len(images) == 0 {
		plogger.Info("AutoSync: no images found in photo_path")
		return nil
	}

	// 加载现有照片（file_path → PhotoDO）
	ctx := papp.NewAppCtx(context.Background())
	allPhotos, err := data.PhotoDAO.GetAll(ctx)
	if err != nil {
		return fmt.Errorf("query existing photos failed: %w", err)
	}
	existingMap := make(map[string]*data.PhotoDO, len(allPhotos))
	for _, p := range allPhotos {
		existingMap[p.FilePath] = p
	}

	plogger.Infof("AutoSync: %d images scanned, %d existing in DB", len(images), len(existingMap))

	var newCount, updateCount, skipCount int
	var mu sync.Mutex

	for _, img := range images {
		// MD5 去重（仅新照片）
		if _, found := existingMap[img.relPath]; !found {
			if fileMD5, err := computeFileMD5(img.absPath); err == nil {
				if firstPath, exists := reg.exists(fileMD5); exists {
					plogger.Warnf("AutoSync dedup skip (same as %s): %s", firstPath, img.relPath)
					mu.Lock()
					skipCount++
					mu.Unlock()
					continue
				}
			}
		}

		if existing, found := existingMap[img.relPath]; found {
			// 已有照片：检查是否需要更新
			if syncUpdatePhoto(ctx, existing, img, descMap, timelineEntries) {
				mu.Lock()
				updateCount++
				mu.Unlock()
			} else {
				mu.Lock()
				skipCount++
				mu.Unlock()
			}
			continue
		}

		// 新照片：完整导入
		if err := syncImportPhoto(ctx, img, descMap, timelineEntries); err != nil {
			plogger.Warnf("AutoSync import failed %s: %v", img.relPath, err)
			continue
		}

		// 注册 MD5
		if fileMD5, err := computeFileMD5(img.absPath); err == nil {
			reg.register(fileMD5, img.relPath)
		}

		mu.Lock()
		newCount++
		mu.Unlock()
	}

	// 保存去重注册表
	if err := reg.save(); err != nil {
		plogger.Warnf("Dedup registry save failed: %v", err)
	}

	plogger.Debugf("AutoSync done: new=%d, updated=%d, skipped=%d", newCount, updateCount, skipCount)
	return nil
}

// --------------------------------------------------
// 图片扫描
// --------------------------------------------------

type imageEntry struct {
	absPath  string
	relPath  string
	filename string
}

// scanImagesInPhotoPath 递归扫描 photo_path 目录下的所有图片文件。
func scanImagesInPhotoPath(root string) ([]imageEntry, error) {
	var images []imageEntry

	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if info.IsDir() {
			return nil
		}

		ext := strings.ToLower(filepath.Ext(path))
		if ext != ".jpg" && ext != ".jpeg" && ext != ".png" && ext != ".webp" {
			return nil
		}

		relPath, err := filepath.Rel(root, path)
		if err != nil {
			return nil
		}
		relPath = filepath.ToSlash(relPath)

		images = append(images, imageEntry{
			absPath:  path,
			relPath:  relPath,
			filename: info.Name(),
		})
		return nil
	})

	return images, err
}

// --------------------------------------------------
// 新照片导入
// --------------------------------------------------

// syncImportPhoto 导入单张新照片。
func syncImportPhoto(ctx *papp.AppCtx, img imageEntry, descMap descriptionMap, entries []TimelineEntry) error {
	ei := getExifInfo(img.absPath)
	if ei == nil {
		ei = &exifInfo{}
	}


	// 匹配时间线
	timeline := ""
	if ei.ShotAt != nil {
		timeline = findEventByTime(*ei.ShotAt, entries, conf.C.Storage.TimelineWindowDays)
	}

	width, height := getImageSize(img.absPath)

	// 从 descriptions.json 获取描述
	var description string
	if descMap != nil {
		if entry := findDescInMap(descMap, img.relPath); entry.Description != "" {
			description = entry.Description
		}
	}

	photoDO := &data.PhotoDO{
		ID:           putil.UUID(),
		Filename:     img.filename,
		FilePath:     img.relPath,
		Timeline:     timeline,
		Description:  description,
		Width:        int32(width),
		Height:       int32(height),
		Brand:        ei.Brand,
		Model:        ei.Model,
		Lens:         ei.Lens,
		FocalLength:  ei.FocalLength,
		Aperture:     ei.Aperture,
		Iso:          int32(ei.ISO),
		ExposureTime: ei.ExposureTime,
	}
	if ei.ShotAt != nil {
		photoDO.ShotAt = *ei.ShotAt
	}
	if ei.Latitude != nil {
		photoDO.Latitude = *ei.Latitude
	}
	if ei.Longitude != nil {
		photoDO.Longitude = *ei.Longitude
	}
	if ei.Altitude != nil {
		photoDO.Altitude = *ei.Altitude
	}

	if err := data.PhotoDAO.Add(ctx, photoDO); err != nil {
		return fmt.Errorf("save photo failed: %w", err)
	}

	plogger.Infof("AutoSync imported: %s, id=%s", img.relPath, photoDO.ID)
	return nil
}

// --------------------------------------------------
// 已有照片更新
// --------------------------------------------------

// syncUpdatePhoto 更新已有照片的描述和时间线。
// 返回 true 表示有实际更新。
func syncUpdatePhoto(ctx *papp.AppCtx, existing *data.PhotoDO, img imageEntry, descMap descriptionMap, entries []TimelineEntry) bool {
	// 从 descriptions.json 获取最新描述
	var newDesc string
	if descMap != nil {
		if entry := findDescInMap(descMap, img.relPath); entry.Description != "" {
			newDesc = entry.Description
		}
	}

	// 重新计算时间线
	newTimeline := ""
	if ei := getExifInfo(img.absPath); ei != nil && ei.ShotAt != nil {
		newTimeline = findEventByTime(*ei.ShotAt, entries, conf.C.Storage.TimelineWindowDays)
	} else if !existing.ShotAt.IsZero() {
		newTimeline = findEventByTime(existing.ShotAt, entries, conf.C.Storage.TimelineWindowDays)
	}

	// 检查是否有变化
	if existing.Description == newDesc &&
		existing.Timeline == newTimeline {
		return false
	}

	updates := map[string]any{
		"description": newDesc,
		"timeline":    newTimeline,
	}

	q := db.GetQuery().Photo
	if _, err := q.WithContext(ctx).Where(q.ID.Eq(existing.ID)).Updates(updates); err != nil {
		plogger.Warnf("AutoSync update failed %s: %v", img.relPath, err)
		return false
	}

	plogger.Infof("AutoSync updated: %s, timeline=%q", img.relPath, newTimeline)
	return true
}

// --------------------------------------------------
// MD5 去重注册表
// --------------------------------------------------

// loadDedupRegistry 加载 MD5 注册表文件，不存在则返回空注册表。
func loadDedupRegistry(filePath string) *dedupRegistry {
	r := &dedupRegistry{
		path:   filePath,
		hashes: make(map[string]string),
	}

	data, err := os.ReadFile(filePath)
	if err != nil {
		if !os.IsNotExist(err) {
			plogger.Warnf("DedupRegistry load failed: %v", err)
		}
		return r
	}

	entries := make(map[string]string)
	if err := json.Unmarshal(data, &entries); err != nil {
		// 兼容旧格式：数组
		var legacy []struct {
			MD5     string `json:"md5"`
			RelPath string `json:"rel_path"`
		}
		if err2 := json.Unmarshal(data, &legacy); err2 != nil {
			plogger.Warnf("DedupRegistry parse failed: %v", err)
			return r
		}
		for _, e := range legacy {
			entries[e.MD5] = e.RelPath
		}
	}

	r.hashes = entries
	plogger.Infof("DedupRegistry loaded: %d hashes from %s", len(r.hashes), filepath.Base(filePath))
	return r
}

// exists 检查 MD5 是否已注册。
func (r *dedupRegistry) exists(md5sum string) (relPath string, found bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	p, ok := r.hashes[md5sum]
	return p, ok
}

// register 注册 MD5 → relPath 映射。
func (r *dedupRegistry) register(md5sum, relPath string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.hashes[md5sum]; exists {
		return
	}
	r.hashes[md5sum] = relPath
	r.modified = true
}

// save 持久化注册表（仅在有变更时写入）。
func (r *dedupRegistry) save() error {
	r.mu.Lock()
	defer r.mu.Unlock()

	if !r.modified {
		return nil
	}

	dir := filepath.Dir(r.path)
	if dir != "" && dir != "." {
		_ = os.MkdirAll(dir, 0755)
	}

	data, err := json.MarshalIndent(r.hashes, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal dedup registry: %w", err)
	}

	tmpPath := r.path + ".tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil {
		return fmt.Errorf("write dedup registry: %w", err)
	}

	if err := os.Rename(tmpPath, r.path); err != nil {
		return fmt.Errorf("rename dedup registry: %w", err)
	}

	r.modified = false
	plogger.Infof("DedupRegistry saved: %d hashes", len(r.hashes))
	return nil
}

// computeFileMD5 计算文件的 MD5 哈希（hex 字符串）。
func computeFileMD5(filePath string) (string, error) {
	f, err := os.Open(filePath)
	if err != nil {
		return "", fmt.Errorf("open file: %w", err)
	}
	defer f.Close()

	h := md5.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", fmt.Errorf("hash file: %w", err)
	}

	return fmt.Sprintf("%x", h.Sum(nil)), nil
}

package service

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/model"
	"github.com/pancake-lee/photo-agent/internal/vlm"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

// AutoSync 自动同步照片数据到 SQLite 和 Dify。
// 扫描 photo_path 下所有图片，读取 descriptions.json，对比 SQLite 执行增量导入：
//   - 新照片：执行完整导入流程（EXIF、时间线、描述、Dify 同步）
//   - 已有照片：如 description 变化则更新并同步 Dify
//   - 无变化：跳过
//
// 当 clearDB 为 true 时，先清空 SQLite 中所有数据，再基于磁盘文件全新构建。
// 此函数在 server 启动时由后台 goroutine 调用，不阻塞启动流程。
func AutoSync(clearDB bool) error {
	cfg := config.Get()

	// 0. 如果需要清空数据库（-clearDB 参数），先删除所有旧数据
	if clearDB {
		if err := ClearAllData(); err != nil {
			return fmt.Errorf("clear db failed: %w", err)
		}
		// 同时清空 MD5 去重注册表，确保所有磁盘图片都会被重新导入
		dedupPath := filepath.Join(filepath.Dir(cfg.Storage.DescriptionsPath), "dedup_hashes.json")
		if err := os.Remove(dedupPath); err != nil && !os.IsNotExist(err) {
			plogger.Warnf("remove dedup registry failed: %v", err)
		}
		plogger.Info("AutoSync: database and dedup registry cleared, rebuilding from disk")
	}

	// 1. 清空缓存，强制重新加载最新文件
	// （batch_vlm 可能已更新 descriptions.json，时间线文件也可能已修改）
	ClearDescCache()
	ClearTimelineCache()
	preDesc, _ := LoadDescriptions()

	// 加载 MD5 去重注册表（-clearDB 时已被删除，会得到空注册表）
	dedupPath := filepath.Join(filepath.Dir(cfg.Storage.DescriptionsPath), "dedup_hashes.json")
	dedupReg := LoadDedupRegistry(dedupPath)

	// 2. 扫描 photo_path 下所有图片
	images, err := scanImagesInPhotoPath(cfg.Storage.PhotoPath)
	if err != nil {
		return fmt.Errorf("scan photo path failed: %w", err)
	}
	if len(images) == 0 {
		plogger.Info("AutoSync: no images found in photo_path")
		return nil
	}

	// 3. 加载现有照片到内存 map（key 为 file_path）
	var existingPhotos []model.Photo
	if err := db.Find(&existingPhotos).Error; err != nil {
		return fmt.Errorf("query existing photos failed: %w", err)
	}
	existingMap := make(map[string]model.Photo, len(existingPhotos))
	for _, p := range existingPhotos {
		existingMap[p.FilePath] = p
	}

	plogger.Infof("AutoSync: %d images scanned, %d existing in DB", len(images), len(existingMap))

	// 4. 并发处理（复用配置的并发数）
	concurrency := cfg.VLM.Concurrency
	if concurrency <= 0 {
		concurrency = 3
	}
	sem := make(chan struct{}, concurrency)
	var wg sync.WaitGroup

	var newCount, updateCount, skipCount int
	var mu sync.Mutex

	for _, img := range images {
		wg.Add(1)
		sem <- struct{}{}

		go func(img imageEntry) {
			defer wg.Done()
			defer func() { <-sem }()

			// 从 descriptions.json 获取描述，从 EXIF 获取完整元数据
			description, exifInfo := resolvePhotoData(img.relPath, img.absPath, preDesc)

			// MD5 去重检查（仅新照片）：避免相同内容以不同路径重复导入
				if _, found := existingMap[img.relPath]; !found {
					if fileMD5, err := ComputeFileMD5(img.absPath); err == nil {
						if firstPath, exists := dedupReg.Exists(fileMD5); exists {
							plogger.Warnf("AutoSync dedup skip (same as %s): %s", firstPath, img.relPath)
							mu.Lock()
							skipCount++
							mu.Unlock()
							return
						}
					} else {
						plogger.Warnf("MD5 compute failed %s: %v", img.relPath, err)
					}
				}

			// MD5 去重检查（仅新照片）：避免相同内容以不同路径重复导入
			if _, found := existingMap[img.relPath]; !found {
				if fileMD5, err := ComputeFileMD5(img.absPath); err == nil {
					if firstPath, exists := dedupReg.Exists(fileMD5); exists {
						plogger.Warnf("AutoSync dedup skip (same as %s): %s", firstPath, img.relPath)
						mu.Lock()
						skipCount++
						mu.Unlock()
						return
					}
				} else {
					plogger.Warnf("MD5 compute failed %s: %v", img.relPath, err)
				}
			}

			if existing, found := existingMap[img.relPath]; found {
				// 已存在：优先用 EXIF 的 shot_at 重新计算 timeline
				newTimeline := ""
				if exifInfo.ShotAt != nil {
					newTimeline = FindEventByTime(*exifInfo.ShotAt)
				} else if existing.ShotAt != nil {
					newTimeline = FindEventByTime(*existing.ShotAt)
				}

				// description 或 timeline 任一变化都触发更新，同时回填 EXIF
				if existing.Description != description || existing.Timeline != newTimeline ||
					existing.Brand == "" && exifInfo.Brand != "" {
					if err := updatePhotoWithExif(existing.ID, description, newTimeline, exifInfo); err != nil {
						plogger.Warnf("AutoSync update failed %s: %v", img.relPath, err)
						return
					}
					syncPhotoToDify(existing.ID, description, newTimeline)
					mu.Lock()
					updateCount++
					mu.Unlock()
				} else {
					mu.Lock()
					skipCount++
					mu.Unlock()
				}
				return
			}

			// 新照片，执行完整导入
			photo, err := importNewPhoto(img.absPath, img.relPath, description, exifInfo)
			if err != nil {
				plogger.Warnf("AutoSync import failed %s: %v", img.relPath, err)
				return
			}


			// 注册 MD5 去重
			if fileMD5, err := ComputeFileMD5(img.absPath); err == nil {
				dedupReg.Register(fileMD5, img.relPath)
			}
			syncPhotoToDify(photo.ID, description, photo.Timeline)

			mu.Lock()
			newCount++
			mu.Unlock()
		}(img)
	}

	wg.Wait()


	// 保存去重注册表
	if err := dedupReg.Save(); err != nil {
		plogger.Warnf("Dedup registry save failed: %v", err)
	}

	plogger.Infof("AutoSync done: new=%d, updated=%d, skipped=%d", newCount, updateCount, skipCount)
	return nil
}

// imageEntry 扫描到的图片条目
type imageEntry struct {
	absPath  string // 绝对路径
	relPath  string // 相对于 photo_path 的路径（正斜杠）
	filename string
}

// scanImagesInPhotoPath 递归扫描 photo_path 目录下的所有图片文件。
// 返回的 relPath 使用正斜杠，与 descriptions.json 的 key 格式保持一致。
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

// importNewPhoto 导入单张新照片到 SQLite。
// exifInfo 包含完整 EXIF 元数据（shot_at 优先来自 descriptions.json）。
func importNewPhoto(absPath, relPath, description string, exifInfo *ExifInfo) (*model.Photo, error) {
	// 获取图片尺寸
	width, height := GetImageSize(absPath)

	// 根据拍摄时间匹配活动
	timeline := ""
	if exifInfo != nil && exifInfo.ShotAt != nil {
		timeline = FindEventByTime(*exifInfo.ShotAt)
	}

	// 保存到数据库
	photo, err := SavePhoto(filepath.Base(absPath), relPath, timeline, "", description, width, height, exifInfo)
	if err != nil {
		return nil, fmt.Errorf("save photo failed: %w", err)
	}

	plogger.Infof("Photo imported: %s, id=%s", relPath, photo.ID)
	return photo, nil
}

// resolvePhotoData 从 descriptions.json 和文件 EXIF 解析照片描述与拍摄时间。
// 优先级：descriptions.json 中的 shot_at > 文件 EXIF。
func resolvePhotoData(relPath, absPath string, preDesc DescriptionMap) (string, *ExifInfo) {
	description := ""

	if preDesc != nil {
		if entry, ok := GetDescriptionEntry(relPath); ok {
			description = entry.Description
		}
	}

	// 读取完整 EXIF 信息
	exifInfo := GetExifInfo(absPath)
	if exifInfo == nil {
		exifInfo = &ExifInfo{}
	}

	// descriptions.json 中的 shot_at 优先级高于 EXIF
	if preDesc != nil {
		if entry, ok := GetDescriptionEntry(relPath); ok {
			if entry.ShotAt != "" {
				if t, err := time.Parse(time.RFC3339, entry.ShotAt); err == nil {
					exifInfo.ShotAt = &t
				}
			}
		}
	}

	return description, exifInfo
}

// updatePhotoWithExif 更新已有照片的描述、时间线和 EXIF 字段。
func updatePhotoWithExif(photoID, description, timeline string, exifInfo *ExifInfo) error {
	updates := map[string]any{
		"description": description,
		"timeline":    timeline,
	}
	if exifInfo != nil {
		if exifInfo.Brand != "" {
			updates["brand"] = exifInfo.Brand
		}
		if exifInfo.Model != "" {
			updates["model"] = exifInfo.Model
		}
		if exifInfo.Lens != "" {
			updates["lens"] = exifInfo.Lens
		}
		if exifInfo.FocalLength != "" {
			updates["focal_length"] = exifInfo.FocalLength
		}
		if exifInfo.Aperture != "" {
			updates["aperture"] = exifInfo.Aperture
		}
		if exifInfo.ISO != 0 {
			updates["iso"] = exifInfo.ISO
		}
		if exifInfo.ExposureTime != "" {
			updates["exposure_time"] = exifInfo.ExposureTime
		}
		if exifInfo.Latitude != nil {
			updates["latitude"] = exifInfo.Latitude
		}
		if exifInfo.Longitude != nil {
			updates["longitude"] = exifInfo.Longitude
		}
		if exifInfo.Altitude != nil {
			updates["altitude"] = exifInfo.Altitude
		}
	}
	if err := db.Model(&model.Photo{}).Where("id = ?", photoID).Updates(updates).Error; err != nil {
		return fmt.Errorf("update photo failed: %w", err)
	}
	plogger.Infof("Photo updated: %s, timeline=%q", photoID, timeline)
	return nil
}

// syncPhotoToDify 将照片描述同步到 Dify 知识库。
// 仅在 Dify APIKey 和 DatasetID 都已配置且描述非空时执行。
func syncPhotoToDify(photoID, description, timeline string) {
	cfg := config.Get().Dify
	if cfg.APIKey == "" || cfg.DatasetID == "" {
		return
	}
	if description == "" {
		return
	}
	if err := vlm.WriteToKnowledgeBase(photoID, description, timeline); err != nil {
		plogger.Warnf("Dify sync failed photo_%s: %v", photoID, err)
	}
}

// ClearAllData 清空 SQLite 中所有数据（photos 和 import_jobs 表）。
// 在 AutoSync 搭配 -clearDB 参数时调用，用于基于磁盘文件全新重建数据库。
func ClearAllData() error {
	if err := db.Where("1 = 1").Delete(&model.Photo{}).Error; err != nil {
		return fmt.Errorf("delete photos failed: %w", err)
	}
	if err := db.Where("1 = 1").Delete(&model.ImportJob{}).Error; err != nil {
		return fmt.Errorf("delete import_jobs failed: %w", err)
	}
	plogger.Info("All data cleared from SQLite")
	return nil
}

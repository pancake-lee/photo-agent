package service

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/pancake-lee/photo-agent/internal/model"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/satori/go.uuid"
)

// SavePhoto 保存照片元数据到数据库
func SavePhoto(filename, filePath, timeline, tags, description string, width, height int, shotAt *time.Time) (*model.Photo, error) {
	photo := &model.Photo{
		ID:          uuid.NewV4().String(),
		Filename:    filename,
		FilePath:    filePath,
		Timeline:    timeline,
		Tags:        tags,
		Description: description,
		ShotAt:      shotAt,
		Width:       width,
		Height:      height,
		ImportedAt:  time.Now(),
	}

	if err := db.Create(photo).Error; err != nil {
		return nil, fmt.Errorf("create photo failed: %w", err)
	}

	plogger.Infof("Photo saved: id=%s, timeline=%s", photo.ID, timeline)
	return photo, nil
}

// GetPhotoByID 根据 ID 查询照片
func GetPhotoByID(id string) (*model.Photo, error) {
	var photo model.Photo
	if err := db.Where("id = ?", id).First(&photo).Error; err != nil {
		return nil, err
	}
	return &photo, nil
}

// ListPhotosParams 照片列表查询参数
type ListPhotosParams struct {
	Page     int    // 页码，从 1 开始
	PageSize int    // 每页数量
	Timeline string // 按时间线过滤
	Tag      string // 按标签过滤
	Keyword  string // 按关键词过滤（description LIKE）
}

// ListPhotos 查询照片列表（分页、过滤）
func ListPhotos(params ListPhotosParams) ([]model.Photo, int64, error) {
	if params.Page < 1 {
		params.Page = 1
	}
	if params.PageSize < 1 {
		params.PageSize = 20
	}
	if params.PageSize > 100 {
		params.PageSize = 100
	}

	q := db.Model(&model.Photo{})

	if params.Timeline != "" {
		q = q.Where("timeline = ?", params.Timeline)
	}
	if params.Tag != "" {
		q = q.Where("tags LIKE ?", "%"+params.Tag+"%")
	}
	if params.Keyword != "" {
		q = q.Where("description LIKE ?", "%"+params.Keyword+"%")
	}

	var total int64
	if err := q.Count(&total).Error; err != nil {
		return nil, 0, fmt.Errorf("count photos failed: %w", err)
	}

	var photos []model.Photo
	offset := (params.Page - 1) * params.PageSize
	if err := q.Order("shot_at DESC, imported_at DESC").
		Limit(params.PageSize).Offset(offset).
		Find(&photos).Error; err != nil {
		return nil, 0, fmt.Errorf("query photos failed: %w", err)
	}

	return photos, total, nil
}

// GetPhotosByTimeline 根据时间线查询照片
func GetPhotosByTimeline(timeline string) ([]model.Photo, error) {
	var photos []model.Photo
	if err := db.Where("timeline = ?", timeline).
		Order("shot_at DESC, imported_at DESC").
		Find(&photos).Error; err != nil {
		return nil, fmt.Errorf("query photos by timeline failed: %w", err)
	}
	return photos, nil
}

// GetPhotosByTag 根据标签查询照片
func GetPhotosByTag(tag string) ([]model.Photo, error) {
	var photos []model.Photo
	if err := db.Where("tags LIKE ?", "%"+tag+"%").
		Order("shot_at DESC, imported_at DESC").
		Find(&photos).Error; err != nil {
		return nil, fmt.Errorf("query photos by tag failed: %w", err)
	}
	return photos, nil
}

// ListDistinctTimelines 查询所有不重复的时间线
func ListDistinctTimelines() ([]string, error) {
	var timelines []string
	if err := db.Model(&model.Photo{}).
		Where("timeline != ?", "").
		Distinct().
		Pluck("timeline", &timelines).Error; err != nil {
		return nil, fmt.Errorf("query timelines failed: %w", err)
	}
	return timelines, nil
}

// ListDistinctTags 查询所有不重复的标签
func ListDistinctTags() ([]string, error) {
	var rows []struct {
		Tags string
	}
	if err := db.Model(&model.Photo{}).
		Where("tags != ?", "").
		Distinct().
		Pluck("tags", &rows).Error; err != nil {
		return nil, fmt.Errorf("query tags failed: %w", err)
	}

	tagSet := make(map[string]struct{})
	for _, r := range rows {
		var tags []string
		if err := json.Unmarshal([]byte(r.Tags), &tags); err == nil {
			for _, t := range tags {
				if t != "" {
					tagSet[t] = struct{}{}
				}
			}
		}
	}

	result := make([]string, 0, len(tagSet))
	for t := range tagSet {
		result = append(result, t)
	}
	return result, nil
}

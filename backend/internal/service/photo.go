package service

import (
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

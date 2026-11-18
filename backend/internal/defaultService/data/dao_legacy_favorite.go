package data

import (
	"errors"
	"fmt"

	"backend/internal/pkg/db/model"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// SaveRestoredFavorite preserves live metadata and verified JPG/NEF manifests.
// Restored AI results only fill an empty description; they never replace one.
func SaveRestoredFavorite(ctx *papp.AppCtx, photo *PhotoDO,
	archive PhotoArchiveDO, existingOnly bool,
) (created, inherited bool, err error) {
	err = pdb.GetGormDB().WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var current model.Photo
		lookupErr := tx.Take(&current, "id = ?", photo.ID).Error
		if errors.Is(lookupErr, gorm.ErrRecordNotFound) {
			if existingOnly {
				return fmt.Errorf("待合并照片已不存在: %s", photo.ID)
			}
			createErr := tx.Create(photo).Error
			if createErr != nil {
				return createErr
			}
			created = true
			inherited = photo.Description != ""
		} else if lookupErr != nil {
			return lookupErr
		} else {
			if !existingOnly && (current.Timeline != photo.Timeline || current.Filename != photo.Filename) {
				return fmt.Errorf("恢复照片 ID 已被其他位置占用: %s", photo.ID)
			}
			if current.Description == "" && photo.Description != "" {
				updates := map[string]any{
					"description": photo.Description, "description_model": photo.DescriptionModel,
					"description_time": photo.DescriptionTime, "description_raw": photo.DescriptionRaw,
					"objects": photo.Objects, "colors": photo.Colors, "scene": photo.Scene,
					"lighting": photo.Lighting, "mood": photo.Mood, "composition": photo.Composition,
					"embedding_status": "pending", "embedding_description_time": "",
				}
				updateErr := tx.Model(&current).Updates(updates).Error
				if updateErr != nil {
					return updateErr
				}
				inherited = true
			}
		}
		archive.PhotoID, archive.Favorite = photo.ID, true
		return tx.Clauses(clause.OnConflict{
			Columns:   []clause.Column{{Name: "photo_id"}},
			DoUpdates: clause.Assignments(map[string]any{"favorite": true}),
		}).Create(&archive).Error
	})
	return created, inherited, err
}

package data

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"sort"

	"backend/internal/pkg/db/model"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"github.com/pancake-lee/pgo/pkg/putil"
	"gorm.io/gorm"
)

type PhotoActivityMove struct {
	PhotoID        string
	FromActivityID string
	FromTimeline   string
	FromFilename   string
	ActivityID     string
	Timeline       string
	Filename       string
}

// ListPhotosForActivityMove expands selected covers in the requested profile.
// Explicitly selected non-cover photos remain individual selections.
func ListPhotosForActivityMove(ctx *papp.AppCtx, ids []string,
	profile string,
) ([]PhotoDO, error) {
	g := pdb.GetGormDB().WithContext(ctx)
	var selected []PhotoDO
	err := g.Where("id IN ? AND file_type <> ?", ids, "nef").Find(&selected).Error
	if err != nil {
		return nil, err
	}
	if len(selected) != len(ids) {
		return nil, fmt.Errorf("存在已删除或不可用的照片，请刷新后重试")
	}
	if profile == "all" {
		return selected, nil
	}
	var groups []model.PhotoGroup
	err = g.Where("cover_photo_id IN ? AND profile = ?", ids, profile).
		Find(&groups).Error
	if err != nil || len(groups) == 0 {
		return selected, err
	}
	groupIDs := make([]string, 0, len(groups))
	for _, group := range groups {
		groupIDs = append(groupIDs, group.ID)
	}
	column := "burst_group_id"
	if profile == "coarse" {
		column = "burst_group_coarse_id"
	}
	var rows []PhotoDO
	err = g.Where("file_type <> ? AND (id IN ? OR "+column+" IN ?)",
		"nef", ids, groupIDs).Order("id").Find(&rows).Error
	return rows, err
}

// MovePhotosActivity commits locations and related archive metadata together.
// Processing results and photo identities are deliberately untouched.
func MovePhotosActivity(ctx *papp.AppCtx, moves []PhotoActivityMove) error {
	return pdb.GetGormDB().WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		groups := map[string]bool{}
		for _, move := range moves {
			var photo model.Photo
			err := tx.Take(&photo, "id = ?", move.PhotoID).Error
			if err != nil {
				return err
			}
			if photo.ActivityID != move.FromActivityID ||
				photo.Timeline != move.FromTimeline || photo.Filename != move.FromFilename {
				return fmt.Errorf("照片位置已变化，请重新预览: %s", photo.Filename)
			}
			var count int64
			err = tx.Model(&model.Photo{}).
				Where("timeline = ? AND filename = ? COLLATE NOCASE AND id <> ?",
					move.Timeline, move.Filename, move.PhotoID).Count(&count).Error
			if err != nil {
				return err
			}
			if count > 0 {
				return fmt.Errorf("目标照片位置已被占用: %s", move.Filename)
			}
			groups[photo.BurstGroupID], groups[photo.BurstGroupCoarseID] = true, true
			err = tx.Model(&model.Photo{}).Where("id = ?", move.PhotoID).
				Updates(map[string]any{"activity_id": move.ActivityID,
					"timeline": move.Timeline, "filename": move.Filename}).Error
			if err != nil {
				return err
			}
			var state model.PhotoArchive
			err = tx.Where("photo_id = ?", move.PhotoID).Find(&state).Error
			if err != nil {
				return err
			}
			if state.ImportKey != "" {
				err = tx.Model(&state).Update("import_key", ArchiveImportKey(
					move.Timeline, state.JPGSHA256, state.NEFSHA256)).Error
				if err != nil {
					return err
				}
			}
			err = moveRecycledNEFLocation(tx, move)
			if err != nil {
				return err
			}
		}
		delete(groups, "")
		for id := range groups {
			err := splitMovedPhotoGroup(tx, id)
			if err != nil {
				return err
			}
		}
		return nil
	})
}

func moveRecycledNEFLocation(tx *gorm.DB, move PhotoActivityMove) error {
	var items []model.PhotoRecycle
	err := tx.Where("photo_id = ? AND kind = ? AND state <> ?",
		move.PhotoID, "nef", "purged").Find(&items).Error
	if err != nil {
		return err
	}
	for _, item := range items {
		var photo model.Photo
		var files []map[string]any
		err = json.Unmarshal(item.PhotoJSON, &photo)
		if err != nil {
			return err
		}
		err = json.Unmarshal(item.FilesJSON, &files)
		if err != nil {
			return err
		}
		photo.ActivityID, photo.Timeline, photo.Filename =
			move.ActivityID, move.Timeline, move.Filename
		photo.FilePath = filepath.Join(move.Timeline, move.Filename)
		for _, file := range files {
			// original locates the archived attachment; only restore changes.
			rel, ok := file["original"].(string)
			if !ok {
				return fmt.Errorf("NEF 回收记录缺少文件路径")
			}
			stem := move.Filename[:len(move.Filename)-len(filepath.Ext(move.Filename))]
			file["restore"] = filepath.Join(move.Timeline, stem+filepath.Ext(rel))
		}
		item.PhotoJSON, err = json.Marshal(photo)
		if err != nil {
			return err
		}
		item.FilesJSON, err = json.Marshal(files)
		if err != nil {
			return err
		}
		err = tx.Save(&item).Error
		if err != nil {
			return err
		}
	}
	return nil
}

// A group must not hide members behind a cover in another activity.
func splitMovedPhotoGroup(tx *gorm.DB, id string) error {
	var group model.PhotoGroup
	err := tx.Where("id = ?", id).Find(&group).Error
	if err != nil || group.ID == "" {
		return err
	}
	column := "burst_group_id"
	if group.Profile == "coarse" {
		column = "burst_group_coarse_id"
	}
	var members []model.Photo
	err = tx.Where(column+" = ?", id).Order("shot_at, id").Find(&members).Error
	if err != nil {
		return err
	}
	partitions := map[string][]model.Photo{}
	for _, member := range members {
		partitions[member.Timeline] = append(partitions[member.Timeline], member)
	}
	if len(partitions) <= 1 {
		return nil
	}
	err = tx.Delete(&group).Error
	if err != nil {
		return err
	}
	names := make([]string, 0, len(partitions))
	for name := range partitions {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		list := partitions[name]
		newID := ""
		if len(list) > 1 {
			part := group
			part.ID, part.CoverPhotoID = putil.UUID(), list[0].ID
			for _, member := range list {
				if member.ID == group.CoverPhotoID {
					part.ID, part.CoverPhotoID = group.ID, member.ID
				}
			}
			part.PhotoCount = int32(len(list))
			part.TimeStart, part.TimeEnd = list[0].ShotAt, list[len(list)-1].ShotAt
			err = tx.Create(&part).Error
			if err != nil {
				return err
			}
			newID = part.ID
		}
		ids := make([]string, 0, len(list))
		for _, member := range list {
			ids = append(ids, member.ID)
		}
		err = tx.Model(&model.Photo{}).Where("id IN ?", ids).Update(column, newID).Error
		if err != nil {
			return err
		}
	}
	return nil
}

package data

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"

	"backend/internal/pkg/db/model"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"gorm.io/gorm"
)

type ActivityLocation struct {
	ActivityID string
	Timeline   string
}

// MigratePhotoLocations consumes legacy paths exactly once without changing IDs
// or processing results. The retired column remains for schema compatibility.
func MigratePhotoLocations(ctx *papp.AppCtx) error {
	return pdb.GetGormDB().WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var rows []struct{ ID, Filename, FilePath string }
		err := tx.Table("photos").Select("id, filename, file_path").Where("file_path <> ''").Scan(&rows).Error
		if err != nil {
			return err
		}
		for _, row := range rows {
			folder := filepath.Dir(row.FilePath)
			if folder == "." {
				folder = ""
			}
			if !filepath.IsLocal(row.FilePath) {
				return fmt.Errorf("照片 %s 的旧路径无效", row.ID)
			}
			updates := map[string]any{"timeline": folder, "filename": filepath.Base(row.FilePath), "file_path": ""}
			err = tx.Table("photos").Where("id = ?", row.ID).Updates(updates).Error
			if err != nil {
				return err
			}
		}
		return nil
	})
}

func ListActivityLocations(ctx *papp.AppCtx) ([]ActivityLocation, error) {
	var rows []ActivityLocation
	err := pdb.GetGormDB().WithContext(ctx).Table("photos").Distinct("activity_id", "timeline").Find(&rows).Error
	if err != nil {
		return nil, err
	}
	var items []model.PhotoRecycle
	err = pdb.GetGormDB().WithContext(ctx).Where("state <> ?", "purged").Find(&items).Error
	if err != nil {
		return nil, err
	}
	for _, item := range items {
		var photo model.Photo
		err = json.Unmarshal(item.PhotoJSON, &photo)
		if err != nil {
			return nil, err
		}
		rows = append(rows, ActivityLocation{ActivityID: photo.ActivityID, Timeline: photo.Timeline})
	}
	return rows, nil
}

// RebindEmptyActivityRecycle keeps prior deletions recoverable after merging
// empty activity directories. The caller first moves all live photos.
func RebindEmptyActivityRecycle(ctx *papp.AppCtx, fromID, fromName, toID,
	toName string,
) (int, error) {
	changed := 0
	err := pdb.GetGormDB().WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var count int64
		err := tx.Model(&model.Photo{}).
			Where("activity_id = ? OR timeline = ?", fromID, fromName).Count(&count).Error
		if err != nil {
			return err
		}
		if count > 0 {
			return fmt.Errorf("源活动仍含照片，不能合并空目录")
		}
		var items []model.PhotoRecycle
		err = tx.Where("state <> ?", "purged").Find(&items).Error
		if err != nil {
			return err
		}
		for _, item := range items {
			var photo model.Photo
			err = json.Unmarshal(item.PhotoJSON, &photo)
			if err != nil {
				return err
			}
			if photo.ActivityID != fromID {
				continue
			}
			if photo.Timeline != fromName || item.State != "deleted" {
				return fmt.Errorf("源活动有未完成或位置不一致的回收记录")
			}
			photo.ActivityID, photo.Timeline = toID, toName
			photo.FilePath = filepath.Join(toName, photo.Filename)
			var files []map[string]any
			err = json.Unmarshal(item.FilesJSON, &files)
			if err != nil {
				return err
			}
			for _, file := range files {
				for _, key := range []string{"original", "restore"} {
					rel, ok := file[key].(string)
					if ok && filepath.Dir(rel) == fromName {
						file[key] = filepath.Join(toName, filepath.Base(rel))
					}
				}
			}
			photoJSON, marshalErr := json.Marshal(photo)
			if marshalErr != nil {
				return marshalErr
			}
			filesJSON, marshalErr := json.Marshal(files)
			if marshalErr != nil {
				return marshalErr
			}
			err = tx.Model(&model.PhotoRecycle{}).Where("id = ?", item.ID).
				Updates(map[string]any{"photo_json": photoJSON, "files_json": filesJSON}).Error
			if err != nil {
				return err
			}
			var state model.PhotoArchive
			err = tx.Where("photo_id = ?", photo.ID).Find(&state).Error
			if err != nil {
				return err
			}
			if state.ImportKey != "" {
				err = tx.Model(&state).Update("import_key",
					ArchiveImportKey(toName, state.JPGSHA256, state.NEFSHA256)).Error
				if err != nil {
					return err
				}
			}
			changed++
		}
		return nil
	})
	return changed, err
}

func ArchiveImportKey(activity, jpg, nef string) string {
	sum := sha256.Sum256([]byte(activity + "\x00" + jpg + "\x00" + nef))
	return hex.EncodeToString(sum[:])
}

func HasActivityReservations(ctx *papp.AppCtx, name string) (bool, error) {
	var count int64
	err := pdb.GetGormDB().WithContext(ctx).Model(&model.PhotoImportReservation{}).
		Where("substr(target, 1, instr(target, '/') - 1) = ?", name).Count(&count).Error
	return count > 0, err
}

// BindActivityDirectory updates the name cache and all journals atomically.
// Stable IDs and archived digests survive both filesystem and UI renames.
func BindActivityDirectory(ctx *papp.AppCtx, id, name string) error {
	return pdb.GetGormDB().WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var rows []model.Photo
		err := tx.Where("activity_id = ? OR (activity_id = '' AND timeline = ?)", id, name).Find(&rows).Error
		if err != nil {
			return err
		}
		for _, row := range rows {
			if row.ActivityID == id && row.Timeline == name {
				continue
			}
			err = tx.Model(&model.Photo{}).Where("id = ?", row.ID).
				Updates(map[string]any{"activity_id": id, "timeline": name}).Error
			if err != nil {
				return err
			}
			if row.Timeline == name {
				continue
			}
			var state model.PhotoArchive
			err = tx.Where("photo_id = ?", row.ID).Find(&state).Error
			if err != nil {
				return err
			}
			if state.ImportKey != "" {
				key := ArchiveImportKey(name, state.JPGSHA256, state.NEFSHA256)
				err = tx.Model(&state).Update("import_key", key).Error
				if err != nil {
					return err
				}
			}
		}
		var items []model.PhotoRecycle
		err = tx.Where("state <> ?", "purged").Find(&items).Error
		if err != nil {
			return err
		}
		for _, item := range items {
			var photo model.Photo
			err = json.Unmarshal(item.PhotoJSON, &photo)
			if err != nil {
				return err
			}
			if photo.ActivityID != id && !(photo.ActivityID == "" && photo.Timeline == name) {
				continue
			}
			previousName := photo.Timeline
			photo.ActivityID, photo.Timeline = id, name
			photo.FilePath = filepath.Join(name, photo.Filename)
			item.PhotoJSON, err = json.Marshal(photo)
			if err != nil {
				return err
			}
			var files []map[string]any
			err = json.Unmarshal(item.FilesJSON, &files)
			if err != nil {
				return err
			}
			for _, file := range files {
				for _, key := range []string{"original", "restore"} {
					path, ok := file[key].(string)
					if ok && strings.HasPrefix(path, previousName+"/") {
						file[key] = name + strings.TrimPrefix(path, previousName)
					}
				}
			}
			item.FilesJSON, err = json.Marshal(files)
			if err != nil {
				return err
			}
			err = tx.Save(&item).Error
			if err != nil {
				return err
			}
			var state model.PhotoArchive
			err = tx.Where("photo_id = ?", photo.ID).Find(&state).Error
			if err != nil {
				return err
			}
			if state.ImportKey != "" {
				err = tx.Model(&state).Update("import_key", ArchiveImportKey(name, state.JPGSHA256, state.NEFSHA256)).Error
				if err != nil {
					return err
				}
			}
		}
		return nil
	})
}

// ActivityMetadataSeed carries historical user metadata only for the first scan.
func ActivityMetadataSeed(ctx *papp.AppCtx, name string) (string, string, error) {
	var rows []model.Photo
	err := pdb.GetGormDB().WithContext(ctx).
		Where("timeline = ? OR substr(file_path, 1, instr(file_path, '/') - 1) = ?", name, name).
		Find(&rows).Error
	if err != nil {
		return "", "", err
	}
	date, legacy := "", ""
	for _, row := range rows {
		if row.ShotAt.Year() >= 2000 {
			candidate := row.ShotAt.Format("2006-01-02")
			if date == "" || candidate < date {
				date = candidate
			}
		}
		if legacy == "" {
			legacy = row.Timeline
		} else if legacy != row.Timeline {
			legacy = name
		}
	}
	if legacy != "" {
		var events []model.TimelineEvent
		err = pdb.GetGormDB().WithContext(ctx).Where("event = ?", legacy).Find(&events).Error
		if err != nil {
			return "", "", err
		}
		if len(events) == 1 {
			return events[0].EventDate.Format("2006-01-02"), events[0].Note, nil
		}
	}
	return date, "", nil
}

// RetireLegacyTimelineEvents removes the obsolete live copy after metadata has
// been materialized and every directory has reconciled successfully.
func RetireLegacyTimelineEvents(ctx *papp.AppCtx) error {
	var count int64
	db := pdb.GetGormDB().WithContext(ctx)
	err := db.Model(&model.TimelineEvent{}).Count(&count).Error
	if err != nil || count == 0 {
		return err
	}
	return db.Where("1 = 1").Delete(&model.TimelineEvent{}).Error
}

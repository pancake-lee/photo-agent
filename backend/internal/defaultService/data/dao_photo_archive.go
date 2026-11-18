package data

import (
	"errors"
	"path/filepath"
	"time"

	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type PhotoArchiveDO = model.PhotoArchive
type PhotoRecycleDO = model.PhotoRecycle

func (*photoDAO) FindArchivedImport(ctx *papp.AppCtx, key string) (*PhotoArchiveDO, error) {
	var row PhotoArchiveDO
	err := pdb.GetGormDB().WithContext(ctx).Where("import_key = ?", key).Take(&row).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &row, err
}

func (*photoDAO) FindByArchivePath(ctx *papp.AppCtx, path string) (*PhotoDO, error) {
	var row PhotoDO
	err := pdb.GetGormDB().WithContext(ctx).
		Where("timeline = ? AND filename = ? COLLATE NOCASE", archiveFolder(path), filepath.Base(path)).Take(&row).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &row, err
}

func (*photoDAO) GetArchiveState(ctx *papp.AppCtx, id string) (PhotoArchiveDO, error) {
	row := PhotoArchiveDO{PhotoID: id}
	err := pdb.GetGormDB().WithContext(ctx).Take(&row).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return row, nil
	}
	return row, err
}

func (*photoDAO) FindImportReservation(
	ctx *papp.AppCtx, key, normalizedTarget string,
) (*model.PhotoImportReservation, error) {
	var row model.PhotoImportReservation
	query := pdb.GetGormDB().WithContext(ctx)
	if normalizedTarget != "" {
		query = query.Where("target = ? COLLATE NOCASE", normalizedTarget)
	} else {
		query = query.Where("import_key = ?", key)
	}
	err := query.Take(&row).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &row, err
}

func (*photoDAO) ReserveImportTarget(ctx *papp.AppCtx, key, target string) error {
	row := model.PhotoImportReservation{Target: target, ImportKey: key}
	err := pdb.GetGormDB().WithContext(ctx).Clauses(clause.OnConflict{DoNothing: true}).
		Create(&row).Error
	return err
}

func (*photoDAO) SaveVerifiedImport(
	ctx *papp.AppCtx, row *PhotoDO, state PhotoArchiveDO, existing bool,
) error {
	return pdb.GetGormDB().WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if !existing {
			err := tx.Create(row).Error
			if err != nil {
				return err
			}
		}
		err := tx.Clauses(clause.OnConflict{UpdateAll: true}).Create(&state).Error
		if err != nil {
			return err
		}
		return tx.Delete(&model.PhotoImportReservation{}, "import_key = ?", state.ImportKey).Error
	})
}

func (*photoDAO) SetArchiveFavorite(ctx *papp.AppCtx, id string, value bool) error {
	state := PhotoArchiveDO{PhotoID: id, Favorite: value}
	return pdb.GetGormDB().WithContext(ctx).Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "photo_id"}},
		DoUpdates: clause.Assignments(map[string]any{"favorite": value}),
	}).Create(&state).Error
}

// GetPhotoFavoriteStatus reads page favorites and complete group counts in bulk.
func (*photoDAO) GetPhotoFavoriteStatus(ctx *papp.AppCtx, ids, groupIDs []string,
	profile string,
) (map[string]bool, map[string]int32, error) {
	favorites := make(map[string]bool)
	counts := make(map[string]int32)
	g := pdb.GetGormDB().WithContext(ctx)
	if len(ids) > 0 {
		var states []PhotoArchiveDO
		err := g.Select("photo_id", "favorite").Where("photo_id IN ?", ids).Find(&states).Error
		if err != nil {
			return nil, nil, err
		}
		for _, state := range states {
			favorites[state.PhotoID] = state.Favorite
		}
	}
	if len(groupIDs) > 0 {
		column := "burst_group_id"
		if profile == "coarse" {
			column = "burst_group_coarse_id"
		}
		var rows []struct {
			GroupID string
			Count   int32
		}
		err := g.Table("photos").
			Select("photos."+column+" AS group_id, COUNT(*) AS count").
			Joins("JOIN photo_archives ON photo_archives.photo_id = photos.id").
			Where("photos."+column+" IN ? AND photo_archives.favorite = ? AND photos.file_type <> ?",
				groupIDs, true, "nef").Group("photos." + column).Scan(&rows).Error
		if err != nil {
			return nil, nil, err
		}
		for _, row := range rows {
			counts[row.GroupID] = row.Count
		}
	}
	return favorites, counts, nil
}

func (*photoDAO) ListArchiveActivity(ctx *papp.AppCtx, activity string) ([]PhotoDO, error) {
	var rows []PhotoDO
	err := pdb.GetGormDB().WithContext(ctx).
		Where("timeline = ? AND file_type <> ?", activity, "nef").
		Order("filename").Find(&rows).Error
	return rows, err
}

func (*photoDAO) SaveRecycle(ctx *papp.AppCtx, item *PhotoRecycleDO) error {
	return pdb.GetGormDB().WithContext(ctx).Save(item).Error
}

func (*photoDAO) FindRecycle(ctx *papp.AppCtx, id string) (*PhotoRecycleDO, error) {
	var item PhotoRecycleDO
	err := pdb.GetGormDB().WithContext(ctx).Take(&item, "id = ?", id).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &item, err
}

func (*photoDAO) FindPhotoRecycle(ctx *papp.AppCtx, id, kind string) (*PhotoRecycleDO, error) {
	var item PhotoRecycleDO
	err := pdb.GetGormDB().WithContext(ctx).
		Where("photo_id = ? AND kind = ?", id, kind).Take(&item).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return &item, err
}

func (*photoDAO) ListRecycle(ctx *papp.AppCtx) ([]PhotoRecycleDO, error) {
	items := make([]PhotoRecycleDO, 0)
	err := pdb.GetGormDB().WithContext(ctx).
		Order("deleted_at DESC, id DESC").Find(&items).Error
	return items, err
}

func (*photoDAO) FinishRecycle(ctx *papp.AppCtx, item *PhotoRecycleDO) error {
	return pdb.GetGormDB().WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if item.Kind == "photo" {
			err := tx.Delete(&model.Photo{}, "id = ?", item.PhotoID).Error
			if err != nil {
				return err
			}
		}
		return tx.Save(item).Error
	})
}

func (*photoDAO) FinishRecycleRestore(
	ctx *papp.AppCtx, item *PhotoRecycleDO, photo *PhotoDO,
) error {
	return pdb.GetGormDB().WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if item.Kind == "photo" {
			err := tx.Create(photo).Error
			if err != nil {
				return err
			}
		}
		return tx.Delete(item).Error
	})
}

func (*photoDAO) PurgeRecycle(ctx *papp.AppCtx, item *PhotoRecycleDO) error {
	return pdb.GetGormDB().WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if item.Kind == "photo" {
			err := tx.Delete(&model.PhotoArchive{}, "photo_id = ?", item.PhotoID).Error
			if err != nil {
				return err
			}
			err = tx.Exec("DELETE FROM ai_processing_history WHERE photo_id = ?", item.PhotoID).Error
			if err != nil {
				return err
			}
			// Retain the identity for index cleanup and historical links.
			item.State, item.LastError = "purged", ""
			item.PhotoJSON, item.FilesJSON = nil, nil
			return tx.Save(item).Error
		}
		return tx.Delete(item).Error
	})
}

func (*photoDAO) ListDeletedPhotoIDs(ctx *papp.AppCtx, purgedOnly bool) ([]string, error) {
	ids := make([]string, 0)
	states := []string{"deleted", "restoring", "purged"}
	if purgedOnly {
		states = []string{"purged"}
	}
	err := pdb.GetGormDB().WithContext(ctx).Model(&model.PhotoRecycle{}).
		Where("kind = ? AND state IN ?", "photo", states).
		Pluck("photo_id", &ids).Error
	return ids, err
}

func (*photoDAO) ListRecycleWork(ctx *papp.AppCtx, cutoff time.Time) ([]PhotoRecycleDO, error) {
	items := make([]PhotoRecycleDO, 0)
	err := pdb.GetGormDB().WithContext(ctx).
		Where("state IN ? OR (state = ? AND deleted_at <= ?)",
			[]string{"moving", "restoring"}, "deleted", cutoff).
		Find(&items).Error
	return items, err
}

func archiveFolder(path string) string {
	folder := filepath.Dir(path)
	if folder == "." {
		return ""
	}
	return folder
}

// FindCompatibleArchivedImport reuses the same JPG when a favorites-only
// import omits an already archived NEF, or a later import adds that NEF.
// Ambiguous copies are left to normal path conflict resolution.
func (*photoDAO) FindCompatibleArchivedImport(ctx *papp.AppCtx, activity, jpg, nef string) (*PhotoArchiveDO, error) {
	var rows []PhotoArchiveDO
	query := pdb.GetGormDB().WithContext(ctx).Table("photo_archives").
		Select("photo_archives.*").Joins("JOIN photos ON photos.id = photo_archives.photo_id").
		Where("photos.timeline = ? AND photo_archives.jpgsha256 = ?", activity, jpg)
	if nef != "" {
		query = query.Where("photo_archives.nefsha256 IN ?", []string{"", nef})
	}
	err := query.Limit(2).Find(&rows).Error
	if err != nil {
		return nil, err
	}
	if len(rows) != 1 {
		return nil, nil
	}
	return &rows[0], nil
}

// ForgetMissingPhoto keeps a purge tombstone so the existing index lifecycle
// can remove vectors without recreating an externally deleted original.
func ForgetMissingPhoto(ctx *papp.AppCtx, id string) error {
	if id == "" {
		return errors.New("照片 ID 不能为空")
	}
	return pdb.GetGormDB().WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		err := tx.Delete(&model.Photo{}, "id = ?", id).Error
		if err != nil {
			return err
		}
		err = tx.Delete(&model.PhotoArchive{}, "photo_id = ?", id).Error
		if err != nil {
			return err
		}
		err = tx.Exec("DELETE FROM ai_processing_history WHERE photo_id = ?", id).Error
		if err != nil {
			return err
		}
		item := model.PhotoRecycle{ID: "missing-photo-" + id, PhotoID: id, Kind: "photo", State: "purged", DeletedAt: time.Now().UTC()}
		return tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&item).Error
	})
}

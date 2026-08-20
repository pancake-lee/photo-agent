package data

import (
	"fmt"
	"time"

	"backend/internal/pkg/db"
	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/papp"
	"gorm.io/gorm/clause"
)

// validShotAtFloor shot_at 有效下界，早于该时间视为零值/异常记录，不参与分组。
var validShotAtFloor = time.Date(2000, 1, 1, 0, 0, 0, 0, time.UTC)

// GetBurstPhotos 按拍摄时间升序返回参与连拍分组的照片候选。
// 跳过 shot_at 零值与 NEF（无缩略图）记录，不参与分组。
func (*photoDAO) GetBurstPhotos(ctx *papp.AppCtx) ([]*model.Photo, error) {
	q := db.GetQuery().Photo
	photos, err := q.WithContext(ctx).
		Where(q.FileType.Neq("nef")).
		Where(q.ShotAt.Gt(validShotAtFloor)).
		Order(q.ShotAt.Asc(), q.ImportedAt.Asc()).
		Find()
	if err != nil {
		return nil, fmt.Errorf("query burst photos failed: %w", err)
	}
	return photos, nil
}

// ClearAllBurstGroups 清空全部分组数据：photos.burst_group_id 置空 + photo_groups 整表删除。
// rebuild 重算前调用，由本函数保证两张表清理的一致性。
func (*photoGroupDAO) ClearAllBurstGroups(ctx *papp.AppCtx) error {
	q := db.GetQuery()
	if _, err := q.Photo.WithContext(ctx).
		Where(q.Photo.BurstGroupID.Neq("")).
		Update(q.Photo.BurstGroupID, ""); err != nil {
		return fmt.Errorf("clear photos burst_group_id failed: %w", err)
	}
	if _, err := q.PhotoGroup.WithContext(ctx).
		Where(q.PhotoGroup.ID.Neq("")).
		Delete(); err != nil {
		return fmt.Errorf("clear photo_groups failed: %w", err)
	}
	return nil
}

// AddBurstGroupList 批量写入连拍组记录。
func (*photoGroupDAO) AddBurstGroupList(ctx *papp.AppCtx, groups []*PhotoGroupDO) error {
	if len(groups) == 0 {
		return nil
	}
	q := db.GetQuery().PhotoGroup
	if err := q.WithContext(ctx).Clauses(clause.OnConflict{UpdateAll: true}).
		Create(groups...); err != nil {
		return fmt.Errorf("create photo_groups failed: %w", err)
	}
	return nil
}

// SetPhotosBurstGroup 批量回填照片的 burst_group_id。
func (*photoDAO) SetPhotosBurstGroup(ctx *papp.AppCtx, photoIDList []string, groupID string) error {
	if len(photoIDList) == 0 {
		return nil
	}
	q := db.GetQuery().Photo
	if _, err := q.WithContext(ctx).
		Where(q.ID.In(photoIDList...)).
		Update(q.BurstGroupID, groupID); err != nil {
		return fmt.Errorf("set photos burst_group_id failed: %w", err)
	}
	return nil
}

// CountPhotoGroups 返回当前连拍组总数。
func (*photoGroupDAO) CountPhotoGroups(ctx *papp.AppCtx) (int64, error) {
	q := db.GetQuery().PhotoGroup
	n, err := q.WithContext(ctx).Count()
	if err != nil {
		return 0, fmt.Errorf("count photo_groups failed: %w", err)
	}
	return n, nil
}

// GetBurstGroupIDList 返回全部分组 id 集合，用于封面/数量拼装。
func (*photoGroupDAO) GetBurstGroupIDList(ctx *papp.AppCtx) ([]string, error) {
	q := db.GetQuery().PhotoGroup
	var idList []string
	if err := q.WithContext(ctx).
		Pluck(q.ID, &idList); err != nil {
		return nil, fmt.Errorf("pluck photo_group ids failed: %w", err)
	}
	return idList, nil
}

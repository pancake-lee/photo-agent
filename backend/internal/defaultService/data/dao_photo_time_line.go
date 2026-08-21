package data

import (
	"time"

	"backend/internal/pkg/db"
	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/papp"
)

// GetPhotosByTimeline 根据时间线查询照片
func (*photoDAO) GetPhotosByTimeline(ctx *papp.AppCtx, timeline string) ([]*model.Photo, error) {
	q := db.GetQuery().Photo
	photos, err := q.WithContext(ctx).
		Where(q.Timeline.Eq(timeline)).
		Order(q.ShotAt.Desc(), q.ImportedAt.Desc()).
		Find()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return photos, nil
}

// GetDistinctTimelineList 查询所有不重复的时间线
func (*photoDAO) GetDistinctTimelineList(ctx *papp.AppCtx) ([]string, error) {
	q := db.GetQuery().Photo
	var timelines []string
	err := q.WithContext(ctx).
		Where(q.Timeline.Neq("")).
		Distinct().
		Pluck(q.Timeline, &timelines)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return timelines, nil
}

// GetAllPhotosOrderByShotAt 全量照片按拍摄时间升序（timeline 重算用）。
// shot_at 零值记录（0001 年）排最前，重算时单独跳过。
func (*photoDAO) GetAllPhotosOrderByShotAt(ctx *papp.AppCtx) ([]*model.Photo, error) {
	q := db.GetQuery().Photo
	photos, err := q.WithContext(ctx).
		Order(q.ShotAt.Asc(), q.ImportedAt.Asc()).
		Find()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return photos, nil
}

// UpdateShotAt 更新单张照片的拍摄时间（仅 shot_at，不动 timeline）。
func (*photoDAO) UpdateShotAt(ctx *papp.AppCtx, photoID string, shotAt time.Time) error {
	q := db.GetQuery().Photo
	_, err := q.WithContext(ctx).
		Where(q.ID.Eq(photoID)).
		Updates(map[string]any{"shot_at": shotAt})
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

// UpdatePhotoTimeline 更新单张照片的 timeline（manual 标记人工指定）。
func (*photoDAO) UpdatePhotoTimeline(ctx *papp.AppCtx, photoID, timeline string, manual bool) error {
	q := db.GetQuery().Photo
	_, err := q.WithContext(ctx).
		Where(q.ID.Eq(photoID)).
		Updates(map[string]any{
			"timeline":        timeline,
			"timeline_manual": manual,
		})
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

// UpdatePhotosTimelineBatch 批量更新照片 timeline 并清 manual 标记（重算写回用）。
func (*photoDAO) UpdatePhotosTimelineBatch(ctx *papp.AppCtx, photoIDList []string, timeline string) error {
	if len(photoIDList) == 0 {
		return nil
	}
	q := db.GetQuery().Photo
	_, err := q.WithContext(ctx).
		Where(q.ID.In(photoIDList...)).
		Updates(map[string]any{
			"timeline":        timeline,
			"timeline_manual": 0,
		})
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

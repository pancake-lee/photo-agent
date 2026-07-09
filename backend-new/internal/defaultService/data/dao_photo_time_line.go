package data

import (
	"backend-new/internal/pkg/db"
	"backend-new/internal/pkg/db/model"

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

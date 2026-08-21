package data

import (
	"fmt"

	"backend/internal/pkg/db"

	"github.com/pancake-lee/pgo/pkg/papp"
)

// GetTimelineEventsOrderByDate 全部时间线事件按日期升序。
func (*timelineEventDAO) GetTimelineEventsOrderByDate(ctx *papp.AppCtx) ([]*TimelineEventDO, error) {
	q := db.GetQuery().TimelineEvent
	events, err := q.WithContext(ctx).
		Order(q.EventDate.Asc()).
		Find()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return events, nil
}

// CountTimelineEvents 事件总数（JSON 一次性导入的「表空」判定用）。
func (*timelineEventDAO) CountTimelineEvents(ctx *papp.AppCtx) (int64, error) {
	q := db.GetQuery().TimelineEvent
	n, err := q.WithContext(ctx).Count()
	if err != nil {
		return 0, fmt.Errorf("count timeline_events failed: %w", err)
	}
	return n, nil
}

// AddTimelineEventList 批量写入时间线事件（JSON 迁移用）。
func (*timelineEventDAO) AddTimelineEventList(ctx *papp.AppCtx, events []*TimelineEventDO) error {
	if len(events) == 0 {
		return nil
	}
	q := db.GetQuery().TimelineEvent
	if err := q.WithContext(ctx).Create(events...); err != nil {
		return fmt.Errorf("create timeline_events failed: %w", err)
	}
	return nil
}

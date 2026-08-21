package service

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"
)

// TimelineEntry 时间线中的单条事件（DB timeline_events 表记录的内存形态）
type TimelineEntry struct {
	Date  time.Time
	Event string
}

// scatteredNamePrefix 散片时间线名前缀特征（YYYY-MM-散片N）
const scatteredNamePart = "-散片"

// isScatteredName 判断 timeline 值是否为散片组名（YYYY-MM-散片N）。
func isScatteredName(name string) bool {
	if !strings.Contains(name, scatteredNamePart) {
		return false
	}
	parts := strings.Split(name, scatteredNamePart)
	if len(parts) != 2 {
		return false
	}
	// 前半段须为 YYYY-MM
	if len(parts[0]) != 7 || parts[0][4] != '-' {
		return false
	}
	// 后半段须为纯数字序号
	for _, c := range parts[1] {
		if c < '0' || c > '9' {
			return false
		}
	}
	return parts[1] != ""
}

// --------------------------------------------------
// loadTimeline 从 timeline_events 表加载时间线事件，按日期升序。
// 首次调用时若表为空且 JSON 文件存在，执行一次性导入后 JSON 退役。
func loadTimeline(ctx *papp.AppCtx) ([]TimelineEntry, error) {
	events, err := data.TimelineEventDAO.GetTimelineEventsOrderByDate(ctx)
	if err != nil {
		return nil, err
	}

	// 表空且 JSON 存在：一次性导入（幂等，导入成功后 JSON 不再读取）
	if len(events) == 0 {
		imported, err := importTimelineFromJSON(ctx, conf.C.Storage.TimelinePath)
		if err != nil {
			plogger.Warnf("Import timeline JSON failed: %v", err)
			return nil, nil
		}
		if imported > 0 {
			events, err = data.TimelineEventDAO.GetTimelineEventsOrderByDate(ctx)
			if err != nil {
				return nil, err
			}
			plogger.Infof("Timeline JSON migrated: %d entries imported, JSON file retired", imported)
		}
	}

	entries := make([]TimelineEntry, len(events))
	for i, e := range events {
		entries[i] = TimelineEntry{Date: e.EventDate, Event: e.Event}
	}
	return entries, nil
}

// importTimelineFromJSON 从旧版 timeline.json 导入事件到 DB，返回导入条数。
// JSON 格式：[[dateStr, event], ...]，dateStr 为 YYMMDD 格式（如 "250309"），
// "none" 表示散图（跳过）。
func importTimelineFromJSON(ctx *papp.AppCtx, path string) (int, error) {
	if path == "" {
		return 0, nil
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return 0, nil
		}
		return 0, fmt.Errorf("read timeline JSON failed: %w", err)
	}

	entries, err := parseTimelineJSON(raw)
	if err != nil {
		return 0, err
	}
	if len(entries) == 0 {
		return 0, nil
	}

	now := time.Now()
	dos := make([]*data.TimelineEventDO, len(entries))
	for i, e := range entries {
		dos[i] = &data.TimelineEventDO{
			ID:        putil.UUID(),
			EventDate: e.Date,
			Event:     e.Event,
			CreatedAt: now,
			UpdatedAt: now,
		}
	}
	if err := data.TimelineEventDAO.AddTimelineEventList(ctx, dos); err != nil {
		return 0, err
	}
	return len(dos), nil
}

// parseTimelineJSON 解析旧版 JSON，跳过 "none" / 空日期 / 解析失败的条目，按日期排序返回。
func parseTimelineJSON(raw []byte) ([]TimelineEntry, error) {
	var rows [][2]string
	if err := json.Unmarshal(raw, &rows); err != nil {
		return nil, fmt.Errorf("parse timeline JSON failed: %w", err)
	}

	const dateFormat = "060102" // YYMMDD

	var entries []TimelineEntry
	for _, row := range rows {
		dateStr := row[0]
		event := strings.TrimSpace(row[1])

		if dateStr == "none" || dateStr == "" || event == "" {
			continue
		}

		t, err := time.ParseInLocation(dateFormat, dateStr, time.Local)
		if err != nil {
			plogger.Warnf("Skip timeline entry with invalid date %q: %v", dateStr, err)
			continue
		}

		entries = append(entries, TimelineEntry{Date: t, Event: event})
	}

	if len(entries) > 0 {
		sort.Slice(entries, func(i, j int) bool { return entries[i].Date.Before(entries[j].Date) })
	}

	return entries, nil
}

// endOfDay 返回 t 所在日期的 23:59:59
func endOfDay(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 23, 59, 59, 0, t.Location())
}

// --------------------------------------------------
// findEventByTime 根据拍摄时间和窗口天数，从时间线条目列表中匹配活动。
// 算法：排序后，活动 i 的时间段为 [date_i − D, right_i]，其中
// right_i = min(midpoint(date_i, date_{i+1}), date_i + D)，
// 最后一个活动为 date_last + D。D = windowDays。
func findEventByTime(t time.Time, entries []TimelineEntry, windowDays int) string {
	if len(entries) == 0 {
		return ""
	}

	// 防御性排序（GetTimelineEventsOrderByDate 已排序，此处保证顺序正确）
	sorted := make([]TimelineEntry, len(entries))
	copy(sorted, entries)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].Date.Before(sorted[j].Date) })

	win := time.Duration(windowDays) * 24 * time.Hour
	local := t.Local()
	date := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, local.Location())

	for i := range sorted {
		left := sorted[i].Date.Add(-win)

		var right time.Time
		if i < len(sorted)-1 {
			midpoint := sorted[i].Date.Add(sorted[i+1].Date.Sub(sorted[i].Date) / 2)
			maxRight := sorted[i].Date.Add(win)
			if midpoint.Before(maxRight) {
				right = midpoint
			} else {
				right = maxRight
			}
		} else {
			right = sorted[i].Date.Add(win)
		}
		right = endOfDay(right)

		if !date.Before(left) && !date.After(right) {
			return sorted[i].Event
		}
	}
	return ""
}

// --------------------------------------------------
// 散片分组（纯函数，单测覆盖）
// --------------------------------------------------

// scatteredPhoto 散片分组算法的单张照片输入
type scatteredPhoto struct {
	PhotoID string
	ShotAt  time.Time
}

// scatteredGroup 散片分组结果：一组连续散片共享同一散片名
type scatteredGroup struct {
	Name    string    // YYYY-MM-散片N
	StartAt time.Time // 组内首张拍摄时间
	IDList  []string
}

// splitScatteredPhotos 散片分组：按时间排序的照片中，事件匹配不上的散片串，
// 按月份切开分段，每段命名 YYYY-MM-散片N（N 为该月内散片段序号，从 1 递增）。
//
// 与 findEventByTime 的窗口语义对齐：活动 i 的覆盖区间为 [date_i − D, right_i]，
// 散片串即活动之间的空隙；首活动之前与末活动之后的散片同样成串。
func splitScatteredPhotos(photos []scatteredPhoto, entries []TimelineEntry, windowDays int) []scatteredGroup {
	if len(photos) == 0 {
		return nil
	}

	sorted := make([]scatteredPhoto, len(photos))
	copy(sorted, photos)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].ShotAt.Before(sorted[j].ShotAt) })

	// 散片串：连续（相邻活动区间之间）匹配不上事件的照片
	type run struct {
		photos []scatteredPhoto
	}
	var runs []run
	var cur run
	for _, p := range sorted {
		if findEventByTime(p.ShotAt, entries, windowDays) == "" {
			cur.photos = append(cur.photos, p)
		} else {
			if len(cur.photos) > 0 {
				runs = append(runs, cur)
				cur = run{}
			}
		}
	}
	if len(cur.photos) > 0 {
		runs = append(runs, cur)
	}

	// 每串内按月份切开，月内序号 N 按时间递增
	monthCounter := make(map[string]int) // YYYY-MM → 已分配段数
	var groups []scatteredGroup
	for _, r := range runs {
		// 串内按月分段
		var monthRuns [][]scatteredPhoto
		var mr []scatteredPhoto
		for i, p := range r.photos {
			if i > 0 && monthOf(p.ShotAt) != monthOf(r.photos[i-1].ShotAt) {
				monthRuns = append(monthRuns, mr)
				mr = nil
			}
			mr = append(mr, p)
		}
		if len(mr) > 0 {
			monthRuns = append(monthRuns, mr)
		}

		for _, seg := range monthRuns {
			m := monthOf(seg[0].ShotAt)
			monthCounter[m]++
			name := fmt.Sprintf("%s%s%d", m, scatteredNamePart, monthCounter[m])
			idList := make([]string, len(seg))
			for i, p := range seg {
				idList[i] = p.PhotoID
			}
			groups = append(groups, scatteredGroup{
				Name:    name,
				StartAt: seg[0].ShotAt,
				IDList:  idList,
			})
		}
	}
	return groups
}

// monthOf 取时间的年月（本地时区）
func monthOf(t time.Time) string {
	local := t.Local()
	return fmt.Sprintf("%04d-%02d", local.Year(), int(local.Month()))
}

// newAppCtxForBackground 后台 goroutine 用的 AppCtx 构造（保持与 burst 重建一致的调用方式）
func newAppCtxForBackground() *papp.AppCtx {
	return papp.NewAppCtx(context.Background())
}

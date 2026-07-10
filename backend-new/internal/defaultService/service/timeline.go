package service

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"time"

	"github.com/pancake-lee/pgo/pkg/plogger"
)

// TimelineEntry 时间线中的单条记录（仅存储从 JSON 解析的原始日期和活动名）
type TimelineEntry struct {
	Date  time.Time
	Event string
}

var (
	timelineCache     []TimelineEntry
	timelineCachePath string
	timelineCacheTime time.Time // 文件修改时间，用于缓存失效判断
)

// --------------------------------------------------
// loadTimeline 从 JSON 文件加载时间线数据。
// JSON 格式：[[dateStr, event], ...]，dateStr 为 YYMMDD 格式（如 "250309"），
// 或 "none" 表示散图（跳过不参与匹配）。条目按日期升序排列。
// 缓存按文件修改时间判断是否失效，文件未变则直接返回缓存。
func loadTimeline(path string) ([]TimelineEntry, error) {
	if path == "" {
		return nil, nil
	}

	fi, err := os.Stat(path)
	if err != nil {
		if os.IsNotExist(err) {
			plogger.Infof("Timeline file not found: %s", path)
			timelineCache = nil
			timelineCachePath = ""
			return nil, nil
		}
		return nil, fmt.Errorf("stat timeline file failed: %w", err)
	}

	if timelineCache != nil && timelineCachePath == path && fi.ModTime().Equal(timelineCacheTime) {
		return timelineCache, nil
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read timeline file failed: %w", err)
	}

	entries, err := parseTimelineJSON(data)
	if err != nil {
		return nil, err
	}

	timelineCache = entries
	timelineCachePath = path
	timelineCacheTime = fi.ModTime()
	plogger.Infof("Loaded %d timeline entries from %s", len(entries), path)
	return entries, nil
}

// clearTimelineCache 清除时间线缓存（用于强制重载）
func clearTimelineCache() {
	timelineCache = nil
	timelineCachePath = ""
	timelineCacheTime = time.Time{}
}

// parseTimelineJSON 解析 JSON，跳过 "none" / 空日期 / 解析失败的条目，按日期排序返回。
func parseTimelineJSON(data []byte) ([]TimelineEntry, error) {
	var raw [][2]string
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("parse timeline JSON failed: %w", err)
	}

	const dateFormat = "060102" // YYMMDD

	var entries []TimelineEntry
	for _, row := range raw {
		dateStr := row[0]
		event := row[1]

		if dateStr == "none" || dateStr == "" || event == "" {
			continue
		}

		t, err := time.Parse(dateFormat, dateStr)
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

	// 防御性排序（LoadTimeline 已排序，此处保证顺序正确）
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

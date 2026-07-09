package service

import (
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/pancake-lee/pgo/pkg/plogger"
)

// TimelineEntry 时间线中的单条记录
type TimelineEntry struct {
	StartAt time.Time
	EndAt   time.Time
	Event   string
}

var timelineCache []TimelineEntry

// LoadTimeline 从 JSON 文件加载时间线数据。
// JSON 格式：[[dateStr, event], ...]，dateStr 为 YYMMDD 格式（如 "250309"）或 "none" 表示散图。
func LoadTimeline(path string) ([]TimelineEntry, error) {
	if timelineCache != nil {
		return timelineCache, nil
	}

	if path == "" {
		return nil, nil
	}

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			plogger.Infof("Timeline file not found: %s", path)
			return nil, nil
		}
		return nil, fmt.Errorf("read timeline file failed: %w", err)
	}

	entries, err := parseTimelineJSON(data)
	if err != nil {
		return nil, err
	}

	timelineCache = entries
	plogger.Infof("Loaded %d timeline entries", len(entries))
	return entries, nil
}

// FindEventByTime 根据拍摄时间匹配时间线活动
func FindEventByTime(t time.Time, timelinePath string) string {
	entries, _ := LoadTimeline(timelinePath)
	if len(entries) == 0 {
		return ""
	}

	local := t.Local()
	date := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, local.Location())

	for _, e := range entries {
		if !date.Before(e.StartAt) && !date.After(e.EndAt) {
			return e.Event
		}
	}
	return ""
}

// ClearTimelineCache 清除时间线缓存（用于重载）
func ClearTimelineCache() {
	timelineCache = nil
}

// parseTimelineJSON 解析 JSON 格式的时间线数据。
// 每条记录为 [dateStr, event]，dateStr 使用 YYMMDD 六位数字格式（如 "250309" = 2025-03-09），
// 或 "none" 表示无明确日期（跳过不参与匹配）。
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

		if dateStr == "none" || event == "" {
			continue
		}

		t, err := time.Parse(dateFormat, dateStr)
		if err != nil {
			plogger.Warnf("Skip timeline entry with invalid date %q: %v", dateStr, err)
			continue
		}

		entries = append(entries, TimelineEntry{
			StartAt: t,
			EndAt:   time.Date(t.Year(), t.Month(), t.Day(), 23, 59, 59, 0, t.Location()),
			Event:   event,
		})
	}

	return entries, nil
}

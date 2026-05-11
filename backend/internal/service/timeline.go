package service

import (
	"bufio"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

// TimelineEntry 时间线单条记录
type TimelineEntry struct {
	StartAt time.Time
	EndAt   time.Time
	Event   string
}

var timelineCache []TimelineEntry

// LoadTimeline 加载时间线文件并解析
func LoadTimeline() ([]TimelineEntry, error) {
	if timelineCache != nil {
		return timelineCache, nil
	}

	path := config.Get().Storage.TimelinePath
	if path == "" {
		return nil, nil
	}

	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			plogger.Infof("Timeline file not found: %s", path)
			return nil, nil
		}
		return nil, fmt.Errorf("open timeline file failed: %w", err)
	}
	defer f.Close()

	var entries []TimelineEntry
	scanner := bufio.NewScanner(f)
	var header []string
	var timeIdx, eventIdx = -1, -1

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if !strings.HasPrefix(line, "|") {
			continue
		}

		cells := parseMarkdownTableRow(line)
		if len(cells) == 0 {
			continue
		}

		// 分隔行
		if isTableSeparator(cells) {
			continue
		}

		// 表头
		if timeIdx == -1 {
			header = cells
			for i, h := range header {
				h = strings.TrimSpace(h)
				if h == "时间" {
					timeIdx = i
				}
				if h == "活动" {
					eventIdx = i
				}
			}
			if timeIdx == -1 || eventIdx == -1 {
				return nil, fmt.Errorf("timeline table missing '时间' or '活动' column")
			}
			continue
		}

		if timeIdx >= len(cells) || eventIdx >= len(cells) {
			continue
		}

		timeStr := strings.TrimSpace(cells[timeIdx])
		eventStr := strings.TrimSpace(cells[eventIdx])
		if timeStr == "" || eventStr == "" {
			continue
		}

		start, end, err := parseTimeRange(timeStr)
		if err != nil {
			plogger.Warnf("Parse timeline time failed '%s': %v", timeStr, err)
			continue
		}

		entries = append(entries, TimelineEntry{
			StartAt: start,
			EndAt:   end,
			Event:   eventStr,
		})
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read timeline file failed: %w", err)
	}

	timelineCache = entries
	plogger.Infof("Loaded %d timeline entries", len(entries))
	return entries, nil
}

// FindEventByTime 根据时间查找对应活动
func FindEventByTime(t time.Time) string {
	entries, err := LoadTimeline()
	if err != nil || len(entries) == 0 {
		return ""
	}

	// 统一转换为本地时区，取日期零点（Truncate 基于 UTC 零点，时区不一致会导致偏差）
	local := t.In(time.Local)
	date := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.Local)
	for _, e := range entries {
		if !date.Before(e.StartAt) && !date.After(e.EndAt) {
			return e.Event
		}
	}
	return ""
}

// ClearTimelineCache 清除时间线缓存
func ClearTimelineCache() {
	timelineCache = nil
}

func parseMarkdownTableRow(line string) []string {
	line = strings.TrimSpace(line)
	if !strings.HasPrefix(line, "|") {
		return nil
	}
	parts := strings.Split(line, "|")
	var cells []string
	for i, p := range parts {
		if i == 0 || i == len(parts)-1 {
			continue // 忽略首尾空元素
		}
		cells = append(cells, p)
	}
	return cells
}

func isTableSeparator(cells []string) bool {
	for _, c := range cells {
		c = strings.TrimSpace(c)
		if c == "" {
			continue
		}
		// 允许包含 - 和 : 的格式如 :---: 或 ------
		trimmed := strings.Trim(c, "-:")
		if trimmed != "" {
			return false
		}
	}
	return true
}

func parseTimeRange(s string) (time.Time, time.Time, error) {
	s = strings.TrimSpace(s)

	// 范围格式：2024-01-01 ~ 2024-01-03
	if idx := strings.Index(s, "~"); idx > 0 {
		startStr := strings.TrimSpace(s[:idx])
		endStr := strings.TrimSpace(s[idx+1:])
		start, _, err := parseDate(startStr)
		if err != nil {
			return time.Time{}, time.Time{}, err
		}
		end, _, err := parseDate(endStr)
		if err != nil {
			return time.Time{}, time.Time{}, err
		}
		return start, end, nil
	}

	// 单日格式
	start, end, err := parseDate(s)
	if err != nil {
		return time.Time{}, time.Time{}, err
	}
	return start, end, nil
}

func parseDate(s string) (time.Time, time.Time, error) {
	s = strings.TrimSpace(s)
	layouts := []string{
		"2006-01-02",
		"2006-01-02 15:04",
		"2006-01-02 15:04:05",
		"2006-01",
		"2006/01/02",
		"060102", // yyMMdd 简写格式，如 250309 → 2025-03-09
	}
	for _, layout := range layouts {
		if t, err := time.ParseInLocation(layout, s, time.Local); err == nil {
			// 月份精度时，范围设为整月
			if layout == "2006-01" {
				start := time.Date(t.Year(), t.Month(), 1, 0, 0, 0, 0, time.Local)
				end := start.AddDate(0, 1, 0).Add(-time.Second)
				return start, end, nil
			}
			return t, t, nil
		}
	}
	return time.Time{}, time.Time{}, fmt.Errorf("unsupported date format: %s", s)
}

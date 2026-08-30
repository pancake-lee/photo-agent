package service

import (
	"testing"
	"time"
)

// mkEntry 构造时间线事件
func mkEntry(date string) TimelineEntry {
	t, _ := time.ParseInLocation("2006-01-02", date, time.Local)
	return TimelineEntry{Date: t, Event: "事件-" + date}
}

// mkScatteredPhoto 构造散片候选照片
func mkScatteredPhoto(id, shotAt string) scatteredPhoto {
	t, _ := time.ParseInLocation("2006-01-02 15:04", shotAt, time.Local)
	return scatteredPhoto{PhotoID: id, ShotAt: t}
}

func TestIsScatteredName(t *testing.T) {
	cases := []struct {
		name string
		want bool
	}{
		{"2026-08-散片1", true},
		{"2026-08-散片12", true},
		{"2026-8-散片1", false},      // 月份非两位
		{"202608-散片1", false},      // 无月分隔
		{"2026-08-散片a", false},     // 序号非数字
		{"2026-08-散片", false},      // 无序号
		{"兰圃", false},              // 普通事件名
		{"散片-2026-08", false},      // 顺序错
		{"2026-08-散片1-散片2", false}, // 多段
	}
	for _, c := range cases {
		if got := isScatteredName(c.name); got != c.want {
			t.Errorf("isScatteredName(%q) = %v, want %v", c.name, got, c.want)
		}
	}
}

func TestSplitScatteredPhotos(t *testing.T) {
	windowDays := 7
	entries := []TimelineEntry{
		mkEntry("2026-05-10"),
		mkEntry("2026-06-20"),
	}

	// 事件 2026-05-10 覆盖约 [05-03, 05-16]（含与下一事件的中点截断），
	// 事件 2026-06-20 覆盖约 [06-13, 06-27]。
	photos := []scatteredPhoto{
		// 事件 1 之前
		mkScatteredPhoto("p1", "2026-05-01 10:00"),
		// 事件 1 与事件 2 之间跨两个月：5 月尾巴 + 6 月头
		mkScatteredPhoto("p2", "2026-05-20 10:00"),
		mkScatteredPhoto("p3", "2026-05-28 10:00"),
		mkScatteredPhoto("p4", "2026-06-05 10:00"),
		mkScatteredPhoto("p5", "2026-06-10 10:00"),
		// 事件 2 之后
		mkScatteredPhoto("p6", "2026-07-15 10:00"),
		// 命中事件 1（窗口内），不算散片
		mkScatteredPhoto("h1", "2026-05-12 10:00"),
		// 命中事件 2（窗口内）
		mkScatteredPhoto("h2", "2026-06-21 10:00"),
	}

	groups := splitScatteredPhotos(photos, entries, windowDays)
	if len(groups) != 4 {
		t.Fatalf("groups = %d, want 4（事件前 / 5 月尾 / 6 月头 / 事件后）, got %+v", len(groups), groups)
	}

	wantNames := []string{"2026-05-散片1", "2026-05-散片2", "2026-06-散片1", "2026-07-散片1"}
	wantCounts := []int{1, 2, 2, 1}
	for i, g := range groups {
		if g.Name != wantNames[i] {
			t.Errorf("group[%d].Name = %q, want %q", i, g.Name, wantNames[i])
		}
		if len(g.IDList) != wantCounts[i] {
			t.Errorf("group[%d] size = %d, want %d", i, len(g.IDList), wantCounts[i])
		}
	}
}

func TestSplitScatteredPhotosEmpty(t *testing.T) {
	if got := splitScatteredPhotos(nil, []TimelineEntry{mkEntry("2026-05-10")}, 7); got != nil {
		t.Errorf("empty photos should return nil, got %+v", got)
	}
	// 无事件时全部照片都是散片
	groups := splitScatteredPhotos(
		[]scatteredPhoto{mkScatteredPhoto("p1", "2026-05-01 10:00")},
		nil, 7,
	)
	if len(groups) != 1 || groups[0].Name != "2026-05-散片1" {
		t.Errorf("no-event groups = %+v, want single 2026-05-散片1", groups)
	}
}

func TestSplitScatteredPhotosCrossYearAndMonthlySequence(t *testing.T) {
	entries := []TimelineEntry{
		mkEntry("2026-12-15"),
		mkEntry("2027-01-15"),
		mkEntry("2027-01-25"),
	}
	photos := []scatteredPhoto{
		mkScatteredPhoto("dec", "2026-12-28 10:00"),
		mkScatteredPhoto("jan1", "2027-01-05 10:00"),
		mkScatteredPhoto("hit", "2027-01-15 10:00"),
		mkScatteredPhoto("jan2", "2027-01-20 10:00"),
	}

	groups := splitScatteredPhotos(photos, entries, 3)
	wantNames := []string{"2026-12-散片1", "2027-01-散片1", "2027-01-散片2"}
	if len(groups) != len(wantNames) {
		t.Fatalf("groups = %d, want %d: %+v", len(groups), len(wantNames), groups)
	}
	for i, want := range wantNames {
		if groups[i].Name != want {
			t.Errorf("group[%d].Name = %q, want %q", i, groups[i].Name, want)
		}
	}
}

func TestFindEventByTimeWindow(t *testing.T) {
	windowDays := 7
	entries := []TimelineEntry{
		{Date: dateOf("2026-05-10"), Event: "活动A"},
		{Date: dateOf("2026-06-20"), Event: "活动B"},
	}

	cases := []struct {
		shotAt string
		want   string
	}{
		{"2026-05-10 12:00", "活动A"}, // 活动当天
		{"2026-05-05 12:00", "活动A"}, // 前 5 天
		{"2026-05-17 12:00", "活动A"}, // 后 7 天（同月无下一事件，min(中点, +7d)）
		{"2026-06-21 12:00", "活动B"}, // 活动B 当天
		{"2026-05-30 12:00", ""},    // 两活动之间空隙
		{"2024-01-01 12:00", ""},    // 远早于所有活动
	}
	for _, c := range cases {
		got := findEventByTime(shotAtOf(c.shotAt), entries, windowDays)
		if got != c.want {
			t.Errorf("findEventByTime(%q) = %q, want %q", c.shotAt, got, c.want)
		}
	}
}

// dateOf / shotAtOf 测试辅助
func dateOf(s string) time.Time {
	t, _ := time.ParseInLocation("2006-01-02", s, time.Local)
	return t
}

func shotAtOf(s string) time.Time {
	t, _ := time.ParseInLocation("2006-01-02 15:04", s, time.Local)
	return t
}

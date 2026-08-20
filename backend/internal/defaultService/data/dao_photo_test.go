package data

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
)

// setupTestDB 在临时 SQLite 中建 photos 表并插入测试数据。
// 返回 AppCtx 与清理函数。
func setupTestDB(t *testing.T) (*papp.AppCtx, func()) {
	t.Helper()

	tmpDir := t.TempDir()
	if err := pdb.InitSqlite(filepath.Join(tmpDir, "test.db")); err != nil {
		t.Fatalf("init sqlite failed: %v", err)
	}
	g := pdb.GetGormDB()
	if err := g.Migrator().CreateTable(&model.Photo{}); err != nil {
		t.Fatalf("create photos table failed: %v", err)
	}

	ctx := papp.NewAppCtx(context.Background())
	return ctx, func() {
		if db, err := g.DB(); err == nil && db != nil {
			db.Close()
		}
	}
}

// addPhoto 插入一条非 NEF 测试照片
func addPhoto(t *testing.T, ctx *papp.AppCtx, id, timeline string, shotAt time.Time) {
	t.Helper()
	if err := PhotoDAO.Add(ctx, &model.Photo{
		ID:       id,
		Filename: id + ".jpg",
		FilePath: "/" + id + ".jpg",
		FileType: "jpg",
		Timeline: timeline,
		ShotAt:   shotAt,
	}); err != nil {
		t.Fatalf("add photo %s failed: %v", id, err)
	}
}

func TestGetPhotoList_TimelineNoneSentinel(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()

	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)
	addPhoto(t, ctx, "p1", "2026-08-云南", base)
	addPhoto(t, ctx, "p2", "", base.Add(time.Hour))
	addPhoto(t, ctx, "p3", "2026-07-川西", base.Add(2*time.Hour))
	addPhoto(t, ctx, "p4", "", base.Add(3*time.Hour))

	cases := []struct {
		name     string
		timeline string
		wantIDs  []string
	}{
		{"空串不过滤", "", []string{"p1", "p2", "p3", "p4"}},
		{"sentinel 只取散图", TimelineNoneSentinel, []string{"p2", "p4"}},
		{"普通活动名精确匹配", "2026-08-云南", []string{"p1"}},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			photos, total, err := PhotoDAO.GetPhotoList(ctx, GetPhotoListParams{
				Page:      1,
				PageSize:  20,
				Timeline:  c.timeline,
				SortBy:    "shot_at",
				SortOrder: "asc",
			})
			if err != nil {
				t.Fatalf("GetPhotoList failed: %v", err)
			}
			if total != int64(len(c.wantIDs)) {
				t.Errorf("total = %d, want %d", total, len(c.wantIDs))
			}
			gotIDs := make([]string, 0, len(photos))
			for _, p := range photos {
				gotIDs = append(gotIDs, p.ID)
			}
			if len(gotIDs) != len(c.wantIDs) {
				t.Fatalf("got %v, want %v", gotIDs, c.wantIDs)
			}
			for i := range gotIDs {
				if gotIDs[i] != c.wantIDs[i] {
					t.Errorf("got %v, want %v", gotIDs, c.wantIDs)
					break
				}
			}
		})
	}
}

func TestGetPhotoList_TimelineNoneSentinelExcludesNEF(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()

	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)
	addPhoto(t, ctx, "p1", "", base)
	// NEF 原始文件即使无活动标签也不参与列表展示
	if err := PhotoDAO.Add(ctx, &model.Photo{
		ID:       "n1",
		Filename: "n1.nef",
		FilePath: "/n1.nef",
		FileType: "nef",
		Timeline: "",
		ShotAt:   base.Add(time.Hour),
	}); err != nil {
		t.Fatalf("add nef failed: %v", err)
	}

	photos, _, err := PhotoDAO.GetPhotoList(ctx, GetPhotoListParams{
		Page:     1,
		PageSize: 20,
		Timeline: TimelineNoneSentinel,
	})
	if err != nil {
		t.Fatalf("GetPhotoList failed: %v", err)
	}
	if len(photos) != 1 || photos[0].ID != "p1" {
		gotIDs := make([]string, 0, len(photos))
		for _, p := range photos {
			gotIDs = append(gotIDs, p.ID)
		}
		t.Errorf("got %v, want [p1]", gotIDs)
	}
}

func TestListPhotoSegments_Month(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()

	// 三张有拍摄时间、一张零值拍摄时间、一张 NEF
	addPhoto(t, ctx, "p1", "act-a", time.Date(2026, 8, 10, 0, 0, 0, 0, time.UTC))
	addPhoto(t, ctx, "p2", "act-a", time.Date(2026, 8, 11, 0, 0, 0, 0, time.UTC))
	addPhoto(t, ctx, "p3", "act-b", time.Date(2026, 7, 20, 0, 0, 0, 0, time.UTC))
	addPhoto(t, ctx, "p4", "act-b", time.Date(2026, 7, 21, 0, 0, 0, 0, time.UTC))
	addPhoto(t, ctx, "p5", "", time.Time{}) // 零值，不进导航
	if err := PhotoDAO.Add(ctx, &model.Photo{
		ID:       "n1",
		Filename: "n1.nef",
		FilePath: "/n1.nef",
		FileType: "nef",
		Timeline: "act-a",
		ShotAt:   time.Date(2026, 8, 12, 0, 0, 0, 0, time.UTC),
	}); err != nil {
		t.Fatalf("add nef failed: %v", err)
	}

	segments, total, err := PhotoDAO.ListPhotoSegments(ctx, GetPhotoListParams{
		SortBy:    "shot_at",
		SortOrder: "asc",
	}, SegmentModeMonth)
	if err != nil {
		t.Fatalf("ListPhotoSegments failed: %v", err)
	}

	// total 含零值照片（其在完整列表中占一个位置），不含 NEF
	if total != 5 {
		t.Errorf("total = %d, want 5", total)
	}
	if len(segments) != 2 {
		t.Fatalf("segments = %d, want 2", len(segments))
	}
	// 零值照片排首位（asc），July 首张位于完整列表 index 1
	if segments[0].Key != "2026-07" || segments[0].Offset != 1 || segments[0].Count != 2 {
		t.Errorf("seg0 = %+v, want key=2026-07 offset=1 count=2", segments[0])
	}
	if segments[0].Label != "2026 年 7 月" {
		t.Errorf("seg0 label = %q, want \"2026 年 7 月\"", segments[0].Label)
	}
	if segments[1].Key != "2026-08" || segments[1].Offset != 3 || segments[1].Count != 2 {
		t.Errorf("seg1 = %+v, want key=2026-08 offset=3 count=2", segments[1])
	}
}

func TestListPhotoSegments_Activity(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()

	addPhoto(t, ctx, "p1", "act-a", time.Date(2026, 8, 1, 0, 0, 0, 0, time.UTC))
	addPhoto(t, ctx, "p2", "", time.Date(2026, 8, 2, 0, 0, 0, 0, time.UTC))
	addPhoto(t, ctx, "p3", "act-b", time.Date(2026, 8, 3, 0, 0, 0, 0, time.UTC))
	addPhoto(t, ctx, "p4", "act-a", time.Date(2026, 8, 4, 0, 0, 0, 0, time.UTC))
	addPhoto(t, ctx, "p5", "", time.Time{}) // 零值 + 空 timeline，不进导航

	segments, total, err := PhotoDAO.ListPhotoSegments(ctx, GetPhotoListParams{
		SortBy:    "shot_at",
		SortOrder: "asc",
	}, SegmentModeActivity)
	if err != nil {
		t.Fatalf("ListPhotoSegments failed: %v", err)
	}

	if total != 5 {
		t.Errorf("total = %d, want 5", total)
	}
	// 未分类（空 timeline）排最后，其余按首现顺序
	if len(segments) != 3 {
		t.Fatalf("segments = %d, want 3", len(segments))
	}
	if segments[0].Key != "act-a" || segments[0].Offset != 1 || segments[0].Count != 2 {
		t.Errorf("seg0 = %+v, want key=act-a offset=1 count=2", segments[0])
	}
	if segments[1].Key != "act-b" || segments[1].Offset != 3 || segments[1].Count != 1 {
		t.Errorf("seg1 = %+v, want key=act-b offset=3 count=1", segments[1])
	}
	if segments[2].Key != "" || segments[2].Label != "未分类" || segments[2].Offset != 2 || segments[2].Count != 1 {
		t.Errorf("seg2 = %+v, want key=\"\" label=未分类 offset=2 count=1", segments[2])
	}
}

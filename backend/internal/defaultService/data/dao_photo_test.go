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

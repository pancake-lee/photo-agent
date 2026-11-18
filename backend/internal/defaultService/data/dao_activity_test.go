package data

import (
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/pdb"
)

func TestRebindEmptyActivityRecycleRollsBackUnfinishedRecord(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()
	g := pdb.GetGormDB()
	var before []byte
	for i, state := range []string{"deleted", "moving"} {
		photo := model.Photo{ID: state, ActivityID: "source", Timeline: "旧活动", Filename: state + ".jpg"}
		raw, err := json.Marshal(photo)
		if err != nil {
			t.Fatal(err)
		}
		if i == 0 {
			before = raw
		}
		item := model.PhotoRecycle{ID: state, PhotoID: state, Kind: "photo", State: state,
			PhotoJSON: raw, FilesJSON: []byte(`[{"original":"旧活动/image.jpg"}]`), DeletedAt: time.Now()}
		if err = g.Create(&item).Error; err != nil {
			t.Fatal(err)
		}
	}
	_, err := RebindEmptyActivityRecycle(ctx, "source", "旧活动", "target", "目标活动")
	if err == nil {
		t.Fatal("unfinished recycle record accepted")
	}
	item, err := PhotoDAO.FindRecycle(ctx, "deleted")
	if err != nil || string(item.PhotoJSON) != string(before) || item.State != "deleted" {
		t.Fatalf("partial rebind committed: %+v %v", item, err)
	}
}

func TestLegacyActivityLocationMigrationPreservesIdentityAndProcessing(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()
	g := pdb.GetGormDB()
	original := &model.Photo{ID: "old-photo", Filename: "same.JPG", Timeline: "旧活动别名", Description: "保留描述", EmbeddingStatus: "healthy"}
	err := PhotoDAO.Add(ctx, original)
	if err != nil {
		t.Fatal(err)
	}
	// Only legacy fixtures write this retired column, through the existing schema.
	err = g.Table("photos").Where("id = ?", original.ID).Update("file_path", "202601-活动/same.JPG").Error
	if err != nil {
		t.Fatal(err)
	}
	err = MigratePhotoLocations(ctx)
	if err != nil {
		t.Fatal(err)
	}
	row, err := PhotoDAO.GetByID(ctx, original.ID)
	if err != nil || row.Timeline != "202601-活动" || row.Description != original.Description || row.EmbeddingStatus != "healthy" || row.FilePath != filepath.Join(row.Timeline, row.Filename) {
		t.Fatalf("migrated: %+v %v", row, err)
	}
	var retired string
	err = g.Table("photos").Where("id = ?", row.ID).Pluck("file_path", &retired).Error
	if err != nil || retired != "" {
		t.Fatalf("path was persisted: %q %v", retired, err)
	}
	err = BindActivityDirectory(ctx, "activity-id", "202601-活动")
	if err != nil {
		t.Fatal(err)
	}
	err = BindActivityDirectory(ctx, "activity-id", "202601-改名")
	if err != nil {
		t.Fatal(err)
	}
	row, err = PhotoDAO.GetByID(ctx, row.ID)
	if err != nil || row.Timeline != "202601-改名" || row.ActivityID != "activity-id" || row.Description != original.Description {
		t.Fatalf("bound: %+v %v", row, err)
	}
	found, err := PhotoDAO.FindByArchivePath(ctx, "202601-改名/SAME.jpg")
	if err != nil || found == nil || found.ID != row.ID {
		t.Fatalf("case-insensitive path lookup: %+v %v", found, err)
	}
	found, err = PhotoDAO.FindByArchivePath(ctx, "202601-别的活动/same.JPG")
	if err != nil || found != nil {
		t.Fatal("lookup crossed activity boundary")
	}
}

func TestLegacyActivityLocationMigrationRollsBackInvalidPath(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()
	for _, id := range []string{"a-good", "z-bad"} {
		err := PhotoDAO.Add(ctx, &model.Photo{ID: id, Filename: id + ".jpg", Timeline: "原值"})
		if err != nil {
			t.Fatal(err)
		}
	}
	g := pdb.GetGormDB()
	err := g.Table("photos").Where("id = ?", "a-good").Update("file_path", "活动/a.jpg").Error
	if err != nil {
		t.Fatal(err)
	}
	err = g.Table("photos").Where("id = ?", "z-bad").Update("file_path", "../outside.jpg").Error
	if err != nil {
		t.Fatal(err)
	}
	if err = MigratePhotoLocations(ctx); err == nil {
		t.Fatal("unsafe legacy path accepted")
	}
	row, err := PhotoDAO.GetByID(ctx, "a-good")
	if err != nil || row.Timeline != "原值" {
		t.Fatalf("partial migration leaked: %+v %v", row, err)
	}
}

func TestNewActivityDoesNotAdoptRecycledRootPhoto(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()
	raw, err := json.Marshal(&model.Photo{ID: "root-photo", Filename: "root.jpg", FilePath: "root.jpg"})
	if err != nil {
		t.Fatal(err)
	}
	item := &PhotoRecycleDO{ID: "root-recycle", PhotoID: "root-photo", Kind: "photo", State: "deleted", PhotoJSON: raw, FilesJSON: []byte(`[]`)}
	err = PhotoDAO.SaveRecycle(ctx, item)
	if err != nil {
		t.Fatal(err)
	}
	err = BindActivityDirectory(ctx, "new-activity-id", "新活动")
	if err != nil {
		t.Fatal(err)
	}
	saved, err := PhotoDAO.FindRecycle(ctx, item.ID)
	if err != nil {
		t.Fatal(err)
	}
	if string(saved.PhotoJSON) != string(raw) {
		t.Fatal("unrelated root photo was adopted by a new activity")
	}
}

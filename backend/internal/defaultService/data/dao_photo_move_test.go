package data

import (
	"encoding/json"
	"testing"
	"time"

	"backend/internal/pkg/db/model"
	"github.com/pancake-lee/pgo/pkg/pdb"
)

func TestActivityMovePreservesResultsAndSplitsGroups(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()
	g := pdb.GetGormDB()
	base := time.Date(2026, 8, 1, 0, 0, 0, 0, time.UTC)
	for i, id := range []string{"p1", "p2", "p3", "p4"} {
		fine := "fine"
		if id == "p4" {
			fine = ""
		}
		err := PhotoDAO.Add(ctx, &PhotoDO{ID: id, ActivityID: "old", Timeline: "旧活动",
			Filename: id + ".JPG", FileType: "jpg", Description: "保留描述",
			EmbeddingStatus: "healthy", DescriptionTime: "version",
			BurstGroupID: fine, BurstGroupCoarseID: "coarse", ShotAt: base.Add(time.Duration(i) * time.Second)})
		if err != nil {
			t.Fatal(err)
		}
	}
	for _, group := range []model.PhotoGroup{
		{ID: "fine", Profile: "fine", CoverPhotoID: "p1", PhotoCount: 3},
		{ID: "coarse", Profile: "coarse", CoverPhotoID: "p1", PhotoCount: 4},
	} {
		if err := g.Create(&group).Error; err != nil {
			t.Fatal(err)
		}
	}
	for profile, want := range map[string]int{"all": 1, "fine": 3, "coarse": 4} {
		rows, err := ListPhotosForActivityMove(ctx, []string{"p1"}, profile)
		if err != nil || len(rows) != want {
			t.Fatalf("expand %s: %d, %v", profile, len(rows), err)
		}
	}
	rows, err := ListPhotosForActivityMove(ctx, []string{"p2"}, "coarse")
	if err != nil || len(rows) != 1 {
		t.Fatalf("non-cover expanded: %d %v", len(rows), err)
	}
	_, err = ListPhotosForActivityMove(ctx, []string{"missing"}, "all")
	if err == nil {
		t.Fatal("missing selection accepted")
	}
	state := model.PhotoArchive{PhotoID: "p1", ImportKey: "old-key", Favorite: true, JPGSHA256: "jpg", NEFSHA256: "nef"}
	if err = g.Create(&state).Error; err != nil {
		t.Fatal(err)
	}
	photo, _ := PhotoDAO.GetByID(ctx, "p1")
	photoJSON, _ := json.Marshal(photo)
	filesJSON := []byte(`[{"original":"旧活动/p1.NEF","sha256":"nef"}]`)
	recycle := model.PhotoRecycle{ID: "recycled-nef", PhotoID: "p1", Kind: "nef", State: "deleted", PhotoJSON: photoJSON, FilesJSON: filesJSON}
	if err = g.Create(&recycle).Error; err != nil {
		t.Fatal(err)
	}
	moves := []PhotoActivityMove{
		{PhotoID: "p1", FromActivityID: "old", FromTimeline: "旧活动", FromFilename: "p1.JPG", ActivityID: "new", Timeline: "新活动", Filename: "p1 (2).JPG"},
		{PhotoID: "p2", FromActivityID: "old", FromTimeline: "旧活动", FromFilename: "p2.JPG", ActivityID: "new", Timeline: "新活动", Filename: "p2.JPG"},
	}
	if err = MovePhotosActivity(ctx, moves); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"p1", "p2"} {
		row, getErr := PhotoDAO.GetByID(ctx, id)
		if getErr != nil || row.Timeline != "新活动" || row.ActivityID != "new" ||
			row.Description != "保留描述" || row.EmbeddingStatus != "healthy" || row.DescriptionTime != "version" || row.BurstGroupID != "fine" {
			t.Fatalf("moved identity/results: %+v %v", row, getErr)
		}
	}
	p3, _ := PhotoDAO.GetByID(ctx, "p3")
	p4, _ := PhotoDAO.GetByID(ctx, "p4")
	if p3.BurstGroupID != "" || p3.BurstGroupCoarseID == "coarse" ||
		p3.BurstGroupCoarseID == "" || p3.BurstGroupCoarseID != p4.BurstGroupCoarseID {
		t.Fatalf("remaining groups: %+v %+v", p3, p4)
	}
	var fine model.PhotoGroup
	if err = g.Take(&fine, "id = ?", "fine").Error; err != nil || fine.PhotoCount != 2 || fine.CoverPhotoID != "p1" {
		t.Fatalf("split group: %+v %v", fine, err)
	}
	gotState, _ := PhotoDAO.GetArchiveState(ctx, "p1")
	if !gotState.Favorite || gotState.ImportKey != ArchiveImportKey("新活动", "jpg", "nef") {
		t.Fatalf("archive metadata: %+v", gotState)
	}
	var retired string
	if err = g.Table("photos").Where("id = ?", "p1").Pluck("file_path", &retired).Error; err != nil || retired != "" {
		t.Fatalf("retired path stored: %q %v", retired, err)
	}
	item, _ := PhotoDAO.FindRecycle(ctx, "recycled-nef")
	var files []map[string]any
	if err = json.Unmarshal(item.FilesJSON, &files); err != nil || files[0]["original"] != "旧活动/p1.NEF" || files[0]["restore"] != "新活动/p1 (2).NEF" {
		t.Fatalf("recycled NEF location: %s %v", item.FilesJSON, err)
	}
}

func TestActivityMoveTransactionRollsBack(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()
	addPhoto(t, ctx, "one", "old", time.Time{})
	move := PhotoActivityMove{PhotoID: "one", FromTimeline: "old", FromFilename: "one.jpg", Timeline: "new", ActivityID: "new", Filename: "one.jpg"}
	missing := move
	missing.PhotoID = "missing"
	err := MovePhotosActivity(ctx, []PhotoActivityMove{move, missing})
	if err == nil {
		t.Fatal("missing second photo accepted")
	}
	row, _ := PhotoDAO.GetByID(ctx, "one")
	if row.Timeline != "old" {
		t.Fatalf("partial database update: %+v", row)
	}
}

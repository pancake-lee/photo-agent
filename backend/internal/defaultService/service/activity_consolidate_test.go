package service

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"
)

func TestConsolidateEmptyActivityPreservesPriorDeletionAndRestore(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	photo := moveTestPair(t, ctx, "旧活动")
	_, err := (&PhotoServer{}).DeletePhoto(ctx, &api.DeletePhotoRequest{Id: photo.PhotoID})
	if err != nil {
		t.Fatal(err)
	}
	before, err := data.PhotoDAO.FindPhotoRecycle(ctx, photo.PhotoID, "photo")
	if err != nil || before == nil {
		t.Fatal(err)
	}
	_, filesBefore, err := recycleData(before)
	if err != nil {
		t.Fatal(err)
	}
	var contents [][]byte
	for _, file := range filesBefore {
		body, readErr := os.ReadFile(recycleFilePath(before.ID, file))
		if readErr != nil {
			t.Fatal(readErr)
		}
		contents = append(contents, body)
	}
	target, err := (&TimelineServer{}).SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "目标活动"})
	if err != nil {
		t.Fatal(err)
	}
	backup := t.TempDir()
	if err = ConsolidateEmptyActivity(ctx, "旧活动", "目标活动", backup); err != nil {
		t.Fatal(err)
	}
	after, err := data.PhotoDAO.FindRecycle(ctx, before.ID)
	if err != nil || after.State != before.State || !after.DeletedAt.Equal(before.DeletedAt) {
		t.Fatalf("deletion changed: %+v %v", after, err)
	}
	row, filesAfter, err := recycleData(after)
	if err != nil || row.ActivityID != target.Id || row.Timeline != "目标活动" {
		t.Fatalf("restore metadata: %+v %v", row, err)
	}
	for i, file := range filesAfter {
		body, readErr := os.ReadFile(recycleFilePath(after.ID, file))
		if readErr != nil || string(body) != string(contents[i]) {
			t.Fatalf("recycled file changed: %s %v", file.Original, readErr)
		}
	}
	if _, err = data.PhotoDAO.GetByID(ctx, photo.PhotoID); err == nil {
		t.Fatal("consolidation restored a deleted photo")
	}
	for _, root := range []string{conf.C.Storage.PhotoSrc, conf.C.Storage.PhotoPath} {
		if _, err = os.Stat(filepath.Join(root, "旧活动")); !os.IsNotExist(err) {
			t.Fatalf("old directory remains: %s", root)
		}
	}
	if err = restorePhotoRecycle(ctx, before.ID, time.Now()); err != nil {
		t.Fatal(err)
	}
	restored, err := data.PhotoDAO.GetByID(ctx, photo.PhotoID)
	if err != nil || restored.ActivityID != target.Id || restored.Timeline != "目标活动" {
		t.Fatalf("restored location: %+v %v", restored, err)
	}
	nef, err := photoPairNEF(ctx, restored)
	if err != nil || nef.Original == "" {
		t.Fatalf("restored NEF missing: %+v %v", nef, err)
	}
}

func TestConsolidateEmptyActivityRefusesLiveFiles(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	_, photo := importActivityTestPhoto(t, ctx, "旧活动", true)
	_, err := (&TimelineServer{}).SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "目标活动"})
	if err != nil {
		t.Fatal(err)
	}
	if err = ConsolidateEmptyActivity(ctx, "旧活动", "目标活动", t.TempDir()); err == nil {
		t.Fatal("nonempty activity consolidated")
	}
	row, err := data.PhotoDAO.GetByID(ctx, photo.PhotoID)
	if err != nil || row.Timeline != "旧活动" {
		t.Fatalf("live photo changed: %+v %v", row, err)
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, row.FilePath)); err != nil {
		t.Fatal(err)
	}
}

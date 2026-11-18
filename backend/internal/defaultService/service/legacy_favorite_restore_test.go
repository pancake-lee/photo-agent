package service

import (
	"context"
	"encoding/json"
	"fmt"
	"image"
	"image/jpeg"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
)

func writeLegacyRestorePlan(t *testing.T, root string, plan legacyFavoritePlan) string {
	t.Helper()
	path := filepath.Join(root, "plan.json")
	raw, err := json.Marshal(plan)
	if err != nil {
		t.Fatal(err)
	}
	err = os.WriteFile(path, raw, 0600)
	if err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLegacyFavoriteRestorePreservesIdentityAndIsRetryable(t *testing.T) {
	ctx, root := setupUserPathTest(t)
	jpg := archiveTestJPG(t, 42)
	source := filepath.Join(root, "legacy.JPG")
	err := os.WriteFile(source, jpg, 0600)
	if err != nil {
		t.Fatal(err)
	}
	req := archiveTestRequest("202508-旧活动", jpg, nil, true)
	date := time.Date(2025, 8, 9, 12, 0, 0, 0, time.FixedZone("CST", 8*3600))
	description := "城市街景\n```json\n{\"scene\":\"街头\",\"image_integrity\":\"normal\"}\n```"
	photo := data.PhotoDO{ID: "legacy-photo", ShotAt: date, ImportedAt: date, Description: description, DescriptionModel: "old-model"}
	plan := legacyFavoritePlan{Version: 1, SourceRoot: root, Activities: []legacyActivity{{Name: req.Activity, Date: date.Format(time.RFC3339), Note: "旧备注"}}, Entries: []legacyFavoriteEntry{{Source: source, SourceName: "legacy.JPG", SHA256: req.JPG, Activity: req.Activity, Filename: "legacy.JPG", Photo: photo}}}
	path := writeLegacyRestorePlan(t, root, plan)
	report := filepath.Join(root, "report.json")
	err = RestoreLegacyFavorites(ctx, path, report, false, io.Discard)
	if err != nil {
		t.Fatal(err)
	}
	saved, err := data.PhotoDAO.GetByID(ctx, photo.ID)
	if err != nil || !saved.ShotAt.Equal(date) || !saved.ImportedAt.Equal(date) || saved.Description != "" {
		t.Fatalf("restore: %+v %v", saved, err)
	}
	state, err := data.PhotoDAO.GetArchiveState(ctx, photo.ID)
	if err != nil || !state.Favorite || state.JPGSHA256 != req.JPG {
		t.Fatalf("archive: %+v %v", state, err)
	}
	meta, err := readActivityMetadata(req.Activity)
	if err != nil || meta.Note != "旧备注" {
		t.Fatalf("metadata: %+v %v", meta, err)
	}
	err = RestoreLegacyFavorites(ctx, path, report, true, io.Discard)
	if err != nil {
		t.Fatal(err)
	}
	all, err := data.PhotoDAO.GetAll(ctx)
	if err != nil || len(all) != 1 || all[0].Description != description {
		t.Fatalf("retry/inherit: %+v %v", all, err)
	}
	// A stopped run can publish files before its SQLite transaction commits.
	err = data.PhotoDAO.DelByID(ctx, photo.ID)
	if err != nil {
		t.Fatal(err)
	}
	err = RestoreLegacyFavorites(ctx, path, report, true, io.Discard)
	if err != nil {
		t.Fatal(err)
	}
	for _, base := range []string{conf.C.Storage.PhotoSrc, conf.C.Storage.PhotoPath} {
		actual, _, readErr := digestFile(filepath.Join(base, req.Activity, "legacy.JPG"))
		if readErr != nil || actual != req.JPG {
			t.Fatalf("changed file at %s: %s %v", base, actual, readErr)
		}
	}
}

func TestLegacyFavoriteMergeKeepsExistingPhotoAndNEF(t *testing.T) {
	ctx, root := setupUserPathTest(t)
	req, result := importActivityTestPhoto(t, ctx, "202602-已有活动", false)
	row, err := data.PhotoDAO.GetByID(ctx, result.PhotoID)
	if err != nil {
		t.Fatal(err)
	}
	source := filepath.Join(root, "favorite.JPG")
	jpg := archiveTestJPG(t, 51)
	err = os.WriteFile(source, jpg, 0600)
	if err != nil {
		t.Fatal(err)
	}
	nefPath := filepath.Join(conf.C.Storage.PhotoSrc, req.Activity, "DSC_0123.nef")
	err = os.WriteFile(nefPath, []byte("existing raw"), 0600)
	if err != nil {
		t.Fatal(err)
	}
	before, err := data.PhotoDAO.GetArchiveState(ctx, row.ID)
	if err != nil {
		t.Fatal(err)
	}
	before.NEFSHA256 = "keep-this-pair"
	err = data.PhotoDAO.SaveVerifiedImport(ctx, row, before, true)
	if err != nil {
		t.Fatal(err)
	}
	plan := legacyFavoritePlan{Version: 1, SourceRoot: root, Activities: []legacyActivity{{Name: req.Activity}}, Entries: []legacyFavoriteEntry{{Source: source, SourceName: "favorite.JPG", SHA256: req.JPG, Activity: req.Activity, Filename: "favorite.JPG", Photo: data.PhotoDO{ID: "old-id"}, MatchPhotoIDs: []string{row.ID}}}}
	path := writeLegacyRestorePlan(t, root, plan)
	err = RestoreLegacyFavorites(context.Background(), path, filepath.Join(root, "report.json"), false, io.Discard)
	if err != nil {
		t.Fatal(err)
	}
	after, err := data.PhotoDAO.GetArchiveState(ctx, row.ID)
	if err != nil || !after.Favorite || after.ImportKey != before.ImportKey || after.NEFSHA256 != before.NEFSHA256 {
		t.Fatalf("merge replaced manifest: %+v %v", after, err)
	}
	raw, err := os.ReadFile(nefPath)
	if err != nil || string(raw) != "existing raw" {
		t.Fatal("NEF changed")
	}
	all, err := data.PhotoDAO.GetAll(ctx)
	if err != nil || len(all) != 1 {
		t.Fatal("merged source created a duplicate")
	}
}

func TestLegacyFavoriteRestoreRejectsChangedSource(t *testing.T) {
	ctx, root := setupUserPathTest(t)
	source := filepath.Join(root, "changed.JPG")
	err := os.WriteFile(source, archiveTestJPG(t, 60), 0600)
	if err != nil {
		t.Fatal(err)
	}
	plan := legacyFavoritePlan{Version: 1, SourceRoot: root, Activities: []legacyActivity{{Name: "202505-活动"}}, Entries: []legacyFavoriteEntry{{Source: source, SourceName: "changed.JPG", SHA256: fmt.Sprintf("%064d", 0), Activity: "202505-活动", Filename: "changed.JPG", Photo: data.PhotoDO{ID: "changed"}}}}
	path := writeLegacyRestorePlan(t, root, plan)
	err = RestoreLegacyFavorites(ctx, path, filepath.Join(root, "report.json"), false, io.Discard)
	if err == nil {
		t.Fatal("changed source accepted")
	}
	photos, lookupErr := data.PhotoDAO.GetAll(ctx)
	if lookupErr != nil || len(photos) != 0 {
		t.Fatal("failed source was committed")
	}
}

func TestLegacyPreviewDownsamplesWithoutChangingOriginal(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "camera.jpg")
	file, err := os.Create(source)
	if err != nil {
		t.Fatal(err)
	}
	err = jpeg.Encode(file, image.NewRGBA(image.Rect(0, 0, 1600, 1200)), nil)
	closeErr := file.Close()
	if err != nil || closeErr != nil {
		t.Fatalf("fixture: %v %v", err, closeErr)
	}
	before, _, err := digestFile(source)
	if err != nil {
		t.Fatal(err)
	}
	previewRoot := filepath.Join(root, "previews")
	err = prepareLegacyPreview(context.Background(), source, "small.jpg", previewRoot, 1)
	if err != nil {
		t.Fatal(err)
	}
	width, height := getImageSize(filepath.Join(previewRoot, "small.jpg"))
	if width != 512 || height != 384 {
		t.Fatalf("preview dimensions: %dx%d", width, height)
	}
	after, _, err := digestFile(source)
	if err != nil || before != after {
		t.Fatal("preview preparation changed original")
	}
}

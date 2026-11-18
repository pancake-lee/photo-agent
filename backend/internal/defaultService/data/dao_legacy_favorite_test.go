package data

import (
	"backend/internal/pkg/db/model"
	"testing"
)

func TestRestoredFavoriteKeepsLiveDescriptionAndPairManifest(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()
	current := &model.Photo{ID: "live-photo", Filename: "live.jpg", Timeline: "activity", Description: "live description"}
	original := PhotoArchiveDO{PhotoID: current.ID, ImportKey: "original-key", JPGSHA256: "original-jpg", NEFSHA256: "original-nef"}
	err := PhotoDAO.SaveVerifiedImport(ctx, current, original, false)
	if err != nil {
		t.Fatal(err)
	}
	source := &model.Photo{ID: current.ID, Description: "legacy description"}
	created, inherited, err := SaveRestoredFavorite(ctx, source, PhotoArchiveDO{ImportKey: "do-not-replace"}, true)
	if err != nil || created || inherited {
		t.Fatalf("merge: %v %v %v", created, inherited, err)
	}
	saved, err := PhotoDAO.GetByID(ctx, current.ID)
	if err != nil || saved.Description != current.Description {
		t.Fatalf("live metadata replaced: %+v %v", saved, err)
	}
	state, err := PhotoDAO.GetArchiveState(ctx, current.ID)
	if err != nil || !state.Favorite || state.ImportKey != original.ImportKey || state.NEFSHA256 != original.NEFSHA256 {
		t.Fatalf("manifest replaced: %+v %v", state, err)
	}
	_, _, err = SaveRestoredFavorite(ctx, &model.Photo{ID: "missing"}, PhotoArchiveDO{}, true)
	if err == nil {
		t.Fatal("missing merge target was recreated")
	}
}

func TestForgetMissingPhotoKeepsPurgeIdentity(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()
	row := &model.Photo{ID: "externally-deleted", Filename: "gone.jpg"}
	state := PhotoArchiveDO{PhotoID: row.ID, Favorite: true}
	err := PhotoDAO.SaveVerifiedImport(ctx, row, state, false)
	if err != nil {
		t.Fatal(err)
	}
	err = ForgetMissingPhoto(ctx, row.ID)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = PhotoDAO.GetByID(ctx, row.ID); err == nil {
		t.Fatal("photo still present")
	}
	after, err := PhotoDAO.GetArchiveState(ctx, row.ID)
	if err != nil || after.Favorite {
		t.Fatal("orphan archive state remains")
	}
	item, err := PhotoDAO.FindPhotoRecycle(ctx, row.ID, "photo")
	if err != nil || item == nil || item.State != "purged" {
		t.Fatalf("purge identity: %+v %v", item, err)
	}
	err = ForgetMissingPhoto(ctx, row.ID)
	if err != nil {
		t.Fatal(err)
	}
	ids, err := PhotoDAO.ListDeletedPhotoIDs(ctx, true)
	if err != nil || len(ids) != 1 || ids[0] != row.ID {
		t.Fatalf("purge retry duplicated identity: %+v %v", ids, err)
	}
}

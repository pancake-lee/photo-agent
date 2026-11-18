package data

import (
	"testing"

	"backend/internal/pkg/db/model"
)

func TestPhotoFavoriteStatusIncludesMembersOutsidePage(t *testing.T) {
	ctx, cleanup := setupTestDB(t)
	defer cleanup()
	for _, row := range []model.Photo{
		{ID: "cover", Filename: "cover.jpg", Timeline: "活动", FileType: "jpg", BurstGroupID: "fine", BurstGroupCoarseID: "coarse"},
		{ID: "member", Filename: "member.jpg", Timeline: "活动", FileType: "jpg", BurstGroupID: "fine", BurstGroupCoarseID: "coarse"},
		{ID: "other", Filename: "other.jpg", Timeline: "活动", FileType: "jpg", BurstGroupID: "other-fine", BurstGroupCoarseID: "coarse"},
		{ID: "nef", Filename: "other.nef", Timeline: "活动", FileType: "nef", BurstGroupID: "fine", BurstGroupCoarseID: "coarse"},
	} {
		if err := PhotoDAO.Add(ctx, &row); err != nil {
			t.Fatal(err)
		}
	}
	for _, id := range []string{"member", "other", "nef", "orphan"} {
		if err := PhotoDAO.SetArchiveFavorite(ctx, id, true); err != nil {
			t.Fatal(err)
		}
	}
	for _, test := range []struct {
		profile string
		group   string
		want    int32
	}{{"fine", "fine", 1}, {"coarse", "coarse", 2}} {
		favorites, counts, err := PhotoDAO.GetPhotoFavoriteStatus(ctx,
			[]string{"cover", "member"}, []string{test.group}, test.profile)
		if err != nil || favorites["cover"] || !favorites["member"] || counts[test.group] != test.want {
			t.Fatalf("%s favorites=%v counts=%v err=%v", test.profile, favorites, counts, err)
		}
	}
	if err := PhotoDAO.SetArchiveFavorite(ctx, "member", false); err != nil {
		t.Fatal(err)
	}
	favorites, counts, err := PhotoDAO.GetPhotoFavoriteStatus(ctx, []string{"cover", "member"}, []string{"fine"}, "fine")
	if err != nil || favorites["member"] || counts["fine"] != 0 {
		t.Fatalf("cancel: %v %v %v", favorites, counts, err)
	}
}

package service

import (
	"testing"

	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"
)

func TestPhotoSearchAndDetailReturnFavorite(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	_, imported := importActivityTestPhoto(t, ctx, "收藏活动", true)
	err := data.PhotoDAO.Add(ctx, &data.PhotoDO{ID: "member", ActivityID: imported.ActivityID,
		Timeline: "收藏活动", Filename: "member.jpg", FileType: "jpg"})
	if err != nil {
		t.Fatal(err)
	}
	if err = data.PhotoDAO.SetArchiveFavorite(ctx, "member", true); err != nil {
		t.Fatal(err)
	}
	for _, profile := range []string{"fine", "coarse"} {
		group := &data.PhotoGroupDO{ID: profile, Profile: profile, CoverPhotoID: imported.PhotoID, PhotoCount: 2}
		if err = data.PhotoGroupDAO.Add(ctx, group); err != nil {
			t.Fatal(err)
		}
		if err = data.PhotoDAO.SetPhotosBurstGroup(ctx, []string{imported.PhotoID, "member"}, profile, profile); err != nil {
			t.Fatal(err)
		}
	}
	server := &PhotoServer{}
	for _, favorite := range []bool{true, false} {
		if err := data.PhotoDAO.SetArchiveFavorite(ctx, imported.PhotoID, favorite); err != nil {
			t.Fatal(err)
		}
		for _, profile := range []string{"fine", "coarse"} {
			// The favorited non-cover is outside this page but included in the group count.
			list, searchErr := server.SearchPhotos(ctx, &api.SearchPhotosRequest{
				Page: 1, PageSize: 1, SortBy: "shot_at", SortOrder: "desc", BurstProfile: profile})
			wantCount := int32(1)
			if favorite {
				wantCount++
			}
			if searchErr != nil || len(list.Items) != 1 || list.Items[0].Id != imported.PhotoID ||
				list.Items[0].Favorite != favorite || list.Items[0].GroupFavoriteCount != wantCount {
				t.Fatalf("list %s favorite=%t: %+v %v", profile, favorite, list, searchErr)
			}
		}
		detail, err := server.GetPhotoDetail(ctx, &api.GetPhotoDetailRequest{Id: imported.PhotoID})
		if err != nil || detail.Photo.Favorite != favorite {
			t.Fatalf("detail favorite=%t: %+v %v", favorite, detail, err)
		}
	}
}

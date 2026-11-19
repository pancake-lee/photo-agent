package service

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"testing"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
	"google.golang.org/protobuf/encoding/protojson"
)

func importActivityTestPhoto(t *testing.T, ctx context.Context, name string, favorite bool) (archiveImportRequest, archiveImportResult) {
	t.Helper()
	app := papp.NewAppCtx(ctx)
	jpg := archiveTestJPG(t, 51)
	req := archiveTestRequest(name, jpg, nil, favorite)
	plan, _, err := resolveArchiveImport(app, req)
	if err != nil {
		t.Fatal(err)
	}
	req.Target = plan.Target
	err = os.MkdirAll(filepath.Join(conf.C.Storage.PhotoSrc, name), 0755)
	if err != nil {
		t.Fatal(err)
	}
	err = os.WriteFile(filepath.Join(conf.C.Storage.PhotoSrc, plan.Target), jpg, 0644)
	if err != nil {
		t.Fatal(err)
	}
	result, err := finishVerifiedArchive(app, req)
	if err != nil {
		t.Fatal(err)
	}
	return req, result
}

func TestDirectoryActivitiesRenameAndFavoriteMerge(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	req, result := importActivityTestPhoto(t, ctx, "202601-旅行", false)
	server := TimelineServer{}
	events, err := server.ListEvents(ctx, &api.Empty{})
	if err != nil || len(events.Events) != 1 {
		t.Fatalf("events: %+v %v", events, err)
	}
	id := events.Events[0].Id
	renamed := "202601-旅行新名"
	_, err = server.SaveEvent(ctx, &api.SaveTimelineEventRequest{Id: id, Event: renamed, Date: "2026-01-05T12:34:56+08:00", Note: "活动备注"})
	if err != nil {
		t.Fatal(err)
	}
	row, err := data.PhotoDAO.GetByID(ctx, result.PhotoID)
	if err != nil || row.Timeline != renamed || row.FilePath != filepath.Join(renamed, row.Filename) || row.ActivityID != id {
		t.Fatalf("renamed row: %+v %v", row, err)
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoPath, row.FilePath)); err != nil {
		t.Fatal(err)
	}
	req.Activity, req.Target, req.Favorite = renamed, row.FilePath, true
	repeated, err := finishVerifiedArchive(ctx, req)
	if err != nil || repeated.PhotoID != result.PhotoID {
		t.Fatalf("dedup: %+v %v", repeated, err)
	}
	state, err := data.PhotoDAO.GetArchiveState(ctx, row.ID)
	if err != nil || !state.Favorite {
		t.Fatalf("favorite merge: %+v %v", state, err)
	}
	manual := "202601-服务器改名"
	err = os.Rename(filepath.Join(conf.C.Storage.PhotoSrc, renamed), filepath.Join(conf.C.Storage.PhotoSrc, manual))
	if err != nil {
		t.Fatal(err)
	}
	router := khttp.NewServer()
	(&PhotoServer{}).Reg(nil, router)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/v1/photos?timeline="+url.QueryEscape(manual), nil))
	var search api.SearchPhotosResponse
	if err = protojson.Unmarshal(response.Body.Bytes(), &search); err != nil || response.Code != http.StatusOK || len(search.Items) != 1 || search.Items[0].Timeline != manual {
		t.Fatalf("renamed HTTP search: %d %s %v", response.Code, response.Body, err)
	}
	second := manual + "-再次"
	err = os.Rename(filepath.Join(conf.C.Storage.PhotoSrc, manual), filepath.Join(conf.C.Storage.PhotoSrc, second))
	if err != nil {
		t.Fatal(err)
	}
	manual = second
	response = httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/v1/photos/"+row.ID+"/image?size=original", nil))
	if response.Code != http.StatusOK || response.Body.Len() == 0 {
		t.Fatalf("renamed image: %d %s", response.Code, response.Body)
	}
	events, err = server.ListEvents(ctx, &api.Empty{})
	if err != nil || len(events.Events) != 1 || events.Events[0].Id != id || events.Events[0].Event != manual || events.Events[0].Note != "活动备注" {
		t.Fatalf("external rename: %+v %v", events, err)
	}
	row, err = data.PhotoDAO.GetByID(ctx, row.ID)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoPath, row.FilePath)); err != nil {
		t.Fatal(err)
	}
	stale := req
	stale.Activity, stale.Target, stale.PhotoID = renamed, filepath.Join(renamed, row.Filename), row.ID
	replay, err := finishVerifiedArchive(ctx, stale)
	if err != nil || replay.PhotoID != row.ID || replay.Activity != manual {
		t.Fatalf("old receipt: %+v %v", replay, err)
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, renamed)); !os.IsNotExist(err) {
		t.Fatal("old activity name was recreated")
	}
	_, err = server.DeleteEvent(ctx, &api.DeleteTimelineEventRequest{Id: id})
	if err == nil {
		t.Fatal("nonempty activity was deleted")
	}
}

func TestDirectoryActivitiesMetadataValidationAndEmptyCRUD(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	server := TimelineServer{}
	created, err := server.SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "202602-空活动", Note: "可编辑"})
	if err != nil {
		t.Fatal(err)
	}
	_, err = server.SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "../escape"})
	if err == nil {
		t.Fatal("invalid name accepted")
	}
	_, err = server.SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "202602-空活动"})
	if err == nil {
		t.Fatal("existing directory overwritten")
	}
	_, err = server.DeleteEvent(ctx, &api.DeleteTimelineEventRequest{Id: created.Id})
	if err != nil {
		t.Fatal(err)
	}
	_, result := importActivityTestPhoto(t, ctx, "202603-活动", true)
	meta, err := readActivityMetadata("202603-活动")
	if err != nil {
		t.Fatal(err)
	}
	err = os.Mkdir(filepath.Join(conf.C.Storage.PhotoSrc, "202603-复制"), 0755)
	if err != nil {
		t.Fatal(err)
	}
	err = writeActivityMetadata("202603-复制", meta)
	if err != nil {
		t.Fatal(err)
	}
	if err = SyncActivityDirectories(ctx); err == nil {
		t.Fatal("duplicate stable ID accepted")
	}
	row, err := data.PhotoDAO.GetByID(ctx, result.PhotoID)
	if err != nil || row.Timeline != "202603-活动" {
		t.Fatalf("conflict changed records: %+v %v", row, err)
	}
	err = os.Remove(filepath.Join(conf.C.Storage.PhotoSrc, "202603-复制", activityMetadataFile))
	if err != nil {
		t.Fatal(err)
	}
	err = os.Remove(filepath.Join(conf.C.Storage.PhotoSrc, "202603-复制"))
	if err != nil {
		t.Fatal(err)
	}
	err = os.WriteFile(filepath.Join(conf.C.Storage.PhotoSrc, "202603-活动", activityMetadataFile), []byte("broken"), 0644)
	if err != nil {
		t.Fatal(err)
	}
	if err = SyncActivityDirectories(ctx); err == nil {
		t.Fatal("corrupt metadata silently replaced")
	}
}

func TestDirectoryRenameRestoresRecycledPhotoToCurrentActivity(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	_, result := importActivityTestPhoto(t, ctx, "202604-活动", true)
	err := startPhotoRecycle(ctx, result.PhotoID, "photo", nil)
	if err != nil {
		t.Fatal(err)
	}
	item, err := data.PhotoDAO.FindPhotoRecycle(ctx, result.PhotoID, "photo")
	if err != nil || item == nil {
		t.Fatalf("recycle: %+v %v", item, err)
	}
	err = os.Rename(filepath.Join(conf.C.Storage.PhotoSrc, "202604-活动"), filepath.Join(conf.C.Storage.PhotoSrc, "202604-改名"))
	if err != nil {
		t.Fatal(err)
	}
	err = restorePhotoRecycle(ctx, item.ID, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	row, err := data.PhotoDAO.GetByID(ctx, result.PhotoID)
	if err != nil || row.Timeline != "202604-改名" {
		t.Fatalf("restore: %+v %v", row, err)
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, row.FilePath)); err != nil {
		t.Fatal(err)
	}
	state, err := data.PhotoDAO.GetArchiveState(ctx, row.ID)
	if err != nil || !state.Favorite {
		t.Fatalf("restored favorite: %+v %v", state, err)
	}
}

func TestFavoritesJPGReimportReusesArchivedPair(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	jpg, nef := archiveTestJPG(t, 88), []byte("paired raw original")
	req := archiveTestRequest("202605-活动", jpg, nef, false)
	plan, _, err := resolveArchiveImport(ctx, req)
	if err != nil {
		t.Fatal(err)
	}
	req.Target = plan.Target
	err = os.WriteFile(filepath.Join(conf.C.Storage.PhotoSrc, plan.Target), jpg, 0644)
	if err != nil {
		t.Fatal(err)
	}
	err = os.WriteFile(filepath.Join(conf.C.Storage.PhotoSrc, plan.NEFTarget), nef, 0644)
	if err != nil {
		t.Fatal(err)
	}
	original, err := finishVerifiedArchive(ctx, req)
	if err != nil {
		t.Fatal(err)
	}
	favorite := archiveTestRequest(req.Activity, jpg, nil, true)
	// Favorites exports may have a different filename but identical bytes.
	favorite.Name = "favorite-export.JPG"
	chosen, _, err := resolveArchiveImport(ctx, favorite)
	if err != nil || chosen.PhotoID != original.PhotoID || chosen.Target != req.Target {
		t.Fatalf("favorite dedup: %+v %v", chosen, err)
	}
	favorite.Target = chosen.Target
	merged, err := finishVerifiedArchive(ctx, favorite)
	if err != nil || merged.PhotoID != original.PhotoID {
		t.Fatalf("merge: %+v %v", merged, err)
	}
	state, err := data.PhotoDAO.GetArchiveState(ctx, original.PhotoID)
	if err != nil || !state.Favorite || state.NEFSHA256 != req.NEF {
		t.Fatalf("pair/favorite changed: %+v %v", state, err)
	}
	all, err := data.PhotoDAO.GetAll(ctx)
	if err != nil || len(all) != 1 {
		t.Fatalf("duplicate photos: %d %v", len(all), err)
	}
	raw, err := os.ReadFile(filepath.Join(conf.C.Storage.PhotoSrc, plan.NEFTarget))
	if err != nil || string(raw) != string(nef) {
		t.Fatal("existing NEF was changed")
	}
}

func TestEmptyDirectoryRenameAndTimezoneOrdering(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	server := TimelineServer{}
	first, err := server.SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "later", Date: "2026-01-05T20:00:00Z"})
	if err != nil {
		t.Fatal(err)
	}
	_, err = server.SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "earlier", Date: "2026-01-06T01:00:00+08:00"})
	if err != nil {
		t.Fatal(err)
	}
	events, err := server.ListEvents(ctx, &api.Empty{})
	if err != nil || events.Events[0].Id != first.Id {
		t.Fatalf("timezone order: %+v %v", events, err)
	}
	preview := filepath.Join(conf.C.Storage.PhotoPath, "later")
	err = os.MkdirAll(preview, 0755)
	if err != nil {
		t.Fatal(err)
	}
	err = ensureActivityPreviewID(preview, first.Id)
	if err != nil {
		t.Fatal(err)
	}
	_, err = server.SaveEvent(ctx, &api.SaveTimelineEventRequest{Id: first.Id, Event: "renamed-empty"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoPath, "renamed-empty", activityPreviewIDFile)); err != nil {
		t.Fatal(err)
	}
	_, err = server.DeleteEvent(ctx, &api.DeleteTimelineEventRequest{Id: first.Id})
	if err != nil {
		t.Fatal(err)
	}
	_, err = server.SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "later"})
	if err != nil {
		t.Fatal(err)
	}
	if err = SyncActivityDirectories(ctx); err != nil {
		t.Fatal(err)
	}
}

func TestMissingActivityDoesNotBlockOtherActivities(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	_, missing := importActivityTestPhoto(t, ctx, "202501-移走", true)
	_, healthy := importActivityTestPhoto(t, ctx, "202502-保留", true)
	row, err := data.PhotoDAO.GetByID(ctx, missing.PhotoID)
	if err != nil {
		t.Fatal(err)
	}
	err = os.RemoveAll(filepath.Join(conf.C.Storage.PhotoSrc, row.Timeline))
	if err != nil {
		t.Fatal(err)
	}
	server := TimelineServer{}
	list, err := server.ListEvents(ctx, &api.Empty{})
	if err != nil || len(list.Events) != 1 || list.Events[0].Event != "202502-保留" {
		t.Fatalf("missing directory blocked list: %+v %v", list, err)
	}
	router := khttp.NewServer()
	(&PhotoServer{}).Reg(nil, router)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/v1/photos?timeline="+url.QueryEscape("202502-保留"), nil))
	var result api.SearchPhotosResponse
	err = protojson.Unmarshal(response.Body.Bytes(), &result)
	if err != nil || response.Code != http.StatusOK || len(result.Items) != 1 || result.Items[0].Id != healthy.PhotoID {
		t.Fatalf("missing directory blocked search: %d %s %v", response.Code, response.Body, err)
	}
	if _, err = data.PhotoDAO.GetByID(ctx, missing.PhotoID); err != nil {
		t.Fatal("unconfirmed missing photo was deleted")
	}
	err = ForgetMissingActivity(ctx, list.Events[0].Id)
	if err == nil {
		t.Fatal("present activity was purged")
	}
	err = ForgetMissingActivity(ctx, row.ActivityID)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = data.PhotoDAO.GetByID(ctx, missing.PhotoID); err == nil {
		t.Fatal("confirmed deleted photo remains")
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoPath, row.Timeline)); !os.IsNotExist(err) {
		t.Fatalf("orphan preview remains: %v", err)
	}
	deleted, err := data.PhotoDAO.ListDeletedPhotoIDs(ctx, true)
	if err != nil || len(deleted) != 1 || deleted[0] != missing.PhotoID {
		t.Fatalf("missing purge tombstone: %+v %v", deleted, err)
	}
	if _, err = data.PhotoDAO.GetByID(ctx, healthy.PhotoID); err != nil {
		t.Fatal("unrelated photo changed")
	}
	err = ForgetMissingActivity(ctx, row.ActivityID)
	if err != nil {
		t.Fatalf("cleanup is not retryable: %v", err)
	}
}

func TestDirectoryActivitySelectedFlagTracksFavorites(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	_, favorite := importActivityTestPhoto(t, ctx, "已选片活动", true)
	importActivityTestPhoto(t, ctx, "未选片活动", false)
	server := TimelineServer{}
	_, err := server.SaveEvent(ctx, &api.SaveTimelineEventRequest{
		Event: "空活动",
	})
	if err != nil {
		t.Fatal(err)
	}
	assertFlags := func(want bool) {
		t.Helper()
		list, err := server.ListEvents(ctx, &api.Empty{})
		if err != nil || len(list.Events) != 3 {
			t.Fatalf("events: %+v %v", list, err)
		}
		for _, event := range list.Events {
			expected := event.Event == "已选片活动" && want
			if event.HasFavorites != expected {
				t.Fatalf("activity %s selected = %v, want %v",
					event.Event, event.HasFavorites, expected)
			}
		}
	}
	assertFlags(true)
	err = data.PhotoDAO.SetArchiveFavorite(ctx, favorite.PhotoID, false)
	if err != nil {
		t.Fatal(err)
	}
	assertFlags(false)
}

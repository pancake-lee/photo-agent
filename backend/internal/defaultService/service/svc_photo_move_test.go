package service

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
)

func moveTestPair(t *testing.T, ctx *papp.AppCtx, activity string) archiveImportResult {
	t.Helper()
	jpg, nef := archiveTestJPG(t, 80), []byte("paired NEF bytes")
	req := archiveTestRequest(activity, jpg, nef, true)
	plan, _, err := resolveArchiveImport(ctx, req)
	if err != nil {
		t.Fatal(err)
	}
	req.Target = plan.Target
	for path, content := range map[string][]byte{plan.Target: jpg, plan.NEFTarget: nef} {
		full := filepath.Join(conf.C.Storage.PhotoSrc, path)
		if err = os.MkdirAll(filepath.Dir(full), 0755); err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(full, content, 0644); err != nil {
			t.Fatal(err)
		}
	}
	result, err := finishVerifiedArchive(ctx, req)
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func TestMovePhotosActivityHTTPPreservesFilesAndIdentity(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	first := moveTestPair(t, ctx, "来源一")
	second := moveTestPair(t, ctx, "来源二")
	existing := moveTestPair(t, ctx, "目标")
	router := khttp.NewServer()
	(&PhotoServer{}).Reg(nil, router)
	server := httptest.NewServer(router)
	defer server.Close()
	move := func(req movePhotosRequest, code int) photoMoveResult {
		var result photoMoveResult
		resp := doJSONRequest(t, server.Client(), http.MethodPost,
			server.URL+"/api/v1/photos/activity", req)
		readArchiveTestResponse(t, resp, code, &result)
		return result
	}
	before, _ := data.PhotoDAO.GetByID(ctx, first.PhotoID)
	before.Description, before.DescriptionTime = "保留描述", "version"
	before.EmbeddingStatus = "healthy"
	if err := data.PhotoDAO.UpdateByID(ctx, before); err != nil {
		t.Fatal(err)
	}
	stateBefore, _ := data.PhotoDAO.GetArchiveState(ctx, first.PhotoID)
	originalInfo, err := os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, first.Target))
	if err != nil {
		t.Fatal(err)
	}
	req := movePhotosRequest{PhotoIDs: []string{first.PhotoID, second.PhotoID},
		ActivityID: existing.ActivityID, BurstProfile: "all", Preview: true}
	preview := move(req, http.StatusOK)
	if preview.Total != 2 || preview.Moving != 2 || preview.Renamed != 2 {
		t.Fatalf("preview: %+v", preview)
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, activityMoveJournalName)); !os.IsNotExist(err) {
		t.Fatal("preview created journal")
	}
	req.Preview, req.ConfirmedIDs = false, preview.PhotoIDs
	result := move(req, http.StatusOK)
	if result.Moving != 2 {
		t.Fatalf("move: %+v", result)
	}
	row, _ := data.PhotoDAO.GetByID(ctx, first.PhotoID)
	if row.ActivityID != existing.ActivityID || row.Timeline != "目标" || row.Filename == before.Filename ||
		row.Description != "保留描述" || row.DescriptionTime != "version" || row.EmbeddingStatus != "healthy" {
		t.Fatalf("identity/metadata changed: %+v", row)
	}
	stateAfter, _ := data.PhotoDAO.GetArchiveState(ctx, first.PhotoID)
	if !stateAfter.Favorite || stateAfter.JPGSHA256 != stateBefore.JPGSHA256 || stateAfter.NEFSHA256 != stateBefore.NEFSHA256 ||
		stateAfter.ImportKey != data.ArchiveImportKey("目标", stateBefore.JPGSHA256, stateBefore.NEFSHA256) {
		t.Fatalf("archive metadata: %+v", stateAfter)
	}
	afterInfo, err := os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, row.FilePath))
	if err != nil || !os.SameFile(originalInfo, afterInfo) {
		t.Fatalf("original file changed: %v", err)
	}
	for _, root := range []string{conf.C.Storage.PhotoSrc, conf.C.Storage.PhotoPath} {
		if _, err = os.Stat(filepath.Join(root, row.FilePath)); err != nil {
			t.Fatal(err)
		}
		if _, err = os.Stat(filepath.Join(root, first.Target)); !os.IsNotExist(err) {
			t.Fatalf("old location remains: %s", root)
		}
	}
	nef, err := photoPairNEF(ctx, row)
	if err != nil || nef.SHA256 != stateBefore.NEFSHA256 {
		t.Fatalf("paired NEF lost: %+v %v", nef, err)
	}
	oldTarget, _ := data.PhotoDAO.GetByID(ctx, existing.PhotoID)
	if oldTarget.FilePath != existing.Target {
		t.Fatal("existing destination photo moved")
	}
	resp := doJSONRequest(t, server.Client(), http.MethodGet,
		server.URL+"/api/v1/photos/"+first.PhotoID+"/image", nil)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("image inaccessible: %d", resp.StatusCode)
	}
	resp.Body.Close()
	// Retrying after a response was lost does not move files a second time.
	retry := move(req, http.StatusOK)
	if retry.Moving != 0 || retry.Unchanged != 2 {
		t.Fatalf("retry: %+v", retry)
	}
	invalid := req
	invalid.ConfirmedIDs = []string{first.PhotoID}
	move(invalid, http.StatusConflict)
	invalid = req
	invalid.PhotoIDs = []string{first.PhotoID, first.PhotoID}
	move(invalid, http.StatusBadRequest)
	invalid = req
	invalid.PhotoIDs, invalid.Preview = []string{"missing"}, true
	move(invalid, http.StatusConflict)
	invalid = req
	invalid.ActivityID = "00000000-0000-4000-8000-000000000000"
	move(invalid, http.StatusConflict)
	invalid = movePhotosRequest{PhotoIDs: req.PhotoIDs, BurstProfile: "all", NewActivity: "../外部", Preview: true}
	move(invalid, http.StatusBadRequest)
	invalid.NewActivity = "新建预览"
	move(invalid, http.StatusOK)
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, "新建预览")); !os.IsNotExist(err) {
		t.Fatal("new activity preview created a directory")
	}
}

func TestActivityMoveRecoveryAndRollback(t *testing.T) {
	for _, committed := range []bool{false, true} {
		t.Run(map[bool]string{false: "before-commit", true: "after-commit"}[committed], func(t *testing.T) {
			ctx, _ := setupUserPathTest(t)
			source := moveTestPair(t, ctx, "来源")
			dest := moveTestPair(t, ctx, "目标")
			list, err := readActivityDirectories(ctx)
			if err != nil {
				t.Fatal(err)
			}
			var target activityDirectory
			for _, item := range list {
				if item.Metadata.ID == dest.ActivityID {
					target = item
				}
			}
			req := movePhotosRequest{PhotoIDs: []string{source.PhotoID}, BurstProfile: "all", Preview: true}
			plan, _, err := planPhotosActivityMove(ctx, req, target)
			if err != nil {
				t.Fatal(err)
			}
			raw, _ := json.Marshal(plan)
			journal := filepath.Join(conf.C.Storage.PhotoSrc, activityMoveJournalName)
			if err = os.WriteFile(journal, raw, 0600); err != nil {
				t.Fatal(err)
			}
			for _, file := range plan.Files {
				root := moveFileRoot(file.Preview)
				if err = os.Link(filepath.Join(root, file.From), filepath.Join(root, file.To)); err != nil {
					t.Fatal(err)
				}
			}
			if committed {
				if err = data.MovePhotosActivity(ctx, plan.Moves); err != nil {
					t.Fatal(err)
				}
			}
			if err = SyncActivityDirectories(ctx); err != nil {
				t.Fatal(err)
			}
			for _, file := range plan.Files {
				keep, removed := file.From, file.To
				if committed {
					keep, removed = file.To, file.From
				}
				root := moveFileRoot(file.Preview)
				if _, err = os.Stat(filepath.Join(root, keep)); err != nil {
					t.Fatal(err)
				}
				if _, err = os.Stat(filepath.Join(root, removed)); !os.IsNotExist(err) {
					t.Fatalf("interrupted link remains: %s", removed)
				}
			}
			if _, err = os.Stat(journal); !os.IsNotExist(err) {
				t.Fatal("journal not finalized")
			}
		})
	}
}

func TestActivityMovePreservesExternalCollisionAndRollsBackLinks(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	source := moveTestPair(t, ctx, "来源")
	created, err := (&TimelineServer{}).SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "目标"})
	if err != nil {
		t.Fatal(err)
	}
	meta, _ := readActivityMetadata("目标")
	target := activityDirectory{Name: "目标", Metadata: meta}
	plan, _, err := planPhotosActivityMove(ctx, movePhotosRequest{PhotoIDs: []string{source.PhotoID}, BurstProfile: "all", Preview: true}, target)
	if err != nil || created.Id != meta.ID {
		t.Fatal(err)
	}
	// An external file appears after preview. It must never be overwritten/removed.
	path := filepath.Join(conf.C.Storage.PhotoSrc, plan.Files[1].To)
	content := []byte("external user file")
	if err = os.WriteFile(path, content, 0644); err != nil {
		t.Fatal(err)
	}
	if err = applyPhotosActivityMove(ctx, plan); err == nil {
		t.Fatal("external collision accepted")
	}
	got, _ := os.ReadFile(path)
	if !bytes.Equal(got, content) {
		t.Fatal("external file overwritten")
	}
	row, _ := data.PhotoDAO.GetByID(ctx, source.PhotoID)
	if row.FilePath != source.Target {
		t.Fatal("location changed after failed move")
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, source.Target)); err != nil {
		t.Fatal(err)
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, plan.Files[0].To)); !os.IsNotExist(err) {
		t.Fatal("link published before collision was not rolled back")
	}
}

func TestActivityMoveDatabaseFailureRollsBackPublishedFiles(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	source := moveTestPair(t, ctx, "来源")
	_, err := (&TimelineServer{}).SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "目标"})
	if err != nil {
		t.Fatal(err)
	}
	meta, _ := readActivityMetadata("目标")
	plan, _, err := planPhotosActivityMove(ctx, movePhotosRequest{PhotoIDs: []string{source.PhotoID}, BurstProfile: "all", Preview: true}, activityDirectory{Name: "目标", Metadata: meta})
	if err != nil {
		t.Fatal(err)
	}
	// A competing DB record appears between planning and committing.
	err = data.PhotoDAO.Add(ctx, &data.PhotoDO{ID: "conflict", ActivityID: meta.ID,
		Timeline: "目标", Filename: plan.Moves[0].Filename, FileType: "jpg"})
	if err != nil {
		t.Fatal(err)
	}
	if err = applyPhotosActivityMove(ctx, plan); err == nil {
		t.Fatal("database collision accepted")
	}
	for _, file := range plan.Files {
		root := moveFileRoot(file.Preview)
		if _, err = os.Stat(filepath.Join(root, file.From)); err != nil {
			t.Fatal(err)
		}
		if _, err = os.Stat(filepath.Join(root, file.To)); !os.IsNotExist(err) {
			t.Fatalf("staged file not rolled back: %s", file.To)
		}
	}
	if _, err = os.Stat(filepath.Join(conf.C.Storage.PhotoSrc, activityMoveJournalName)); !os.IsNotExist(err) {
		t.Fatal("rolled-back journal remains")
	}
}

func TestActivityMoveCaseNEFAndPreviewConflictsAndSymlink(t *testing.T) {
	ctx, _ := setupUserPathTest(t)
	source := moveTestPair(t, ctx, "来源")
	_, err := (&TimelineServer{}).SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: "目标"})
	if err != nil {
		t.Fatal(err)
	}
	meta, _ := readActivityMetadata("目标")
	if err = os.MkdirAll(filepath.Join(conf.C.Storage.PhotoPath, "目标"), 0755); err != nil {
		t.Fatal(err)
	}
	for path, value := range map[string]string{
		filepath.Join(conf.C.Storage.PhotoSrc, "目标", "dsc_0123.jpg"):      "case collision",
		filepath.Join(conf.C.Storage.PhotoSrc, "目标", "DSC_0123 (2).NEF"):  "unrelated NEF",
		filepath.Join(conf.C.Storage.PhotoPath, "目标", "DSC_0123 (3).JPG"): "preview collision",
	} {
		if err = os.WriteFile(path, []byte(value), 0644); err != nil {
			t.Fatal(err)
		}
	}
	req := movePhotosRequest{PhotoIDs: []string{source.PhotoID}, BurstProfile: "all", Preview: true}
	target := activityDirectory{Name: "目标", Metadata: meta}
	plan, result, err := planPhotosActivityMove(ctx, req, target)
	if err != nil || result.Renamed != 1 || plan.Moves[0].Filename != "DSC_0123 (4).jpg" {
		t.Fatalf("collision plan: %+v %v", plan, err)
	}
	path := filepath.Join(conf.C.Storage.PhotoSrc, source.Target)
	if err = os.Rename(path, path+".backup"); err != nil {
		t.Fatal(err)
	}
	if err = os.Symlink(path+".backup", path); err != nil {
		t.Fatal(err)
	}
	if _, _, err = planPhotosActivityMove(ctx, req, target); err == nil {
		t.Fatal("symlink source accepted")
	}
}

package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestImportReviewClientSharesOnlyChangedEntriesAndLocksLatestDecisions(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("isolated XDG configuration")
	}
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	batch := &ImportBatch{ID: strings.Repeat("a", 32), Name: "活动", Activity: "202611-活动", Step: "review"}
	for _, id := range []string{"a", "b"} {
		batch.Entries = append(batch.Entries, ImportBatchEntry{
			ID: id, JPG: &ImportBatchFile{Path: filepath.Join(t.TempDir(), id+".JPG"), SHA256: strings.Repeat(id, 64)},
			Decision: batchKept, Origin: "manual", Pair: "jpg_only",
		})
	}
	var remote importRemoteReview
	var lastChanges []importRemoteChange
	cleaned := false
	receiver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch strings.TrimPrefix(r.URL.Path, "/api/v1/photo-import/") {
		case "review/publish":
			var input importRemoteReview
			err := json.NewDecoder(r.Body).Decode(&input)
			if err != nil {
				t.Error(err)
			}
			if remote.BatchID == "" {
				remote = input
				remote.State = "review"
			}
		case "review":
		case "review/edit":
			var input struct {
				Changes []importRemoteChange `json:"changes"`
				State   string               `json:"state"`
			}
			_ = json.NewDecoder(r.Body).Decode(&input)
			lastChanges = input.Changes
			if remote.State == "locked" && len(input.Changes) > 0 {
				w.WriteHeader(409)
				_ = json.NewEncoder(w).Encode(map[string]string{"error": "ended"})
				return
			}
			for _, change := range input.Changes {
				for i := range remote.Entries {
					if remote.Entries[i].ID == change.ID {
						remote.Entries[i].Decision = change.Decision
						remote.Entries[i].Origin = "manual"
					}
				}
			}
			if input.State != "" {
				remote.State = input.State
			}
		case "stage/cleanup":
			cleaned = true
			_ = json.NewEncoder(w).Encode(map[string]bool{"cleaned": true})
			return
		default:
			t.Errorf("unexpected route %s", r.URL.Path)
		}
		remote.Revision++
		remote.UpdatedAt = "2026-11-19T12:00:00Z"
		_ = json.NewEncoder(w).Encode(remote)
	}))
	defer receiver.Close()
	for i := range batch.Entries {
		batch.Entries[i].StagedServer = receiver.URL
	}
	batch.StageServers = []string{receiver.URL}
	if err := saveImportBatch(importBatchRoot(), batch); err != nil {
		t.Fatal(err)
	}
	app := &App{}
	saved, err := app.PublishImportReview(batch.ID, receiver.URL)
	if err != nil || saved.Review == nil || len(remote.Entries) != 2 {
		t.Fatalf("publish: %v %#v", err, saved)
	}
	if strings.Contains(remote.Entries[0].Name, string(os.PathSeparator)) {
		t.Fatal("shared name exposed local path")
	}
	// Phone favors A; PC submits its stale view's decision only for B.
	remote.Entries[0].Decision = "favorite"
	saved, err = app.DecideImportBatch(batch.ID, []string{"b"}, "discarded")
	if err != nil {
		t.Fatal(err)
	}
	if len(lastChanges) != 1 || lastChanges[0].ID != "b" || saved.Entries[0].Decision != "favorite" {
		t.Fatal("PC overwrote unrelated phone change")
	}
	// Last submit on the same photo wins, and refresh reads without publishing.
	remote.Entries[1].Decision = "favorite"
	saved, err = app.RefreshImportReview(batch.ID)
	if err != nil || saved.Entries[1].Decision != "favorite" {
		t.Fatalf("refresh: %v", err)
	}
	saved, err = app.DecideImportBatch(batch.ID, []string{"b"}, "discarded")
	if err != nil || remote.Entries[1].Decision != "discarded" {
		t.Fatalf("last write: %v", err)
	}
	saved, err = app.UndoImportBatch(batch.ID)
	if err != nil || remote.Entries[1].Decision != "favorite" {
		t.Fatalf("undo: %v", err)
	}
	// Latest phone change is included in the lock response before physical work.
	remote.Entries[0].Decision = "discarded"
	saved, err = app.AdvanceImportBatch(batch.ID, "reject", false)
	if err != nil || saved.Step != "reject" || saved.Entries[0].Decision != "discarded" || remote.State != "locked" {
		t.Fatalf("advance: %v %#v", err, saved)
	}
	_, err = app.DecideImportBatch(batch.ID, []string{"b"}, "kept")
	if err == nil {
		t.Fatal("PC allowed review changes in recycle step")
	}
	saved, err = app.AdvanceImportBatch(batch.ID, "review", false)
	if err != nil || remote.State != "review" {
		t.Fatalf("reopen: %v", err)
	}
	// Unavailable server cannot silently save local-only decisions in a shared batch.
	receiver.Close()
	_, err = app.DecideImportBatch(batch.ID, []string{"b"}, "kept")
	if err == nil {
		t.Fatal("offline shared update succeeded")
	}
	persisted, err := app.GetImportBatch(batch.ID)
	if err != nil || persisted.Entries[1].Decision != "favorite" {
		t.Fatalf("failed update changed local state: %v", err)
	}
	if cleaned {
		t.Fatal("review recycled stage unexpectedly")
	}
}

func TestSharedImportReviewAbandonLocksBeforeStageCleanup(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("isolated XDG configuration")
	}
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	remote := importRemoteReview{BatchID: strings.Repeat("a", 32), State: "review", Entries: []importRemoteReviewEntry{}}
	cleaned := false
	receiver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch strings.TrimPrefix(r.URL.Path, "/api/v1/photo-import/") {
		case "review/edit":
			var req struct {
				State string `json:"state"`
			}
			_ = json.NewDecoder(r.Body).Decode(&req)
			remote.State = req.State
			_ = json.NewEncoder(w).Encode(remote)
		case "stage/cleanup":
			if remote.State != "locked" {
				t.Error("cleanup started with phone editing still enabled")
			}
			cleaned = true
			_ = json.NewEncoder(w).Encode(map[string]bool{"cleaned": true})
		default:
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
	}))
	defer receiver.Close()
	batch := &ImportBatch{ID: remote.BatchID, Activity: "活动", Review: &ImportReviewSync{Server: receiver.URL}, StageServers: []string{receiver.URL}}
	err := saveImportBatch(importBatchRoot(), batch)
	if err != nil {
		t.Fatal(err)
	}
	err = (&App{}).AbandonImportBatch(batch.ID)
	if err != nil || !cleaned {
		t.Fatalf("abandon: %v, cleanup=%t", err, cleaned)
	}
	saved, err := loadImportBatch(importBatchRoot(), batch.ID)
	if err != nil || saved.Step != "abandoned" {
		t.Fatalf("abandoned batch: %v", err)
	}
}

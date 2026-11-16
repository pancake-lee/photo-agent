package main

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func batchTestDir(t *testing.T, root, name string) string {
	t.Helper()
	path := filepath.Join(root, name)
	err := os.MkdirAll(path, 0700)
	if err != nil {
		t.Fatal(err)
	}
	return path
}

func TestScanImportBatchMixedSourcesAndCoveredDifference(t *testing.T) {
	root := t.TempDir()
	card1 := batchTestDir(t, root, "local/card1")
	card2 := batchTestDir(t, root, "local/card2")
	phone := batchTestDir(t, root, "local/phone")
	rawOnly := batchTestDir(t, root, "local/raw-only")
	full := batchTestDir(t, root, "full")
	favorites := batchTestDir(t, root, "favorites")
	start := batchTestDir(t, root, "start")
	work := batchTestDir(t, root, "local/work")
	first := buildExifJpeg(time.Date(2026, 9, 1, 8, 0, 0, 0, time.Local))
	second := buildExifJpeg(time.Date(2026, 9, 1, 8, 0, 1, 0, time.Local))

	writeFile(t, filepath.Join(card1, "DSC_0123.JPG"), first)
	writeFile(t, filepath.Join(card1, "DSC_0123.NEF"), []byte("raw from card 1"))
	writeFile(t, filepath.Join(card2, "DSC_0123.JPG"), second)
	writeFile(t, filepath.Join(card2, "DSC_0123.NEF"), []byte("raw from card 2"))
	writeFile(t, filepath.Join(phone, "IMG_0.JPG"), []byte("phone"))
	writeFile(t, filepath.Join(rawOnly, "DSC_0987.NEF"), []byte("raw-only"))
	writeFile(t, filepath.Join(full, "DSC_0987.JPG"), []byte("used iPad export"))
	writeFile(t, filepath.Join(favorites, "DSC_0987.JPG"), []byte("used iPad export"))
	writeFile(t, filepath.Join(favorites, "renamed.JPG"), first)
	writeFile(t, filepath.Join(start, "DSC_0123.JPG"), second)
	writeFile(t, filepath.Join(work, "ignored.JPG"), []byte("work copy"))

	batch := &ImportBatch{
		ID: strings.Repeat("a", 32), Activity: "202609-桂林", Complete: true,
		Sources: []ImportBatchSource{
			{Path: filepath.Join(root, "local"), Role: "local"},
			{Path: full, Role: "retained"}, {Path: favorites, Role: "favorite"},
			{Path: start, Role: "starting"},
		},
	}
	scanImportBatch(work, batch, nil)
	if len(batch.Entries) != 4 || len(batch.Issues) != 0 {
		t.Fatalf("entries: %#v, issues: %v", batch.Entries, batch.Issues)
	}
	byPath := make(map[string]ImportBatchEntry)
	for _, entry := range batch.Entries {
		byPath[entry.JPG.Path] = entry
	}
	c1 := byPath[filepath.Join(card1, "DSC_0123.JPG")]
	c2 := byPath[filepath.Join(card2, "DSC_0123.JPG")]
	iPad := byPath[filepath.Join(full, "DSC_0987.JPG")]
	if c1.Decision != batchKept || c1.NEF.Path != filepath.Join(card1, "DSC_0123.NEF") {
		t.Fatalf("card one = %#v", c1)
	}
	if c2.Decision != batchKept || !c2.MissingFromExport || c2.NEF.Path != filepath.Join(card2, "DSC_0123.NEF") {
		t.Fatalf("card two = %#v", c2)
	}
	if iPad.Decision != batchFavorite || iPad.NEF.Path != filepath.Join(rawOnly, "DSC_0987.NEF") {
		t.Fatalf("iPad = %#v", iPad)
	}
	if len(collectImportRecycle(batch, "discarded")) != 0 {
		t.Fatal("an inferred discard became eligible without human review")
	}
	err := batch.setDecisions([]string{c2.ID}, batchDiscarded)
	if err != nil {
		t.Fatal(err)
	}
	if items := collectImportRecycle(batch, "discarded"); len(items) != 2 {
		t.Fatalf("expected only confirmed discarded pair: %#v", items)
	}
	batch.undoDecisions()
	if items := collectImportRecycle(batch, "discarded"); len(items) != 0 {
		t.Fatalf("undo left the files eligible: %#v", items)
	}

	partial := &ImportBatch{Sources: batch.Sources}
	scanImportBatch(work, partial, nil)
	for _, entry := range partial.Entries {
		if entry.MissingFromExport {
			t.Fatal("partial export inferred absence")
		}
	}
}

func TestImportBatchPersistsDecisionAcrossMoveAndRequiresContent(t *testing.T) {
	root := t.TempDir()
	work := batchTestDir(t, root, "work")
	source := batchTestDir(t, root, "source")
	path := filepath.Join(source, "before.JPG")
	writeFile(t, path, []byte("same original"))
	batch := &ImportBatch{ID: strings.Repeat("b", 32), Activity: "activity",
		Sources: []ImportBatchSource{{Path: source, Role: "local"}}}
	scanImportBatch(work, batch, nil)
	id := batch.Entries[0].ID
	batch.Entries[0].Decision, batch.Entries[0].Origin = "later", "manual"
	err := saveImportBatch(work, batch)
	if err != nil {
		t.Fatal(err)
	}
	old, err := loadImportBatch(work, batch.ID)
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(source, "moved.JPG")
	err = os.Rename(path, target)
	if err != nil {
		t.Fatal(err)
	}
	scanImportBatch(work, batch, old)
	if entry := batch.Entries[0]; entry.ID != id || entry.Decision != "later" {
		t.Fatalf("moved entry = %#v", entry)
	}
	writeFile(t, target, []byte("replacement"))
	scanImportBatch(work, batch, old)
	if entry := batch.Entries[0]; entry.ID == id || entry.Decision != batchKept {
		t.Fatalf("replacement inherited decision = %#v", entry)
	}
}

func TestLocalRecycleResumeAndRestoreCollision(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "source.jpg")
	staged := filepath.Join(root, "group", "files", "source.jpg")
	writeFile(t, source, []byte("original"))
	digest, err := importFileDigest(source)
	if err != nil {
		t.Fatal(err)
	}
	err = stageImportRecycle(source, staged, digest)
	if err != nil {
		t.Fatal(err)
	}
	err = stageImportRecycle(source, staged, digest)
	if err != nil {
		t.Fatalf("resume staging: %v", err)
	}
	writeFile(t, source, []byte("other original"))
	file := &ImportRecycleFile{Source: source, Relative: filepath.Join("files", "source.jpg"), SHA256: digest}
	err = restoreImportRecycleFile(filepath.Join(root, "group"), file)
	if err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(source)
	if string(got) != "other original" || file.RestoredTo == source || file.RestoredTo == "" {
		t.Fatalf("collision was overwritten: %s", got)
	}
	got, _ = os.ReadFile(file.RestoredTo)
	if string(got) != "original" {
		t.Fatalf("restored data = %s", got)
	}
}

func TestRawOnlyCoveredDiscardUsesStartingJPGAsEvidence(t *testing.T) {
	root := t.TempDir()
	source := batchTestDir(t, root, "raw")
	full := batchTestDir(t, root, "full-empty")
	start := batchTestDir(t, root, "starting")
	at := time.Date(2026, 9, 1, 8, 0, 0, 0, time.Local)
	jpg := buildExifJpeg(at)
	rawPath := filepath.Join(source, "DSC_1.NEF")
	// Nikon NEF is TIFF-based. Here the EXIF TIFF payload is enough to
	// reproduce a matching capture timestamp without including real images.
	writeFile(t, rawPath, jpg[12:])
	startPath := filepath.Join(start, "DSC_1.JPG")
	writeFile(t, startPath, jpg)
	batch := &ImportBatch{Complete: true, Sources: []ImportBatchSource{
		{Path: source, Role: "local"}, {Path: full, Role: "retained"}, {Path: start, Role: "starting"},
	}}
	scanImportBatch(filepath.Join(root, "work"), batch, nil)
	if len(batch.Entries) != 1 || !batch.Entries[0].ReferenceOnly || !batch.Entries[0].MissingFromExport {
		t.Fatalf("expected one covered raw-only candidate: %#v", batch.Entries)
	}
	err := batch.setDecisions([]string{batch.Entries[0].ID}, batchDiscarded)
	if err != nil {
		t.Fatal(err)
	}
	files := collectImportRecycle(batch, "discarded")
	if len(files) != 1 || files[0].Path != rawPath {
		t.Fatalf("starting JPG is not a cleanup target: %#v", files)
	}
	writeFile(t, rawPath, []byte("unknown capture"))
	scanImportBatch(filepath.Join(root, "work"), batch, nil)
	if len(batch.Entries) != 1 || batch.Entries[0].MissingFromExport || batch.Entries[0].Pair != "nef_only" {
		t.Fatalf("a common filename alone cannot prove prior iPad coverage: %#v", batch.Entries)
	}
}

func TestLocalRecycleUnavailableRetainsOriginal(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("this fixture represents a platform without a recycle bin")
	}
	root := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", root)
	filePath := filepath.Join(root, "original.JPG")
	writeFile(t, filePath, []byte("original"))
	file, err := inspectBatchFile(filePath, root)
	if err != nil {
		t.Fatal(err)
	}
	batch := &ImportBatch{
		ID: strings.Repeat("c", 32), Activity: "fixture",
		Entries: []ImportBatchEntry{{ID: "discard", JPG: file, Decision: batchDiscarded, Origin: "manual"}},
	}
	err = saveImportBatch(importBatchRoot(), batch)
	if err != nil {
		t.Fatal(err)
	}
	app := NewApp()
	files, err := app.PreviewImportRecycle(batch.ID, "discarded")
	if err != nil || len(files) != 1 || files[0].Source != filePath {
		t.Fatalf("recycle preview = %#v, %v", files, err)
	}
	result, err := app.RecycleImportFiles(batch.ID, "discarded", []string{filePath})
	if err != nil || len(result.Recycling) != 1 || result.Recycling[0].Status != "retained" {
		t.Fatalf("unexpected recycle result: %#v %v", result, err)
	}
	err = verifyRecycleDigest(filePath, file.SHA256)
	if err != nil {
		t.Fatalf("original was changed on unsupported volume: %v", err)
	}
	if _, err = app.RecycleImportFiles(batch.ID, "discarded", []string{"relative.jpg"}); err == nil {
		t.Fatal("relative original path was accepted")
	}
}

func TestImportGroupReviewDecisions(t *testing.T) {
	batch := &ImportBatch{Entries: []ImportBatchEntry{
		{ID: "first", JPG: &ImportBatchFile{Path: "first.jpg"}, Decision: batchFavorite, Origin: "ipad"},
		{ID: "second", JPG: &ImportBatchFile{Path: "second.jpg"}, Decision: "later"},
		{ID: "third", JPG: &ImportBatchFile{Path: "third.jpg"}, Decision: batchKept},
	}}
	if !batch.Entries[1].canUpload() || !batch.Entries[2].canUpload() {
		t.Fatal("untouched entries should be eligible for the confirmed import")
	}
	ids := []string{"first", "second"}
	err := batch.setDecisions(ids, batchFavorite)
	if err != nil || batch.Entries[1].Decision != batchFavorite || batch.Entries[2].Decision == batchFavorite {
		t.Fatalf("group favorite: %#v, %v", batch.Entries, err)
	}
	batch.undoDecisions()
	if batch.Entries[0].Decision != batchFavorite || batch.Entries[1].Decision != "later" {
		t.Fatal("group favorite undo should restore each member's state")
	}
	err = batch.setDecisions(ids, batchDiscarded)
	if err != nil || batch.Entries[0].canUpload() || batch.Entries[1].canUpload() || !batch.Entries[2].canUpload() {
		t.Fatalf("group deletion: %#v, %v", batch.Entries, err)
	}
	batch.undoDecisions()
	if batch.Entries[0].Decision != batchFavorite || batch.Entries[1].Decision != "later" {
		t.Fatal("group deletion undo should restore each member's state")
	}
}

func TestImportBatchNamesAndRecycleFolders(t *testing.T) {
	root := t.TempDir()
	legacy := &ImportBatch{ID: strings.Repeat("a", 32), Activity: "桂林"}
	if err := saveImportBatch(root, legacy); err != nil {
		t.Fatal(err)
	}
	for i, want := range []string{"桂林-1", "桂林-2"} {
		batch := &ImportBatch{ID: strings.Repeat(string(rune('b'+i)), 32), Activity: "桂林"}
		var err error
		batch.Name, err = importBatchName(root, batch)
		if err != nil || batch.Name != want {
			t.Fatalf("new batch name = %q, want %q: %v", batch.Name, want, err)
		}
		if err := saveImportBatch(root, batch); err != nil {
			t.Fatal(err)
		}
		for kind, suffix := range map[string]string{"discarded": "-reject", "imported": "-keep"} {
			dir, err := importRecycleDirectory(batch, root, kind)
			if err != nil || dir != filepath.Join(root, want+suffix) {
				t.Fatalf("%s folder = %q: %v", kind, dir, err)
			}
			batch.Recycling = append(batch.Recycling, ImportRecycleGroup{Directory: dir})
			retry, err := importRecycleDirectory(batch, root, kind)
			if err != nil || retry != filepath.Join(root, want+"-1"+suffix) {
				t.Fatalf("later recycle folder = %q: %v", retry, err)
			}
		}
	}
	name, err := importBatchName(root, legacy)
	if err != nil || name != "桂林" {
		t.Fatalf("legacy batch name = %q: %v", name, err)
	}
}

func TestRecycleDirectoryRejectsUnrelatedFiles(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "original.jpg")
	writeFile(t, source, []byte("original"))
	digest, err := importFileDigest(source)
	if err != nil {
		t.Fatal(err)
	}
	group := &ImportRecycleGroup{Directory: filepath.Join(root, "活动-reject"), Files: []ImportRecycleFile{
		{Source: source, Relative: "original.jpg", SHA256: digest},
	}}
	target := filepath.Join(group.Directory, group.Files[0].Relative)
	if err := stageImportRecycle(source, target, digest); err != nil {
		t.Fatal(err)
	}
	if err := verifyRecycleDirectory(group); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(group.Directory, "unrelated.jpg"), []byte("unrelated"))
	if err := verifyRecycleDirectory(group); err == nil {
		t.Fatal("the chosen directory includes an unrelated file")
	}
}

func TestRecycleGroupsUseEachOriginalDirectory(t *testing.T) {
	root := t.TempDir()
	card := batchTestDir(t, root, "card")
	nested := batchTestDir(t, card, "subfolder")
	raw := batchTestDir(t, root, "raw")
	unsupported := batchTestDir(t, root, "unsupported")
	for _, test := range []struct{ kind, suffix string }{
		{"discarded", "-reject"}, {"imported", "-keep"},
	} {
		t.Run(test.kind, func(t *testing.T) {
			batch := &ImportBatch{Name: "活动"}
			existing := batchTestDir(t, nested, batch.Name+test.suffix)
			files := []*ImportBatchFile{
				{Path: filepath.Join(card, "a.jpg")}, {Path: filepath.Join(raw, "a.nef")},
				{Path: filepath.Join(card, "b.jpg")}, {Path: filepath.Join(nested, "a.jpg")},
				{Path: filepath.Join(unsupported, "skip.jpg")},
			}
			planImportRecycleGroups(batch, test.kind, files, func(path string) (string, error) {
				if path == unsupported {
					return "", errors.New("回收站不可用")
				}
				return root, nil
			})
			groups := batch.Recycling
			if len(groups) != 4 || groups[0].Directory != filepath.Join(card, batch.Name+test.suffix) ||
				groups[1].Directory != filepath.Join(raw, batch.Name+test.suffix) ||
				groups[2].Directory != filepath.Join(nested, batch.Name+"-1"+test.suffix) || groups[2].Directory == existing ||
				groups[3].Status != "retained" || groups[3].Error == "" {
				t.Fatalf("unexpected recycle groups: %#v", groups)
			}
			if len(groups[0].Files) != 2 || groups[0].Files[1].Relative != "b.jpg" || groups[2].Files[0].Relative != "a.jpg" {
				t.Fatalf("original filenames or grouping changed: %#v", groups)
			}
		})
	}
}

func TestIncompleteRecycleMovesBackBeforeReplanning(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "a.jpg")
	writeFile(t, source, []byte("original"))
	digest, err := importFileDigest(source)
	if err != nil {
		t.Fatal(err)
	}
	old := filepath.Join(root, ".photo-agent-recycle", "old-reject")
	oldFile := filepath.Join(old, "originals", "a.jpg")
	if err := stageImportRecycle(source, oldFile, digest); err != nil {
		t.Fatal(err)
	}
	batch := &ImportBatch{Recycling: []ImportRecycleGroup{{Kind: "discarded", Status: "pending", Directory: old,
		Files: []ImportRecycleFile{{Source: source, SHA256: digest, Relative: filepath.Join("originals", "a.jpg"), Status: "staged"}},
	}}}
	if err := restoreMisplacedRecycleFiles(batch, "discarded", map[string]bool{source: true}, func() error { return nil }); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(oldFile); !os.IsNotExist(err) || batch.Recycling[0].Status != "restored" {
		t.Fatalf("interrupted group was not moved back before replanning: %v %#v", err, batch.Recycling)
	}
	if err := verifyRecycleDigest(source, digest); err != nil {
		t.Fatal(err)
	}
}

func TestUncertainLegacyRecycleIsNotReplanned(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "a.jpg")
	batch := &ImportBatch{Recycling: []ImportRecycleGroup{{
		Kind: "discarded", Status: "sending", Directory: filepath.Join(root, "previous", "old-reject"),
		Files: []ImportRecycleFile{{Source: source, Relative: "a.jpg", Status: "staged"}},
	}}}
	selected := map[string]bool{source: true}
	save := func() error { return nil }
	if err := restoreMisplacedRecycleFiles(batch, "discarded", selected, save); err != nil {
		t.Fatal(err)
	}
	group := &batch.Recycling[0]
	if err := runImportRecycle(group, selected, save); err != nil {
		t.Fatal(err)
	}
	if group.Status != "uncertain" || len(group.Files) != 1 || group.Files[0].Status != "staged" {
		t.Fatalf("missing previous recycle directory should remain recorded: %#v", group)
	}
}

func TestImportUsesLocalFolderForBlankActivity(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("fixture redirects config using XDG_CONFIG_HOME")
	}
	root := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", root)
	local := batchTestDir(t, root, "桂林")
	writeFile(t, filepath.Join(local, "a.JPG"), []byte("jpg fixture"))
	batch, err := NewApp().ScanImportBatch("", "", []ImportBatchSource{{Path: local, Role: "local"}}, false, importModePC)
	if err != nil || batch.Activity != "桂林" || batch.Name != "桂林" {
		t.Fatalf("inferred activity = %#v %v", batch, err)
	}
}

func TestScanImportBatchSourceModes(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("fixture redirects config using XDG_CONFIG_HOME")
	}
	root := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", root)
	local := ImportBatchSource{Path: batchTestDir(t, root, "local"), Role: "local"}
	favorite := ImportBatchSource{Path: batchTestDir(t, root, "favorite"), Role: "favorite"}
	starting := ImportBatchSource{Path: batchTestDir(t, root, "starting"), Role: "starting"}
	retained := ImportBatchSource{Path: batchTestDir(t, root, "retained"), Role: "retained"}
	writeFile(t, filepath.Join(local.Path, "original.jpg"), []byte("shared"))
	writeFile(t, filepath.Join(favorite.Path, "renamed.jpg"), []byte("shared"))
	writeFile(t, filepath.Join(favorite.Path, "ORIGINAL.NEF"), []byte("raw marker"))
	writeFile(t, filepath.Join(favorite.Path, "export.NEF"), []byte("raw marker"))
	writeFile(t, filepath.Join(favorite.Path, "favorite-only.jpg"), []byte("favorite only"))
	writeFile(t, filepath.Join(starting.Path, "initial.jpg"), []byte("shared"))
	writeFile(t, filepath.Join(starting.Path, "unselected.jpg"), []byte("unselected"))
	writeFile(t, filepath.Join(retained.Path, "export.jpg"), []byte("shared"))

	app := NewApp()
	if _, err := app.ScanImportBatch("", "活动", []ImportBatchSource{favorite}, false, importModePC); err == nil {
		t.Fatal("computer mode accepted a favorite folder without originals")
	}
	if _, err := app.ScanImportBatch("", "活动", []ImportBatchSource{local, retained}, false, importModeIPad); err == nil {
		t.Fatal("iPad mode accepted a missing starting range")
	}
	if _, err := app.ScanImportBatch("", "活动", []ImportBatchSource{starting, favorite}, false, importModeIPad); err == nil {
		t.Fatal("iPad mode accepted a missing retained export")
	}

	pc, err := app.ScanImportBatch("", "活动", []ImportBatchSource{local, favorite}, false, importModePC)
	if err != nil {
		t.Fatal(err)
	}
	pc, err = app.GetImportBatch(pc.ID)
	if err != nil {
		t.Fatal(err)
	}
	if pc.Mode != importModePC || len(pc.Entries) != 1 || pc.Entries[0].Decision != batchFavorite ||
		pc.Entries[0].JPG.Root != local.Path {
		t.Fatalf("computer mode should use originals and inherit matched favorites: %#v", pc)
	}
	ipadSources := []ImportBatchSource{starting, retained, favorite}
	if _, err := app.ScanImportBatch(pc.ID, "活动", ipadSources, true, importModeIPad); err == nil {
		t.Fatal("changing the mode of an existing batch should require a new batch")
	}

	ipad, err := app.ScanImportBatch("", "活动", ipadSources, true, importModeIPad)
	if err != nil {
		t.Fatal(err)
	}
	ipad, err = app.GetImportBatch(ipad.ID)
	if err != nil {
		t.Fatal(err)
	}
	if ipad.Mode != importModeIPad || len(ipad.Entries) != 2 {
		t.Fatalf("iPad mode should include the retained and favorite-only exports: %#v", ipad)
	}
	for _, entry := range ipad.Entries {
		if entry.Decision != batchFavorite || entry.JPG.Root == starting.Path {
			t.Fatalf("starting exports are references and favorite exports are marked: %#v", entry)
		}
	}

	legacy, err := app.ScanImportBatch("", "活动", []ImportBatchSource{favorite}, false, "")
	if err != nil {
		t.Fatal(err)
	}
	legacy, err = app.ScanImportBatch(legacy.ID, legacy.Activity, legacy.Sources, legacy.Complete, "")
	if err != nil || legacy.Mode != "" || len(legacy.Entries) != 2 {
		t.Fatalf("existing batches should keep their source rules: %#v %v", legacy, err)
	}
}

func TestScanReportsEmptyFavoriteDirectories(t *testing.T) {
	root := t.TempDir()
	local := batchTestDir(t, root, "local")
	empty := batchTestDir(t, root, "empty-favorites")
	metadataOnly := batchTestDir(t, root, "metadata-only")
	nested := batchTestDir(t, root, "favorites/nested")
	missing := filepath.Join(root, "missing-favorites")
	photo := []byte("jpg fixture")
	writeFile(t, filepath.Join(local, "original.jpg"), photo)
	writeFile(t, filepath.Join(metadataOnly, ".DS_Store"), []byte("directory metadata"))
	writeFile(t, filepath.Join(nested, "ORIGINAL.NEF"), nil)

	batch := &ImportBatch{
		Mode: importModePC,
		Sources: []ImportBatchSource{
			{Path: local, Role: "local"},
			{Path: empty, Role: "favorite"},
			{Path: metadataOnly, Role: "favorite"},
			{Path: filepath.Dir(nested), Role: "favorite"},
			{Path: missing, Role: "favorite"},
		},
	}
	work := filepath.Join(root, "work")
	scanImportBatch(work, batch, nil)
	assertStrSlice(t, batch.EmptyFavoriteDirs, []string{empty, metadataOnly})
	if len(batch.Issues) != 1 || !strings.Contains(batch.Issues[0], missing) {
		t.Fatalf("missing directory should be a read error: %v", batch.Issues)
	}
	if len(batch.Entries) != 1 || batch.Entries[0].Decision != batchFavorite {
		t.Fatalf("valid files should still match: %#v", batch.Entries)
	}

	writeFile(t, filepath.Join(empty, "found.HEIC"), nil)
	scanImportBatch(work, batch, nil)
	assertStrSlice(t, batch.EmptyFavoriteDirs, []string{metadataOnly})
}

func TestScanFavoriteNamesLeaveAmbiguousOriginalsForReview(t *testing.T) {
	root := t.TempDir()
	local := batchTestDir(t, root, "local")
	secondCard := batchTestDir(t, local, "second-card")
	favorites := batchTestDir(t, root, "favorites")
	writeFile(t, filepath.Join(local, "DSC_0001.jpg"), []byte("first photo"))
	writeFile(t, filepath.Join(secondCard, "dsc_0001.jpg"), []byte("different photo"))
	writeFile(t, filepath.Join(local, "DSC_0002.jpg"), []byte("third photo"))
	writeFile(t, filepath.Join(favorites, "DSC_0001.nef"), nil)
	writeFile(t, filepath.Join(favorites, "dsc_0002.HEIC"), nil)
	writeFile(t, filepath.Join(favorites, "DSC_0002.nef"), nil)

	batch := &ImportBatch{Mode: importModePC, Sources: []ImportBatchSource{
		{Path: local, Role: "local"}, {Path: favorites, Role: "favorite"},
	}}
	scanImportBatch(filepath.Join(root, "work"), batch, nil)
	favoritesCount, conflicts := 0, 0
	for _, entry := range batch.Entries {
		if entry.Decision == batchFavorite {
			favoritesCount++
			if filepath.Base(entry.JPG.Path) != "DSC_0002.jpg" || entry.NEF != nil {
				t.Fatalf("unexpected favorite: %#v", entry)
			}
		}
		if entry.Conflict {
			conflicts++
		}
	}
	if favoritesCount != 1 || conflicts != 2 || len(batch.Entries) != 3 {
		t.Fatalf("unambiguous names should match once and different same-name originals need review: %#v", batch.Entries)
	}
}

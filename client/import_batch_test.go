package main

import (
	"context"
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
		ID: strings.Repeat("a", 32), Activity: "202609-桂林", Reviewed: true, Complete: true,
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
	if c1.Decision != batchFavorite || c1.NEF.Path != filepath.Join(card1, "DSC_0123.NEF") {
		t.Fatalf("card one = %#v", c1)
	}
	if c2.Decision != batchPending || !c2.MissingFromExport || c2.NEF.Path != filepath.Join(card2, "DSC_0123.NEF") {
		t.Fatalf("card two = %#v", c2)
	}
	if iPad.Decision != batchFavorite || iPad.NEF.Path != filepath.Join(rawOnly, "DSC_0987.NEF") {
		t.Fatalf("iPad = %#v", iPad)
	}
	if len(collectImportRecycle(batch, "discarded")) != 0 {
		t.Fatal("an inferred discard became eligible without human review")
	}
	err := batch.setDecisions([]string{c2.ID}, batchDiscarded, false)
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

	partial := &ImportBatch{Sources: batch.Sources, Reviewed: true}
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
	err := batch.setDecisions([]string{id}, batchLater, false)
	if err != nil {
		t.Fatal(err)
	}
	err = saveImportBatch(work, batch)
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
	if entry := batch.Entries[0]; entry.ID != id || entry.Decision != batchLater {
		t.Fatalf("moved entry = %#v", entry)
	}
	writeFile(t, target, []byte("replacement"))
	scanImportBatch(work, batch, old)
	if entry := batch.Entries[0]; entry.ID == id || entry.Decision != batchPending {
		t.Fatalf("replacement inherited decision = %#v", entry)
	}
}

func TestReadCullScoresRejectsDuplicates(t *testing.T) {
	path := filepath.Join(t.TempDir(), "tiers.csv")
	raw := "\xef\xbb\xbffilename,rating,tier,rank,why,cluster\n" +
		"a.jpg,4,top5,1,sharp,1\na.jpg,1,reject,-1,duplicate,\nb.jpg,2,p15_30,12,good,3\n"
	writeFile(t, path, []byte(raw))
	manifest := map[string]ImportBatchEntry{
		"a.jpg": {ID: "a", JPG: &ImportBatchFile{SHA256: "digest-a"}},
		"b.jpg": {ID: "b", JPG: &ImportBatchFile{SHA256: "digest-b"}},
	}
	scores, err := readCullScores(path, manifest, "auto")
	if err != nil || len(scores) != 1 || scores["b"].Rank != 12 || scores["a"] != nil {
		t.Fatalf("scores %#v, err %v", scores, err)
	}
}

func TestAutoCullWorkspaceIsolatesOriginalAndXMP(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("CLI fixture uses POSIX shell")
	}
	root := t.TempDir()
	source := batchTestDir(t, root, "source")
	workspace := batchTestDir(t, root, "work")
	path := filepath.Join(source, "DSC.JPG")
	xmp := filepath.Join(source, "DSC.xmp")
	writeFile(t, path, []byte("original JPG bytes"))
	writeFile(t, xmp, []byte("original XMP bytes"))
	cli := filepath.Join(root, "autocull")
	script := `#!/bin/sh
set -eu
if [ "$1" = --version ]; then
  printf 'autocull 1.4.9\n'
  exit 0
fi
[ "$1" = run ]
cd "$2"
set -- *.jpg
[ "$#" -eq 1 ]
file="$1"
mkdir -p _cull_out/autocull
printf 'filename,rating,tier,rank,why,cluster\n%s,4,top5,1,sharp,3\n' "$file" > _cull_out/autocull/tiers.csv
printf 'changed copy only' > "$file"
printf 'new sidecar in workspace' > "${file%.jpg}.xmp"
`
	err := os.WriteFile(cli, []byte(script), 0700)
	if err != nil {
		t.Fatal(err)
	}
	file, err := inspectBatchFile(path, source)
	if err != nil {
		t.Fatal(err)
	}
	batch := &ImportBatch{Entries: []ImportBatchEntry{
		{ID: "pending", JPG: file, Decision: batchPending},
		{ID: "favorite", JPG: file, Decision: batchFavorite},
	}}
	scores, failures, err := analyzeImportBatch(context.Background(), workspace, batch, cli, "auto", func(ImportCullProgress) {})
	if err != nil || len(scores) != 1 || len(failures) != 0 || scores["pending"].SHA256 != file.SHA256 {
		t.Fatalf("scores %#v failures %#v err %v", scores, failures, err)
	}
	for p, expected := range map[string]string{path: "original JPG bytes", xmp: "original XMP bytes"} {
		data, err := os.ReadFile(p)
		if err != nil || string(data) != expected {
			t.Fatalf("source %s changed: %v", p, err)
		}
	}
	files, err := os.ReadDir(workspace)
	if err != nil || len(files) != 0 {
		t.Fatalf("orphaned workspace: %v %v", files, err)
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

func TestAutoCullCancellationStopsChildAndCleansWorkspace(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("CLI fixture uses POSIX shell")
	}
	root := t.TempDir()
	work := batchTestDir(t, root, "cull")
	cli := filepath.Join(root, "autocull")
	script := `#!/bin/sh
if [ "$1" = --version ]; then
  printf 'autocull 1.4.9\n'
  exit 0
fi
sleep 30 &
printf 'analyzing\n'
wait
`
	err := os.WriteFile(cli, []byte(script), 0700)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "test.JPG")
	writeFile(t, path, []byte("test"))
	file, err := inspectBatchFile(path, root)
	if err != nil {
		t.Fatal(err)
	}
	batch := &ImportBatch{Entries: []ImportBatchEntry{{ID: "pending", JPG: file, Decision: batchPending}}}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	started := time.Now()
	_, _, err = analyzeImportBatch(ctx, work, batch, cli, "auto", func(p ImportCullProgress) {
		if p.Message == "analyzing" {
			cancel()
		}
	})
	if err != context.Canceled || time.Since(started) > 4*time.Second {
		t.Fatalf("cancel exceeded deadline or misreported: %v", err)
	}
	remaining, err := os.ReadDir(work)
	if err != nil || len(remaining) != 0 {
		t.Fatalf("cancellation left workspace: %v %v", remaining, err)
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
	err := batch.setDecisions([]string{batch.Entries[0].ID}, batchDiscarded, false)
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
	result, err := app.RecycleImportFiles(batch.ID, "discarded", []string{filePath}, false)
	if err != nil || len(result.Recycling) != 1 || result.Recycling[0].Status != "retained" {
		t.Fatalf("unexpected recycle result: %#v %v", result, err)
	}
	err = verifyRecycleDigest(filePath, file.SHA256)
	if err != nil {
		t.Fatalf("original was changed on unsupported volume: %v", err)
	}
	if _, err = app.RecycleImportFiles(batch.ID, "imported", []string{filePath}, true); err == nil {
		t.Fatal("permanent deletion for imported images was accepted")
	}
}

package main

import (
	"encoding/base64"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// buildExifJpeg 构造一个带 EXIF 的极简 JPEG（APP1 段 + IFD0 写入 DateTime 0x0132）。
// goexif 的 DateTime() 在缺失 DateTimeOriginal 时会回退到 DateTime，因此可直接命中。
func buildExifJpeg(shotAt time.Time) []byte {
	dateStr := shotAt.Format("2006:01:02 15:04:05")
	dateField := make([]byte, 20)
	copy(dateField, dateStr)

	tiff := make([]byte, 0, 46)
	// TIFF 头（小端）："II" + magic 42 + IFD0 偏移 = 8
	tiff = append(tiff, 'I', 'I', 42, 0, 8, 0, 0, 0)
	// IFD0：条目数 = 1
	tiff = append(tiff, 1, 0)
	// 条目：tag=0x0132, type=ASCII(2), count=20, 值偏移=26
	tiff = append(tiff, 0x32, 0x01, 2, 0, 20, 0, 0, 0, 26, 0, 0, 0)
	// 下一个 IFD 偏移 = 0
	tiff = append(tiff, 0, 0, 0, 0)
	// 偏移 26 处：DateTime 字符串
	tiff = append(tiff, dateField...)

	exifHeader := []byte{'E', 'x', 'i', 'f', 0, 0}
	app1Data := append(exifHeader, tiff...)
	length := len(app1Data) + 2

	jpeg := []byte{0xFF, 0xD8, 0xFF, 0xE1}
	jpeg = append(jpeg, byte(length>>8), byte(length&0xFF))
	jpeg = append(jpeg, app1Data...)
	return jpeg
}

func writeFile(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.WriteFile(path, data, 0644); err != nil {
		t.Fatal(err)
	}
}

func assertStrSlice(t *testing.T, got, want []string) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("len mismatch: got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("mismatch at %d: got %v, want %v", i, got, want)
		}
	}
}

// testFolder 测试用归档目录名。
const testFolder = "202608-山西旅游"

func TestBaseNameOf(t *testing.T) {
	cases := map[string]string{
		"IMG_0001.NEF":  "img_0001",
		"IMG_0001.JPG":  "img_0001",
		"img_0001.jpg":  "img_0001",
		"IMG_0001":      "img_0001",
		"DSC_1234.jpeg": "dsc_1234",
	}
	for in, want := range cases {
		if got := baseNameOf(in); got != want {
			t.Errorf("baseNameOf(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestCompareNef(t *testing.T) {
	fullDir := filepath.Join(t.TempDir(), "full")
	likeDir := filepath.Join(t.TempDir(), "like")
	full := []FileInfo{
		{Name: "IMG_0001.JPG"}, {Name: "IMG_0002.JPG"}, {Name: "IMG_0003.JPG"}, {Name: "IMG_0004.JPG"},
	}
	like := []FileInfo{{Name: "IMG_0002.JPG"}}
	nef := []FileInfo{
		{Name: "IMG_0001.NEF"}, {Name: "IMG_0002.NEF"}, {Name: "IMG_0003.NEF"}, {Name: "ORPHAN.NEF"},
	}

	favorite, retained, discarded, migrated, missing := compareNef(fullDir, likeDir, full, like, nil, nef)

	assertStrSlice(t, favorite, []string{"IMG_0002.NEF"})
	assertStrSlice(t, retained, []string{"IMG_0001.NEF", "IMG_0003.NEF"})
	assertStrSlice(t, discarded, []string{"ORPHAN.NEF"})
	assertStrSlice(t, migrated, []string{})
	if len(missing) != 1 {
		t.Fatalf("missing len = %d, want 1", len(missing))
	}
	if missing[0].Name != "IMG_0004.JPG" || missing[0].Dir != "full" {
		t.Fatalf("missing ref wrong: %+v", missing[0])
	}
	if missing[0].Path != filepath.Join(fullDir, "IMG_0004.JPG") {
		t.Fatalf("missing path wrong: %+v", missing[0])
	}
}

func TestCompareNefMigrated(t *testing.T) {
	fullDir := filepath.Join(t.TempDir(), "full")
	likeDir := filepath.Join(t.TempDir(), "like")
	full := []FileInfo{{Name: "IMG_0001.JPG"}, {Name: "IMG_0002.JPG"}}
	like := []FileInfo{{Name: "IMG_0001.JPG"}}
	// like 中已有 IMG_0001.NEF，表示已迁移
	likeNef := []FileInfo{{Name: "IMG_0001.NEF"}}
	nef := []FileInfo{{Name: "IMG_0001.NEF"}, {Name: "IMG_0002.NEF"}}

	favorite, retained, discarded, migrated, _ := compareNef(fullDir, likeDir, full, like, likeNef, nef)

	assertStrSlice(t, favorite, []string{})
	assertStrSlice(t, migrated, []string{"IMG_0001.NEF"})
	assertStrSlice(t, retained, []string{"IMG_0002.NEF"})
	assertStrSlice(t, discarded, []string{})
}

func TestTimeRangeAndOutliers(t *testing.T) {
	base := time.Date(2026, 8, 1, 12, 0, 0, 0, time.UTC)
	times := map[string]time.Time{
		"a":   base,
		"b":   base.Add(24 * time.Hour),
		"c":   base.Add(48 * time.Hour),
		"d":   base.Add(72 * time.Hour),
		"e":   base.Add(96 * time.Hour),
		"old": base.AddDate(0, 0, -12),
	}

	tr, outliers := timeRangeAndOutliers(times, 7)
	if tr.Min == "" || tr.Max == "" {
		t.Fatalf("expected non-empty time range, got %+v", tr)
	}
	if len(outliers) != 1 || outliers[0].Name != "old" {
		t.Fatalf("expected 1 outlier 'old', got %v", outliers)
	}
}

func TestTimeRangeAndOutliersNoGap(t *testing.T) {
	base := time.Date(2026, 8, 1, 12, 0, 0, 0, time.UTC)
	times := map[string]time.Time{
		"a": base,
		"b": base.Add(24 * time.Hour),
		"c": base.Add(48 * time.Hour),
	}
	_, outliers := timeRangeAndOutliers(times, 7)
	if len(outliers) != 0 {
		t.Fatalf("expected no outliers, got %v", outliers)
	}
}

func TestExifShotAt(t *testing.T) {
	dir := t.TempDir()
	shotAt := time.Date(2026, 8, 5, 12, 34, 56, 0, time.UTC)
	jpeg := filepath.Join(dir, "IMG_0001.JPG")
	writeFile(t, jpeg, buildExifJpeg(shotAt))

	got, ok := exifShotAt(jpeg)
	if !ok {
		t.Fatal("expected EXIF time to be read")
	}
	if got.Format("2006-01-02 15:04:05") != shotAt.Format("2006-01-02 15:04:05") {
		t.Fatalf("shot time mismatch: got %v, want %v", got, shotAt)
	}
}

func TestExifShotAtNoExif(t *testing.T) {
	dir := t.TempDir()
	jpeg := filepath.Join(dir, "IMG_0001.JPG")
	writeFile(t, jpeg, []byte("not a real jpeg"))

	if _, ok := exifShotAt(jpeg); ok {
		t.Fatal("expected no EXIF time for invalid file")
	}
}

func TestCreateStagingDirs(t *testing.T) {
	dir := t.TempDir()
	staging := filepath.Join(dir, "staging")

	res, err := createStagingDirs(staging, testFolder)
	if err != nil {
		t.Fatal(err)
	}
	for _, d := range res.Dirs {
		if d.Status != "created" {
			t.Fatalf("dir %s status = %s, want created", d.Name, d.Status)
		}
		if _, err := os.Stat(d.Path); err != nil {
			t.Fatalf("dir %s not created: %v", d.Name, err)
		}
	}

	res2, _ := createStagingDirs(staging, testFolder)
	for _, d := range res2.Dirs {
		if d.Status != "existed" {
			t.Fatalf("dir %s status = %s, want existed", d.Name, d.Status)
		}
	}
}

func TestScanStaging(t *testing.T) {
	dir := t.TempDir()
	staging := filepath.Join(dir, "staging")
	if _, err := createStagingDirs(staging, testFolder); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(staging, "full", testFolder, "A.JPG"), []byte("x"))
	writeFile(t, filepath.Join(staging, "full", testFolder, "B.jpeg"), []byte("x"))
	writeFile(t, filepath.Join(staging, "full", testFolder, "skip.txt"), []byte("x"))
	writeFile(t, filepath.Join(staging, "like", testFolder, "C.JPG"), []byte("x"))
	writeFile(t, filepath.Join(staging, "nef", testFolder, "D.NEF"), []byte("x"))

	scan, err := scanStaging(staging, testFolder)
	if err != nil {
		t.Fatal(err)
	}
	if scan.Full.Count != 2 || scan.Like.Count != 1 || scan.Nef.Count != 1 {
		t.Fatalf("scan counts wrong: full=%d like=%d nef=%d", scan.Full.Count, scan.Like.Count, scan.Nef.Count)
	}
}

func TestAnalyzeStaging(t *testing.T) {
	dir := t.TempDir()
	staging := filepath.Join(dir, "staging")
	if _, err := createStagingDirs(staging, testFolder); err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)

	writeFile(t, filepath.Join(staging, "full", testFolder, "IMG_0001.JPG"), buildExifJpeg(base))
	writeFile(t, filepath.Join(staging, "full", testFolder, "IMG_0002.JPG"), buildExifJpeg(base.Add(24*time.Hour)))
	writeFile(t, filepath.Join(staging, "full", testFolder, "IMG_0003.JPG"), buildExifJpeg(base.Add(48*time.Hour)))
	writeFile(t, filepath.Join(staging, "like", testFolder, "IMG_0002.JPG"), buildExifJpeg(base.Add(24*time.Hour)))
	writeFile(t, filepath.Join(staging, "nef", testFolder, "IMG_0001.NEF"), []byte("n1"))
	writeFile(t, filepath.Join(staging, "nef", testFolder, "IMG_0002.NEF"), []byte("n2"))
	writeFile(t, filepath.Join(staging, "nef", testFolder, "IMG_0003.NEF"), []byte("n3"))

	analysis, err := analyzeStaging(staging, testFolder)
	if err != nil {
		t.Fatal(err)
	}
	if analysis.FullJpgCount != 3 || analysis.LikeJpgCount != 1 || analysis.NefCount != 3 {
		t.Fatalf("counts wrong: %+v", analysis)
	}
	if analysis.FavoriteCount != 1 || analysis.RetainedCount != 2 {
		t.Fatalf("favorite/retained wrong: favorite=%d retained=%d", analysis.FavoriteCount, analysis.RetainedCount)
	}
	if analysis.DiscardedCount != 0 {
		t.Fatalf("expected 0 discarded, got %d", analysis.DiscardedCount)
	}
	if analysis.MigratedCount != 0 {
		t.Fatalf("expected 0 migrated, got %d", analysis.MigratedCount)
	}
	if len(analysis.FavoriteList) != 1 || analysis.FavoriteList[0].Name != "IMG_0002.NEF" {
		t.Fatalf("favorite list wrong: %+v", analysis.FavoriteList)
	}
	if analysis.FavoriteList[0].ShotAt == "" {
		t.Fatal("expected shot_at on favorite decision")
	}
	if len(analysis.Outliers) != 0 || len(analysis.NoDate) != 0 {
		t.Fatalf("unexpected outliers/no_date: %+v", analysis)
	}
	if analysis.Outliers == nil || analysis.MissingNef == nil ||
		analysis.FavoriteList == nil || analysis.NoDate == nil {
		t.Fatalf("expected non-nil empty slices for JSON serialization: %+v", analysis)
	}
}

func TestAnalyzeStagingDetectsOutlier(t *testing.T) {
	dir := t.TempDir()
	staging := filepath.Join(dir, "staging")
	if _, err := createStagingDirs(staging, testFolder); err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)

	writeFile(t, filepath.Join(staging, "full", testFolder, "IMG_0001.JPG"), buildExifJpeg(base))
	writeFile(t, filepath.Join(staging, "full", testFolder, "IMG_0002.JPG"), buildExifJpeg(base.Add(24*time.Hour)))
	writeFile(t, filepath.Join(staging, "full", testFolder, "IMG_0003.JPG"), buildExifJpeg(base.AddDate(0, 0, -12)))
	writeFile(t, filepath.Join(staging, "nef", testFolder, "IMG_0001.NEF"), []byte("n1"))
	writeFile(t, filepath.Join(staging, "nef", testFolder, "IMG_0002.NEF"), []byte("n2"))
	writeFile(t, filepath.Join(staging, "nef", testFolder, "IMG_0003.NEF"), []byte("n3"))

	analysis, err := analyzeStaging(staging, testFolder)
	if err != nil {
		t.Fatal(err)
	}
	if len(analysis.Outliers) != 1 || analysis.Outliers[0].Name != "img_0003" {
		t.Fatalf("expected outlier img_0003, got %+v", analysis.Outliers)
	}
}

func TestAnalyzeStagingMigrated(t *testing.T) {
	dir := t.TempDir()
	staging := filepath.Join(dir, "staging")
	if _, err := createStagingDirs(staging, testFolder); err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)
	writeFile(t, filepath.Join(staging, "full", testFolder, "IMG_0001.JPG"), buildExifJpeg(base))
	writeFile(t, filepath.Join(staging, "like", testFolder, "IMG_0001.JPG"), buildExifJpeg(base))
	// 迁移已发生：like 中已有对应 NEF
	writeFile(t, filepath.Join(staging, "like", testFolder, "IMG_0001.NEF"), []byte("n1"))
	writeFile(t, filepath.Join(staging, "nef", testFolder, "IMG_0001.NEF"), []byte("n1"))

	analysis, err := analyzeStaging(staging, testFolder)
	if err != nil {
		t.Fatal(err)
	}
	if analysis.FavoriteCount != 0 {
		t.Fatalf("expected 0 favorite after migration, got %d", analysis.FavoriteCount)
	}
	if analysis.MigratedCount != 1 {
		t.Fatalf("expected 1 migrated, got %d", analysis.MigratedCount)
	}
}

func TestAnalyzeStagingMissingNef(t *testing.T) {
	dir := t.TempDir()
	staging := filepath.Join(dir, "staging")
	if _, err := createStagingDirs(staging, testFolder); err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)
	writeFile(t, filepath.Join(staging, "full", testFolder, "IMG_0001.JPG"), buildExifJpeg(base))
	writeFile(t, filepath.Join(staging, "full", testFolder, "IMG_0002.JPG"), buildExifJpeg(base.Add(24*time.Hour)))
	writeFile(t, filepath.Join(staging, "nef", testFolder, "IMG_0001.NEF"), []byte("n1"))

	analysis, err := analyzeStaging(staging, testFolder)
	if err != nil {
		t.Fatal(err)
	}
	if len(analysis.MissingNef) != 1 {
		t.Fatalf("expected 1 missing NEF, got %+v", analysis.MissingNef)
	}
	got := analysis.MissingNef[0]
	if got.Name != "IMG_0002.JPG" || got.Dir != "full" {
		t.Fatalf("missing NEF ref wrong: %+v", got)
	}
	if got.Path != filepath.Join(staging, "full", testFolder, "IMG_0002.JPG") {
		t.Fatalf("missing NEF path wrong: %+v", got)
	}
}

func TestPreviewImage(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "x.JPG")
	data := []byte{0xff, 0xd8, 0xff, 0xd9}
	writeFile(t, path, data)

	b64, err := previewImage(path)
	if err != nil {
		t.Fatal(err)
	}
	if b64 != base64.StdEncoding.EncodeToString(data) {
		t.Fatalf("preview base64 mismatch: got %q", b64)
	}
}

func TestCopyFilePreservesModTime(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src.nef")
	dst := filepath.Join(dir, "sub", "dst.nef")
	writeFile(t, src, []byte("nef-data"))

	modTime := time.Date(2026, 8, 8, 13, 13, 38, 0, time.UTC)
	if err := os.Chtimes(src, modTime, modTime); err != nil {
		t.Fatal(err)
	}

	if err := copyFile(src, dst); err != nil {
		t.Fatal(err)
	}

	info, err := os.Stat(dst)
	if err != nil {
		t.Fatal(err)
	}
	if !info.ModTime().Equal(modTime) {
		t.Errorf("dst mtime not preserved: got %v, want %v", info.ModTime(), modTime)
	}
}

func TestScanDirPopulatesShotTime(t *testing.T) {
	dir := t.TempDir()
	shotAt := time.Date(2026, 8, 2, 10, 0, 0, 0, time.UTC)
	writeFile(t, filepath.Join(dir, "with_exif.JPG"), buildExifJpeg(shotAt))
	writeFile(t, filepath.Join(dir, "no_exif.JPG"), []byte("not a jpeg with exif"))

	files, err := scanDir(dir, isJpg)
	if err != nil {
		t.Fatal(err)
	}
	byName := map[string]FileInfo{}
	for _, f := range files {
		byName[f.Name] = f
	}
	if got := byName["with_exif.JPG"].ShotTime; got == 0 {
		t.Errorf("expected non-zero shot_time for with_exif.JPG")
	}
	if got := byName["no_exif.JPG"].ShotTime; got != 0 {
		t.Errorf("expected zero shot_time for no_exif.JPG, got %d", got)
	}
}

func TestMigrateKeptNefCopiesOnly(t *testing.T) {
	dir := t.TempDir()
	staging := filepath.Join(dir, "staging")
	if _, err := createStagingDirs(staging, testFolder); err != nil {
		t.Fatal(err)
	}
	nefDir := filepath.Join(staging, "nef", testFolder)
	likeDir := filepath.Join(staging, "like", testFolder)

	writeFile(t, filepath.Join(nefDir, "IMG_0001.NEF"), []byte("nef1"))
	writeFile(t, filepath.Join(nefDir, "IMG_0002.NEF"), []byte("nef2"))

	res, err := migrateKeptNef(staging, testFolder, []string{"IMG_0001.NEF"})
	if err != nil {
		t.Fatal(err)
	}
	if res.MigratedCount != 1 || len(res.Migrated) != 1 || res.Migrated[0] != "IMG_0001.NEF" {
		t.Fatalf("migrate result wrong: %+v", res)
	}
	if len(res.Failed) != 0 {
		t.Fatalf("unexpected failures: %+v", res.Failed)
	}

	// like/ 中应有复制来的文件
	if _, err := os.Stat(filepath.Join(likeDir, "IMG_0001.NEF")); err != nil {
		t.Fatalf("migrated file missing in like/: %v", err)
	}
	// nef/ 中源文件应保留（仅复制、不删除）
	for _, name := range []string{"IMG_0001.NEF", "IMG_0002.NEF"} {
		if _, err := os.Stat(filepath.Join(nefDir, name)); err != nil {
			t.Fatalf("nef/ source %s should remain: %v", name, err)
		}
	}
}

package main

import (
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
	full := []FileInfo{
		{Name: "IMG_0001.JPG"}, {Name: "IMG_0002.JPG"}, {Name: "IMG_0003.JPG"}, {Name: "IMG_0004.JPG"},
	}
	like := []FileInfo{{Name: "IMG_0002.JPG"}}
	nef := []FileInfo{
		{Name: "IMG_0001.NEF"}, {Name: "IMG_0002.NEF"}, {Name: "IMG_0003.NEF"}, {Name: "ORPHAN.NEF"},
	}

	keep, del, unmatched, missing := compareNef(full, like, nef)

	assertStrSlice(t, keep, []string{"IMG_0002.NEF"})
	assertStrSlice(t, del, []string{"IMG_0001.NEF", "IMG_0003.NEF"})
	assertStrSlice(t, unmatched, []string{"ORPHAN.NEF"})
	assertStrSlice(t, missing, []string{"img_0004"})
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

	res, err := createStagingDirs(staging)
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

	res2, _ := createStagingDirs(staging)
	for _, d := range res2.Dirs {
		if d.Status != "existed" {
			t.Fatalf("dir %s status = %s, want existed", d.Name, d.Status)
		}
	}
}

func TestScanStaging(t *testing.T) {
	dir := t.TempDir()
	staging := filepath.Join(dir, "staging")
	if _, err := createStagingDirs(staging); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(staging, "full", "A.JPG"), []byte("x"))
	writeFile(t, filepath.Join(staging, "full", "B.jpeg"), []byte("x"))
	writeFile(t, filepath.Join(staging, "full", "skip.txt"), []byte("x"))
	writeFile(t, filepath.Join(staging, "like", "C.JPG"), []byte("x"))
	writeFile(t, filepath.Join(staging, "nef", "D.NEF"), []byte("x"))

	scan, err := scanStaging(staging)
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
	if _, err := createStagingDirs(staging); err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)

	writeFile(t, filepath.Join(staging, "full", "IMG_0001.JPG"), buildExifJpeg(base))
	writeFile(t, filepath.Join(staging, "full", "IMG_0002.JPG"), buildExifJpeg(base.Add(24*time.Hour)))
	writeFile(t, filepath.Join(staging, "full", "IMG_0003.JPG"), buildExifJpeg(base.Add(48*time.Hour)))
	writeFile(t, filepath.Join(staging, "like", "IMG_0002.JPG"), buildExifJpeg(base.Add(24*time.Hour)))
	writeFile(t, filepath.Join(staging, "nef", "IMG_0001.NEF"), []byte("n1"))
	writeFile(t, filepath.Join(staging, "nef", "IMG_0002.NEF"), []byte("n2"))
	writeFile(t, filepath.Join(staging, "nef", "IMG_0003.NEF"), []byte("n3"))

	analysis, err := analyzeStaging(staging)
	if err != nil {
		t.Fatal(err)
	}
	if analysis.FullJpgCount != 3 || analysis.LikeJpgCount != 1 || analysis.NefCount != 3 {
		t.Fatalf("counts wrong: %+v", analysis)
	}
	if analysis.KeepCount != 1 || analysis.DeleteCount != 2 {
		t.Fatalf("keep/delete wrong: keep=%d delete=%d", analysis.KeepCount, analysis.DeleteCount)
	}
	if len(analysis.KeepList) != 1 || analysis.KeepList[0].Name != "IMG_0002.NEF" {
		t.Fatalf("keep list wrong: %+v", analysis.KeepList)
	}
	if analysis.KeepList[0].ShotAt == "" {
		t.Fatal("expected shot_at on keep decision")
	}
	if len(analysis.Outliers) != 0 || len(analysis.NoDateList) != 0 {
		t.Fatalf("unexpected outliers/no_date: %+v", analysis)
	}
}

func TestAnalyzeStagingDetectsOutlier(t *testing.T) {
	dir := t.TempDir()
	staging := filepath.Join(dir, "staging")
	if _, err := createStagingDirs(staging); err != nil {
		t.Fatal(err)
	}
	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)

	writeFile(t, filepath.Join(staging, "full", "IMG_0001.JPG"), buildExifJpeg(base))
	writeFile(t, filepath.Join(staging, "full", "IMG_0002.JPG"), buildExifJpeg(base.Add(24*time.Hour)))
	writeFile(t, filepath.Join(staging, "full", "IMG_0003.JPG"), buildExifJpeg(base.AddDate(0, 0, -12)))
	writeFile(t, filepath.Join(staging, "nef", "IMG_0001.NEF"), []byte("n1"))
	writeFile(t, filepath.Join(staging, "nef", "IMG_0002.NEF"), []byte("n2"))
	writeFile(t, filepath.Join(staging, "nef", "IMG_0003.NEF"), []byte("n3"))

	analysis, err := analyzeStaging(staging)
	if err != nil {
		t.Fatal(err)
	}
	if len(analysis.Outliers) != 1 || analysis.Outliers[0].Name != "img_0003" {
		t.Fatalf("expected outlier img_0003, got %+v", analysis.Outliers)
	}
}

func TestMigrateKeptNefCopiesOnly(t *testing.T) {
	dir := t.TempDir()
	staging := filepath.Join(dir, "staging")
	if _, err := createStagingDirs(staging); err != nil {
		t.Fatal(err)
	}
	nefDir := filepath.Join(staging, "nef")
	likeDir := filepath.Join(staging, "like")

	writeFile(t, filepath.Join(nefDir, "IMG_0001.NEF"), []byte("nef1"))
	writeFile(t, filepath.Join(nefDir, "IMG_0002.NEF"), []byte("nef2"))

	res, err := migrateKeptNef(staging, []string{"IMG_0001.NEF"})
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

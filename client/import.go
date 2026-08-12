package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/rwcarlsen/goexif/exif"
)

// ================================================================
// 中转目录导入工作流：本地文件操作核心逻辑。
// 纯函数、不依赖 Wails，便于单元测试。绑定方法见 app.go。
// ================================================================

// 相邻拍摄时间最大间隙超过该天数时，判定较小一侧为「混入其他活动」。
const outlierGapDays = 7

// stagingSubDirs 中转目录下的固定子目录。
var stagingSubDirs = []string{"full", "like", "nef"}

// ================================================================
// 类型定义（经 Wails 绑定序列化为 JS 对象）
// ================================================================

// FileInfo 单个文件的基础信息。
type FileInfo struct {
	Name    string `json:"name"`
	Size    int64  `json:"size"`
	ModTime int64  `json:"mod_time"`
}

// DirFileList 某个中转子目录的文件清单。
type DirFileList struct {
	Dir   string     `json:"dir"`
	Count int        `json:"count"`
	Files []FileInfo `json:"files"`
}

// StagingScan 中转目录扫描结果。
type StagingScan struct {
	StagingPath string      `json:"staging_path"`
	Full        DirFileList `json:"full"`
	Like        DirFileList `json:"like"`
	Nef         DirFileList `json:"nef"`
}

// NefDecision 单个 NEF 的保留/删除决策，ShotAt 为对应 JPG 的拍摄时间。
type NefDecision struct {
	Name   string `json:"name"`
	ShotAt string `json:"shot_at,omitempty"`
}

// OutlierFile 拍摄时间偏离主要范围的文件。
type OutlierFile struct {
	Name   string `json:"name"`
	ShotAt string `json:"shot_at"`
}

// TimeRange 拍摄时间范围。
type TimeRange struct {
	Min string `json:"min,omitempty"`
	Max string `json:"max,omitempty"`
}

// ImportAnalysis 中转目录分析结果。
type ImportAnalysis struct {
	FullJpgCount     int           `json:"full_jpg_count"`
	LikeJpgCount     int           `json:"like_jpg_count"`
	NefCount         int           `json:"nef_count"`
	KeepCount        int           `json:"keep_count"`
	DeleteCount      int           `json:"delete_count"`
	KeepList         []NefDecision `json:"keep_list"`
	DeleteList       []NefDecision `json:"delete_list"`
	MissingNefList   []string      `json:"missing_nef_list"`
	UnmatchedNefList []string      `json:"unmatched_nef_list"`
	TimeRange        TimeRange     `json:"time_range"`
	Outliers         []OutlierFile `json:"outliers"`
	NoDateList       []string      `json:"no_date_list"`
}

// StagingDir 单个中转目录的创建状态。
type StagingDir struct {
	Name   string `json:"name"`
	Path   string `json:"path"`
	Status string `json:"status"` // created / existed / failed
}

// CreateStagingResult 创建中转目录的结果。
type CreateStagingResult struct {
	StagingPath string       `json:"staging_path"`
	Dirs        []StagingDir `json:"dirs"`
}

// MigrateFailure 单个 NEF 复制失败信息。
type MigrateFailure struct {
	Name   string `json:"name"`
	Reason string `json:"reason"`
}

// MigrateResult 复制保留 NEF 的结果。
type MigrateResult struct {
	MigratedCount int              `json:"migrated_count"`
	Migrated      []string         `json:"migrated"`
	Failed        []MigrateFailure `json:"failed"`
}

// fileTime 文件基础名与其拍摄时间。
type fileTime struct {
	name string
	t    time.Time
}

// ================================================================
// 工具函数
// ================================================================

// baseNameOf 返回文件名去掉扩展名后的小写基础名。
func baseNameOf(name string) string {
	ext := filepath.Ext(name)
	return strings.ToLower(strings.TrimSuffix(name, ext))
}

// isJpg 判断文件名是否为 JPG 图片。
func isJpg(name string) bool {
	ext := strings.ToLower(filepath.Ext(name))
	return ext == ".jpg" || ext == ".jpeg"
}

// isNef 判断文件名是否为 NEF 原始文件。
func isNef(name string) bool {
	return strings.ToLower(filepath.Ext(name)) == ".nef"
}

// scanDir 扫描目录，返回满足 filter 的非目录文件列表（按名称升序）。
func scanDir(dir string, filter func(string) bool) ([]FileInfo, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	files := make([]FileInfo, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		if filter != nil && !filter(e.Name()) {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		files = append(files, FileInfo{
			Name:    e.Name(),
			Size:    info.Size(),
			ModTime: info.ModTime().Unix(),
		})
	}
	sort.Slice(files, func(i, j int) bool { return files[i].Name < files[j].Name })
	return files, nil
}

// exifShotAt 读取文件 EXIF 拍摄时间。
func exifShotAt(path string) (time.Time, bool) {
	f, err := os.Open(path)
	if err != nil {
		return time.Time{}, false
	}
	defer f.Close()

	x, err := exif.Decode(f)
	if err != nil {
		return time.Time{}, false
	}
	t, err := x.DateTime()
	if err != nil {
		return time.Time{}, false
	}
	return t, true
}

// copyFile 复制文件内容到目标路径（自动创建父目录）。
func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return err
	}
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()

	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	return out.Sync()
}

// ================================================================
// 核心逻辑
// ================================================================

// createStagingDirs 在中转路径下创建 full/like/nef 三个子目录。
func createStagingDirs(stagingPath string) (*CreateStagingResult, error) {
	if strings.TrimSpace(stagingPath) == "" {
		return nil, fmt.Errorf("中转目录路径为空")
	}
	result := &CreateStagingResult{
		StagingPath: stagingPath,
		Dirs:        make([]StagingDir, 0, len(stagingSubDirs)),
	}
	for _, name := range stagingSubDirs {
		dir := filepath.Join(stagingPath, name)
		sd := StagingDir{Name: name, Path: dir}
		if info, err := os.Stat(dir); err == nil && info.IsDir() {
			sd.Status = "existed"
		} else if err := os.MkdirAll(dir, 0755); err != nil {
			sd.Status = "failed"
		} else {
			sd.Status = "created"
		}
		result.Dirs = append(result.Dirs, sd)
	}
	return result, nil
}

// scanStaging 扫描中转目录，返回三目录的文件列表与计数。
func scanStaging(stagingPath string) (*StagingScan, error) {
	full, err := scanDir(filepath.Join(stagingPath, "full"), isJpg)
	if err != nil {
		return nil, err
	}
	like, err := scanDir(filepath.Join(stagingPath, "like"), isJpg)
	if err != nil {
		return nil, err
	}
	nef, err := scanDir(filepath.Join(stagingPath, "nef"), isNef)
	if err != nil {
		return nil, err
	}
	return &StagingScan{
		StagingPath: stagingPath,
		Full:        DirFileList{Dir: "full", Count: len(full), Files: full},
		Like:        DirFileList{Dir: "like", Count: len(like), Files: like},
		Nef:         DirFileList{Dir: "nef", Count: len(nef), Files: nef},
	}, nil
}

// analyzeStaging 比对 full/like/nef，产出保留/删除分类、时间范围与异常检测。
func analyzeStaging(stagingPath string) (*ImportAnalysis, error) {
	fullDir := filepath.Join(stagingPath, "full")
	likeDir := filepath.Join(stagingPath, "like")
	nefDir := filepath.Join(stagingPath, "nef")

	fullFiles, err := scanDir(fullDir, isJpg)
	if err != nil {
		return nil, err
	}
	likeFiles, err := scanDir(likeDir, isJpg)
	if err != nil {
		return nil, err
	}
	nefFiles, err := scanDir(nefDir, isNef)
	if err != nil {
		return nil, err
	}

	keep, del, unmatched, missing := compareNef(fullFiles, likeFiles, nefFiles)
	times, noDate := collectJpgTimes(fullDir, likeDir, fullFiles, likeFiles)
	tr, outliers := timeRangeAndOutliers(times, outlierGapDays)

	return &ImportAnalysis{
		FullJpgCount:     len(fullFiles),
		LikeJpgCount:     len(likeFiles),
		NefCount:         len(nefFiles),
		KeepCount:        len(keep),
		DeleteCount:      len(del),
		KeepList:         buildDecisionList(keep, times),
		DeleteList:       buildDecisionList(del, times),
		MissingNefList:   missing,
		UnmatchedNefList: unmatched,
		TimeRange:        tr,
		Outliers:         outliers,
		NoDateList:       noDate,
	}, nil
}

// compareNef 比对三目录，返回保留、删除、未匹配的 NEF 文件名，
// 以及缺少 NEF 的 JPG 基础名。
//
// 规则：like 中有同名 JPG 的 NEF 保留；仅 full 中有但 like 中无的 NEF 标记删除；
// full/like 中都没有对应 JPG 的 NEF 记为未匹配（不自动处理）。
func compareNef(fullFiles, likeFiles, nefFiles []FileInfo) (keep, del, unmatched, missing []string) {
	jpgSet := make(map[string]bool, len(fullFiles)+len(likeFiles))
	likeSet := make(map[string]bool, len(likeFiles))
	for _, f := range fullFiles {
		jpgSet[baseNameOf(f.Name)] = true
	}
	for _, f := range likeFiles {
		base := baseNameOf(f.Name)
		jpgSet[base] = true
		likeSet[base] = true
	}

	nefMap := make(map[string]string, len(nefFiles))
	for _, f := range nefFiles {
		nefMap[baseNameOf(f.Name)] = f.Name
	}

	for base, name := range nefMap {
		switch {
		case likeSet[base]:
			keep = append(keep, name)
		case jpgSet[base]:
			del = append(del, name)
		default:
			unmatched = append(unmatched, name)
		}
	}

	for base := range jpgSet {
		if _, ok := nefMap[base]; !ok {
			missing = append(missing, base)
		}
	}

	sort.Strings(keep)
	sort.Strings(del)
	sort.Strings(unmatched)
	sort.Strings(missing)
	return
}

// collectJpgTimes 读取 full/ 与 like/ 下 JPG 的 EXIF 拍摄时间（按基础名去重），
// 返回基础名到时间的映射，以及无拍摄时间的 JPG 文件名。
func collectJpgTimes(fullDir, likeDir string, fullFiles, likeFiles []FileInfo) (map[string]time.Time, []string) {
	times := make(map[string]time.Time)
	seen := make(map[string]bool)
	var noDate []string

	scan := func(dir string, files []FileInfo) {
		for _, f := range files {
			base := baseNameOf(f.Name)
			if seen[base] {
				continue
			}
			seen[base] = true
			t, ok := exifShotAt(filepath.Join(dir, f.Name))
			if !ok {
				noDate = append(noDate, f.Name)
				continue
			}
			times[base] = t
		}
	}
	scan(fullDir, fullFiles)
	scan(likeDir, likeFiles)
	sort.Strings(noDate)
	return times, noDate
}

// timeRangeAndOutliers 基于拍摄时间计算时间范围，并用相邻最大间隙检测混入文件。
// 排序后找出相邻时间最大间隙，若超过 gapDays 天，则将较小一侧判为异常。
func timeRangeAndOutliers(times map[string]time.Time, gapDays int) (TimeRange, []OutlierFile) {
	ft := make([]fileTime, 0, len(times))
	for base, t := range times {
		ft = append(ft, fileTime{name: base, t: t})
	}
	sort.Slice(ft, func(i, j int) bool { return ft[i].t.Before(ft[j].t) })

	tr := TimeRange{}
	if len(ft) == 0 {
		return tr, nil
	}
	tr.Min = ft[0].t.Format(time.RFC3339)
	tr.Max = ft[len(ft)-1].t.Format(time.RFC3339)

	maxGap := 0
	maxGapIdx := -1
	for i := 1; i < len(ft); i++ {
		gap := int(ft[i].t.Sub(ft[i-1].t).Hours() / 24)
		if gap > maxGap {
			maxGap = gap
			maxGapIdx = i
		}
	}
	if maxGapIdx <= 0 || maxGap < gapDays {
		return tr, nil
	}

	left := ft[:maxGapIdx]
	right := ft[maxGapIdx:]
	var outliers []fileTime
	if len(left) <= len(right) {
		outliers = left
	} else {
		outliers = right
	}

	result := make([]OutlierFile, 0, len(outliers))
	for _, o := range outliers {
		result = append(result, OutlierFile{Name: o.name, ShotAt: o.t.Format(time.RFC3339)})
	}
	return tr, result
}

// buildDecisionList 将 NEF 文件名列表转为带拍摄时间的决策列表，按时间倒序。
func buildDecisionList(names []string, times map[string]time.Time) []NefDecision {
	list := make([]NefDecision, 0, len(names))
	for _, name := range names {
		d := NefDecision{Name: name}
		if t, ok := times[baseNameOf(name)]; ok {
			d.ShotAt = t.Format(time.RFC3339)
		}
		list = append(list, d)
	}
	sort.SliceStable(list, func(i, j int) bool { return list[i].ShotAt > list[j].ShotAt })
	return list
}

// migrateKeptNef 将保留的 NEF 从 nef/ 复制到 like/。
// 仅复制、不删除任何文件，nef/ 目录保持原样，交由用户自行确认后清理。
func migrateKeptNef(stagingPath string, keepList []string) (*MigrateResult, error) {
	if strings.TrimSpace(stagingPath) == "" {
		return nil, fmt.Errorf("中转目录路径为空")
	}
	nefDir := filepath.Join(stagingPath, "nef")
	likeDir := filepath.Join(stagingPath, "like")

	result := &MigrateResult{
		Migrated: []string{},
		Failed:   []MigrateFailure{},
	}
	for _, name := range keepList {
		src := filepath.Join(nefDir, name)
		dst := filepath.Join(likeDir, name)
		if err := copyFile(src, dst); err != nil {
			result.Failed = append(result.Failed, MigrateFailure{Name: name, Reason: err.Error()})
			continue
		}
		result.Migrated = append(result.Migrated, name)
	}
	result.MigratedCount = len(result.Migrated)
	return result, nil
}

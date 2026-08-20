package data

import (
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"backend/internal/pkg/db"
	"backend/internal/pkg/db/model"
	"backend/internal/pkg/perr"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"gorm.io/gen/field"
	"gorm.io/gorm/clause"
)

// rawCond wraps a raw SQL expression as a gen-compatible condition,
// for use with generated Where() when the condition can't be expressed via field methods.
func rawCond(sql string, vars ...any) rawCondition {
	return rawCondition{Expr: clause.Expr{SQL: sql, Vars: vars}}
}

type rawCondition struct {
	clause.Expr
}

func (r rawCondition) BeCond() any      { return r.Expr }
func (r rawCondition) CondError() error { return nil }

// GetPhotoListParams 照片列表查询参数
type GetPhotoListParams struct {
	Page         int
	PageSize     int
	Timeline     string
	Tag          string
	Keyword      string
	Brand        string
	Lens         string
	FocalMin     string
	FocalMax     string
	ISOMin       int32
	ISOMax       int32
	ShotAtStart  string
	ShotAtEnd    string
	SortBy       string
	SortOrder    string
	BurstGroupID string
	BurstProfile string // fine / coarse（缺省 fine），决定组过滤与展示字段所用列
}

// TimelineNoneSentinel timeline 筛选的 sentinel 值，表示「无活动标签」照片。
// 空串在筛选参数中含义是「不过滤」，散图筛选需要独立取值。
const TimelineNoneSentinel = "none"

// GetPhotoList 查询照片列表（分页、过滤、排序）
func (*photoDAO) GetPhotoList(ctx *papp.AppCtx, params GetPhotoListParams) ([]*model.Photo, int64, error) {
	if params.Page < 1 {
		params.Page = 1
	}
	if params.PageSize < 1 {
		params.PageSize = 20
	}
	if params.PageSize > 100 {
		params.PageSize = 100
	}

	q := db.GetQuery().Photo
	do := q.WithContext(ctx)

	// 图片管理列表不展示 NEF 原始文件（仅存储，不参与展示）。
	do = do.Where(q.FileType.Neq("nef"))

	if params.Timeline != "" {
		if params.Timeline == TimelineNoneSentinel {
			// 前端 sentinel 值：筛出无活动标签的散图（timeline 为空串）
			do = do.Where(q.Timeline.Eq(""))
		} else {
			do = do.Where(q.Timeline.Eq(params.Timeline))
		}
	}
	if params.Tag != "" {
		do = do.Where(q.Tags.Like("%" + params.Tag + "%"))
	}
	if params.Keyword != "" {
		do = do.Where(field.Or(
			q.Description.Like("%"+params.Keyword+"%"),
			q.Filename.Like("%"+params.Keyword+"%"),
		))
	}
	if params.Brand != "" {
		do = do.Where(q.Brand.Eq(params.Brand))
	}
	if params.Lens != "" {
		do = do.Where(q.Lens.Like("%" + params.Lens + "%"))
	}
	if params.FocalMin != "" {
		do = do.Where(rawCond(
			fmt.Sprintf("CAST(REPLACE(%s, 'mm', '') AS REAL) >= ?", string(q.FocalLength.ColumnName())),
			params.FocalMin,
		))
	}
	if params.FocalMax != "" {
		do = do.Where(rawCond(
			fmt.Sprintf("CAST(REPLACE(%s, 'mm', '') AS REAL) <= ?", string(q.FocalLength.ColumnName())),
			params.FocalMax,
		))
	}
	if params.ISOMin > 0 {
		do = do.Where(q.Iso.Gte(params.ISOMin))
	}
	if params.ISOMax > 0 {
		do = do.Where(q.Iso.Lte(params.ISOMax))
	}
	if params.ShotAtStart != "" {
		t, err := parseTimeStr(params.ShotAtStart)
		if err == nil {
			do = do.Where(q.ShotAt.Gte(t))
		}
	}
	if params.ShotAtEnd != "" {
		t, err := parseTimeStr(params.ShotAtEnd)
		if err == nil {
			do = do.Where(q.ShotAt.Lte(t))
		}
	}
	if params.BurstGroupID != "" {
		if params.BurstProfile == "coarse" {
			do = do.Where(q.BurstGroupCoarseID.Eq(params.BurstGroupID))
		} else {
			do = do.Where(q.BurstGroupID.Eq(params.BurstGroupID))
		}
	}

	// 排序
	switch params.SortBy {
	case "filename":
		if params.SortOrder == "desc" {
			do = do.Order(q.Filename.Desc())
		} else {
			do = do.Order(q.Filename.Asc())
		}
	case "shot_at":
		if params.SortOrder == "desc" {
			do = do.Order(q.ShotAt.Desc(), q.ImportedAt.Desc())
		} else {
			do = do.Order(q.ShotAt.Asc(), q.ImportedAt.Asc())
		}
	case "imported_at":
		if params.SortOrder == "desc" {
			do = do.Order(q.ImportedAt.Desc())
		} else {
			do = do.Order(q.ImportedAt.Asc())
		}
	default:
		do = do.Order(q.ShotAt.Desc(), q.ImportedAt.Desc())
	}

	offset := (params.Page - 1) * params.PageSize
	photos, total, err := do.FindByPage(offset, params.PageSize)
	if err != nil {
		return nil, 0, fmt.Errorf("query photos failed: %w", err)
	}
	return photos, total, nil
}

// GetByFilename 根据文件名精确查询
func (*photoDAO) GetByFilename(ctx *papp.AppCtx, filename string) (*model.Photo, error) {
	if filename == "" {
		return nil, perr.ErrParamInvalid
	}
	q := db.GetQuery().Photo
	photo, err := q.WithContext(ctx).
		Where(q.Filename.Eq(filename)).
		First()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return photo, nil
}

// BaseNameOf 返回文件名去掉扩展名后的小写基础名（如 DSC_1234.JPG → dsc_1234）。
func BaseNameOf(name string) string {
	ext := filepath.Ext(name)
	return strings.ToLower(strings.TrimSuffix(name, ext))
}

// GetNefBaseNames 返回所有 NEF 文件的小写基础名集合，用于判断 JPG 是否有对应原始文件。
func (*photoDAO) GetNefBaseNames(ctx *papp.AppCtx) (map[string]bool, error) {
	q := db.GetQuery().Photo
	var filenames []string
	if err := q.WithContext(ctx).
		Where(q.FileType.Eq("nef")).
		Pluck(q.Filename, &filenames); err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	set := make(map[string]bool, len(filenames))
	for _, name := range filenames {
		set[BaseNameOf(name)] = true
	}
	return set, nil
}

// GetExistingFilenames 返回 names 中已存在于数据库的 filename 集合（精确匹配）。
func (*photoDAO) GetExistingFilenames(ctx *papp.AppCtx, names []string) (map[string]bool, error) {
	if len(names) == 0 {
		return map[string]bool{}, nil
	}
	q := db.GetQuery().Photo
	var existing []string
	if err := q.WithContext(ctx).
		Where(q.Filename.In(names...)).
		Pluck(q.Filename, &existing); err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	set := make(map[string]bool, len(existing))
	for _, n := range existing {
		set[n] = true
	}
	return set, nil
}

// StatItem 单项统计
type StatItem struct {
	Name  string `json:"name"`
	Count int64  `json:"count"`
}

// FocalRangeStat 焦距段统计
type FocalRangeStat struct {
	Range string `json:"range"`
	Label string `json:"label"`
	Count int64  `json:"count"`
}

// GPSStat GPS 统计
type GPSStat struct {
	WithGPS    int64 `json:"with_gps"`
	WithoutGPS int64 `json:"without_gps"`
}

// MonthlyStat 月度统计
type MonthlyStat struct {
	Month string `json:"month"`
	Count int64  `json:"count"`
}

// HourlyStat 时段统计
type HourlyStat struct {
	Hour  int32 `json:"hour"`
	Count int64 `json:"count"`
}

// PhotoStats 综合统计
type PhotoStats struct {
	Total              int64            `json:"total"`
	WithDescription    int64            `json:"with_description"`
	WithoutDescription int64            `json:"without_description"`
	Brands             []StatItem       `json:"brands"`
	Lens               []StatItem       `json:"lens"`
	FocalRanges        []FocalRangeStat `json:"focal_ranges"`
	GPS                GPSStat          `json:"gps"`
	Monthly            []MonthlyStat    `json:"monthly"`
	Hourly             []HourlyStat     `json:"hourly"`
}

// GetPhotoStats 获取综合统计信息
func (*photoDAO) GetPhotoStats(ctx *papp.AppCtx) (*PhotoStats, error) {
	q := db.GetQuery().Photo // 类型安全字段引用
	stats := &PhotoStats{}

	// 总数（图片管理不展示 NEF，统计口径与列表一致，均排除 NEF）
	total, err := q.WithContext(ctx).Where(q.FileType.Neq("nef")).Count()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	stats.Total = total

	// 描述统计
	withDesc, err := q.WithContext(ctx).Where(q.FileType.Neq("nef"), q.Description.Neq("")).Count()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	stats.WithDescription = withDesc
	stats.WithoutDescription = stats.Total - stats.WithDescription

	// 品牌分布
	if err := q.WithContext(ctx).
		Select(q.Brand.As("name"), q.Brand.Count().As("count")).
		Where(q.FileType.Neq("nef"), q.Brand.Neq("")).
		Group(q.Brand).
		Order(q.Brand.Count().Desc()).
		Scan(&stats.Brands); err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 镜头分布
	if err := q.WithContext(ctx).
		Select(q.Lens.As("name"), q.Lens.Count().As("count")).
		Where(q.FileType.Neq("nef"), q.Lens.Neq("")).
		Group(q.Lens).
		Order(q.Lens.Count().Desc()).
		Scan(&stats.Lens); err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// GPS 统计（复杂 CASE WHEN，使用原始 GORM + gen 列名）
	latCol := string(q.Latitude.ColumnName())
	gpsSQL := fmt.Sprintf(
		"COUNT(CASE WHEN %s IS NOT NULL THEN 1 END) as with_gps, "+
			"COUNT(CASE WHEN %s IS NULL THEN 1 END) as without_gps",
		latCol, latCol,
	)
	if err := pdb.GetGormDB().WithContext(ctx).Model(&model.Photo{}).
		Where("file_type != ?", "nef").
		Select(gpsSQL).Scan(&stats.GPS).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 月度分布（SQLite strftime）
	shotCol := string(q.ShotAt.ColumnName())
	monthlySQL := fmt.Sprintf("strftime('%%Y-%%m', %s) as month, COUNT(*) as count", shotCol)
	if err := pdb.GetGormDB().WithContext(ctx).Model(&model.Photo{}).
		Where("file_type != ?", "nef").
		Select(monthlySQL).
		Where(shotCol + " IS NOT NULL").
		Group("month").Order("month").
		Scan(&stats.Monthly).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 时段分布（SQLite strftime + CAST）
	hourlySQL := fmt.Sprintf("CAST(strftime('%%H', %s) AS INTEGER) as hour, COUNT(*) as count", shotCol)
	if err := pdb.GetGormDB().WithContext(ctx).Model(&model.Photo{}).
		Where("file_type != ?", "nef").
		Select(hourlySQL).
		Where(shotCol + " IS NOT NULL").
		Group("hour").Order("hour").
		Scan(&stats.Hourly).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 焦距段分布
	focalRanges, err := computeFocalRangeStats(ctx)
	if err != nil {
		return nil, err
	}
	stats.FocalRanges = focalRanges

	return stats, nil
}

func computeFocalRangeStats(ctx *papp.AppCtx) ([]FocalRangeStat, error) {
	q := db.GetQuery().Photo
	var rows []struct {
		FocalLength string
	}
	if err := q.WithContext(ctx).
		Select(q.FocalLength).
		Where(q.FileType.Neq("nef"), q.FocalLength.Neq("")).
		Scan(&rows); err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	buckets := []struct {
		key   string
		label string
		min   float64
		max   float64
	}{
		{"ultra_wide", "< 24mm", 0, 24},
		{"wide", "24-35mm", 24, 35},
		{"normal", "35-70mm", 35, 70},
		{"telephoto", "70-200mm", 70, 200},
		{"super_telephoto", "> 200mm", 200, 1e9},
	}
	counts := make(map[string]int64)
	unknown := int64(0)

	for _, r := range rows {
		mm := parseFocalLength(r.FocalLength)
		if mm < 0 {
			unknown++
			continue
		}
		found := false
		for _, b := range buckets {
			if mm >= b.min && mm < b.max {
				counts[b.key]++
				found = true
				break
			}
		}
		if !found {
			unknown++
		}
	}

	result := make([]FocalRangeStat, 0, len(buckets))
	for _, b := range buckets {
		result = append(result, FocalRangeStat{
			Range: b.key,
			Label: b.label,
			Count: counts[b.key],
		})
	}
	if unknown > 0 {
		result = append(result, FocalRangeStat{
			Range: "unknown",
			Label: "未知",
			Count: unknown,
		})
	}
	return result, nil
}

// parseTimeStr 尝试常见日期/时间格式解析为 time.Time。
func parseTimeStr(s string) (time.Time, error) {
	formats := []string{
		time.RFC3339,
		"2006-01-02T15:04:05Z",
		"2006-01-02 15:04:05",
		"2006-01-02",
	}
	for _, f := range formats {
		t, err := time.Parse(f, s)
		if err == nil {
			return t, nil
		}
	}
	return time.Time{}, fmt.Errorf("unable to parse time: %s", s)
}

func parseFocalLength(s string) float64 {
	var val float64
	n, err := fmt.Sscanf(s, "%fmm", &val)
	if n == 1 && err == nil {
		return val
	}
	n, err = fmt.Sscanf(s, "%f", &val)
	if n == 1 && err == nil {
		return val
	}
	return -1
}

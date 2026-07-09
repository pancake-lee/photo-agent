package data

import (
	"fmt"
	"strings"

	"backend-new/internal/pkg/db/model"
	"backend-new/internal/pkg/perr"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"gorm.io/gorm"
)

// ListPhotosParams 照片列表查询参数
type ListPhotosParams struct {
	Page        int
	PageSize    int
	Timeline    string
	Tag         string
	Keyword     string
	Brand       string
	Lens        string
	FocalMin    string
	FocalMax    string
	ISOMin      int32
	ISOMax      int32
	ShotAtStart string
	ShotAtEnd   string
	SortBy      string
	SortOrder   string
}

// ListPhotos 查询照片列表（分页、过滤、排序）
func (*photoDAO) ListPhotos(ctx *papp.AppCtx, params ListPhotosParams) ([]*model.Photo, int64, error) {
	if params.Page < 1 {
		params.Page = 1
	}
	if params.PageSize < 1 {
		params.PageSize = 20
	}
	if params.PageSize > 100 {
		params.PageSize = 100
	}

	gdb := pdb.GetGormDB()
	q := gdb.WithContext(ctx).Model(&model.Photo{})

	if params.Timeline != "" {
		q = q.Where("timeline = ?", params.Timeline)
	}
	if params.Tag != "" {
		q = q.Where("tags LIKE ?", "%"+params.Tag+"%")
	}
	if params.Keyword != "" {
		q = q.Where("(description LIKE ? OR filename LIKE ?)",
			"%"+params.Keyword+"%", "%"+params.Keyword+"%")
	}
	if params.Brand != "" {
		q = q.Where("brand = ?", params.Brand)
	}
	if params.Lens != "" {
		q = q.Where("lens LIKE ?", "%"+params.Lens+"%")
	}
	if params.FocalMin != "" {
		q = q.Where("CAST(REPLACE(focal_length, 'mm', '') AS REAL) >= ?", params.FocalMin)
	}
	if params.FocalMax != "" {
		q = q.Where("CAST(REPLACE(focal_length, 'mm', '') AS REAL) <= ?", params.FocalMax)
	}
	if params.ISOMin > 0 {
		q = q.Where("iso >= ?", params.ISOMin)
	}
	if params.ISOMax > 0 {
		q = q.Where("iso <= ?", params.ISOMax)
	}
	if params.ShotAtStart != "" {
		q = q.Where("shot_at >= ?", params.ShotAtStart)
	}
	if params.ShotAtEnd != "" {
		q = q.Where("shot_at <= ?", params.ShotAtEnd)
	}

	var total int64
	if err := q.Count(&total).Error; err != nil {
		return nil, 0, fmt.Errorf("count photos failed: %w", err)
	}

	var photos []*model.Photo
	offset := (params.Page - 1) * params.PageSize
	orderClause := buildOrderClause(params.SortBy, params.SortOrder)

	if err := q.Order(orderClause).Limit(params.PageSize).Offset(offset).Find(&photos).Error; err != nil {
		return nil, 0, fmt.Errorf("query photos failed: %w", err)
	}

	return photos, total, nil
}

// GetPhotosByTimeline 根据时间线查询照片
func (*photoDAO) GetPhotosByTimeline(ctx *papp.AppCtx, timeline string) ([]*model.Photo, error) {
	var photos []*model.Photo
	if err := pdb.GetGormDB().WithContext(ctx).
		Where("timeline = ?", timeline).
		Order("shot_at DESC, imported_at DESC").
		Find(&photos).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return photos, nil
}

// GetPhotosByTag 根据标签查询照片
func (*photoDAO) GetPhotosByTag(ctx *papp.AppCtx, tag string) ([]*model.Photo, error) {
	var photos []*model.Photo
	if err := pdb.GetGormDB().WithContext(ctx).
		Where("tags LIKE ?", "%"+tag+"%").
		Order("shot_at DESC, imported_at DESC").
		Find(&photos).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return photos, nil
}

// GetByFilename 根据文件名精确查询
func (*photoDAO) GetByFilename(ctx *papp.AppCtx, filename string) (*model.Photo, error) {
	if filename == "" {
		return nil, perr.ErrParamInvalid
	}
	var photo model.Photo
	if err := pdb.GetGormDB().WithContext(ctx).
		Where("filename = ?", filename).
		First(&photo).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return &photo, nil
}

// UpdateTags 更新照片标签字段
func (*photoDAO) UpdateTags(ctx *papp.AppCtx, photoID, tags string) error {
	if photoID == "" {
		return perr.ErrParamInvalid
	}
	if err := pdb.GetGormDB().WithContext(ctx).
		Model(&model.Photo{}).
		Where("id = ?", photoID).
		Update("tags", tags).Error; err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
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
	gdb := pdb.GetGormDB().WithContext(ctx)
	stats := &PhotoStats{}

	// 总数
	if err := gdb.Model(&model.Photo{}).Count(&stats.Total).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 描述统计
	if err := gdb.Model(&model.Photo{}).
		Where("description != ''").Count(&stats.WithDescription).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	stats.WithoutDescription = stats.Total - stats.WithDescription

	// 品牌分布
	if err := gdb.Model(&model.Photo{}).
		Select("brand as name, COUNT(*) as count").
		Where("brand != ''").
		Group("brand").Order("count DESC").
		Scan(&stats.Brands).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 镜头分布
	if err := gdb.Model(&model.Photo{}).
		Select("lens as name, COUNT(*) as count").
		Where("lens != ''").
		Group("lens").Order("count DESC").
		Scan(&stats.Lens).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// GPS 统计
	if err := gdb.Model(&model.Photo{}).
		Select("COUNT(CASE WHEN latitude IS NOT NULL THEN 1 END) as with_gps, " +
			"COUNT(CASE WHEN latitude IS NULL THEN 1 END) as without_gps").
		Scan(&stats.GPS).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 月度分布
	if err := gdb.Model(&model.Photo{}).
		Select("strftime('%Y-%m', shot_at) as month, COUNT(*) as count").
		Where("shot_at IS NOT NULL").
		Group("month").Order("month").
		Scan(&stats.Monthly).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 时段分布
	if err := gdb.Model(&model.Photo{}).
		Select("CAST(strftime('%H', shot_at) AS INTEGER) as hour, COUNT(*) as count").
		Where("shot_at IS NOT NULL").
		Group("hour").Order("hour").
		Scan(&stats.Hourly).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 焦距段分布（查询后在 Go 中分桶）
	focalRanges, err := computeFocalRangeStats(ctx, gdb)
	if err != nil {
		return nil, err
	}
	stats.FocalRanges = focalRanges

	return stats, nil
}

func computeFocalRangeStats(ctx *papp.AppCtx, gdb *gorm.DB) ([]FocalRangeStat, error) {
	var rows []struct {
		FocalLength string
	}
	if err := gdb.Model(&model.Photo{}).
		Select("focal_length").
		Where("focal_length != ''").
		Scan(&rows).Error; err != nil {
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

func parseFocalLength(s string) float64 {
	var val float64
	if n, err := fmt.Sscanf(s, "%fmm", &val); n == 1 && err == nil {
		return val
	}
	if n, err := fmt.Sscanf(s, "%f", &val); n == 1 && err == nil {
		return val
	}
	return -1
}

func buildOrderClause(sortBy, sortOrder string) string {
	if sortBy == "" {
		return "shot_at DESC, imported_at DESC"
	}
	dir := "ASC"
	if sortOrder == "desc" {
		dir = "DESC"
	}
	switch sortBy {
	case "filename":
		return fmt.Sprintf("filename %s", dir)
	case "shot_at":
		return fmt.Sprintf("shot_at %s, imported_at %s", dir, dir)
	case "imported_at":
		return fmt.Sprintf("imported_at %s", dir)
	default:
		return "shot_at DESC, imported_at DESC"
	}
}

// ListDistinctTimelines 查询所有不重复的时间线
func (*photoDAO) ListDistinctTimelines(ctx *papp.AppCtx) ([]string, error) {
	var timelines []string
	if err := pdb.GetGormDB().WithContext(ctx).Model(&model.Photo{}).
		Where("timeline != ''").
		Distinct().
		Pluck("timeline", &timelines).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return timelines, nil
}

// ListDistinctTags 查询所有不重复的标签
func (*photoDAO) ListDistinctTags(ctx *papp.AppCtx) ([]string, error) {
	var rows []string
	if err := pdb.GetGormDB().WithContext(ctx).Model(&model.Photo{}).
		Where("tags != ''").
		Distinct().
		Pluck("tags", &rows).Error; err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	tagSet := make(map[string]struct{})
	for _, r := range rows {
		for _, t := range strings.Split(r, ",") {
			t = strings.TrimSpace(t)
			if t != "" {
				tagSet[t] = struct{}{}
			}
		}
	}

	result := make([]string, 0, len(tagSet))
	for t := range tagSet {
		result = append(result, t)
	}
	return result, nil
}

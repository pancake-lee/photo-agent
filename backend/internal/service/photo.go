package service

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/pancake-lee/photo-agent/internal/model"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/satori/go.uuid"
)

// SavePhoto 保存照片元数据到数据库
func SavePhoto(filename, filePath, timeline, tags, description string, width, height int, exifInfo *ExifInfo, objects, colors, scene, lighting, mood, composition string) (*model.Photo, error) {
	photo := &model.Photo{
		ID:          uuid.NewV4().String(),
		Filename:    filename,
		FilePath:    filePath,
		Timeline:    timeline,
		Tags:        tags,
		Description: description,
		Objects:     objects,
		Colors:      colors,
		Scene:       scene,
		Lighting:    lighting,
		Mood:        mood,
		Composition: composition,
		Width:       width,
		Height:      height,
		ImportedAt:  time.Now(),
	}

	if exifInfo != nil {
		photo.ShotAt = exifInfo.ShotAt
		photo.Brand = exifInfo.Brand
		photo.Model = exifInfo.Model
		photo.Lens = exifInfo.Lens
		photo.FocalLength = exifInfo.FocalLength
		photo.Aperture = exifInfo.Aperture
		photo.ISO = exifInfo.ISO
		photo.ExposureTime = exifInfo.ExposureTime
		photo.Latitude = exifInfo.Latitude
		photo.Longitude = exifInfo.Longitude
		photo.Altitude = exifInfo.Altitude
	}

	if err := db.Create(photo).Error; err != nil {
		return nil, fmt.Errorf("create photo failed: %w", err)
	}

	plogger.Infof("Photo saved: id=%s, timeline=%s", photo.ID, timeline)
	return photo, nil
}

// GetPhotoByID 根据 ID 查询照片
func GetPhotoByID(id string) (*model.Photo, error) {
	var photo model.Photo
	if err := db.Where("id = ?", id).First(&photo).Error; err != nil {
		return nil, err
	}
	return &photo, nil
}

// GetPhotoByFilename 根据文件名查询照片
func GetPhotoByFilename(filename string) (*model.Photo, error) {
	var photo model.Photo
	if err := db.Where("filename = ?", filename).First(&photo).Error; err != nil {
		return nil, err
	}
	return &photo, nil
}

// UpdatePhotoTags 更新照片的结构化标签（JSON 字符串）
func UpdatePhotoTags(photoID, tags string) error {
	return db.Model(&model.Photo{}).Where("id = ?", photoID).Update("tags", tags).Error
}

// DeletePhoto 删除照片：从数据库删除记录，并删除磁盘上的原图文件。
// 返回被删除照片的信息（供后续清理使用），若照片不存在则返回 nil。
func DeletePhoto(photoID string) (*model.Photo, error) {
	photo, err := GetPhotoByID(photoID)
	if err != nil {
		return nil, err
	}

	// 删除数据库记录
	if err := db.Delete(&model.Photo{}, "id = ?", photoID).Error; err != nil {
		return nil, fmt.Errorf("delete photo from db failed: %w", err)
	}

	plogger.Infof("Photo deleted from db: id=%s, file=%s", photo.ID, photo.FilePath)
	return photo, nil
}

// ListPhotosParams 照片列表查询参数
type ListPhotosParams struct {
	Page        int    // 页码，从 1 开始
	PageSize    int    // 每页数量
	Timeline    string // 按时间线过滤
	Tag         string // 按标签过滤
	Keyword     string // 按关键词过滤（description 或 filename LIKE）
	Brand       string // 按品牌过滤
	Lens        string // 按镜头过滤（LIKE）
	FocalMin    string // 焦距下限（mm）
	FocalMax    string // 焦距上限（mm）
	ISOMin      int    // ISO 下限
	ISOMax      int    // ISO 上限
	ShotAtStart string // 拍摄时间起始（RFC 3339）
	ShotAtEnd   string // 拍摄时间结束（RFC 3339）
	SortBy      string // 排序字段：filename | shot_at | imported_at
	SortOrder   string // 排序方向：asc | desc（默认 desc）
}

// ListPhotos 查询照片列表（分页、过滤）
func ListPhotos(params ListPhotosParams) ([]model.Photo, int64, error) {
	if params.Page < 1 {
		params.Page = 1
	}
	if params.PageSize < 1 {
		params.PageSize = 20
	}
	if params.PageSize > 100 {
		params.PageSize = 100
	}

	q := db.Model(&model.Photo{})

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

	var photos []model.Photo
	offset := (params.Page - 1) * params.PageSize

	// 动态排序
	orderClause := buildOrderClause(params.SortBy, params.SortOrder)

	if err := q.Order(orderClause).
		Limit(params.PageSize).Offset(offset).
		Find(&photos).Error; err != nil {
		return nil, 0, fmt.Errorf("query photos failed: %w", err)
	}

	return photos, total, nil
}

// GetPhotosByTimeline 根据时间线查询照片
func GetPhotosByTimeline(timeline string) ([]model.Photo, error) {
	var photos []model.Photo
	if err := db.Where("timeline = ?", timeline).
		Order("shot_at DESC, imported_at DESC").
		Find(&photos).Error; err != nil {
		return nil, fmt.Errorf("query photos by timeline failed: %w", err)
	}
	return photos, nil
}

// GetPhotosByTag 根据标签查询照片
func GetPhotosByTag(tag string) ([]model.Photo, error) {
	var photos []model.Photo
	if err := db.Where("tags LIKE ?", "%"+tag+"%").
		Order("shot_at DESC, imported_at DESC").
		Find(&photos).Error; err != nil {
		return nil, fmt.Errorf("query photos by tag failed: %w", err)
	}
	return photos, nil
}

// ListDistinctTimelines 查询所有不重复的时间线
func ListDistinctTimelines() ([]string, error) {
	var timelines []string
	if err := db.Model(&model.Photo{}).
		Where("timeline != ?", "").
		Distinct().
		Pluck("timeline", &timelines).Error; err != nil {
		return nil, fmt.Errorf("query timelines failed: %w", err)
	}
	return timelines, nil
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
	Hour  int   `json:"hour"`
	Count int64 `json:"count"`
}

// PhotoStats 综合统计
type PhotoStats struct {
	Total            int64            `json:"total"`
	WithDescription  int64            `json:"with_description"`
	WithoutDescription int64          `json:"without_description"`
	Brands           []StatItem       `json:"brands"`
	Lens             []StatItem       `json:"lens"`
	FocalRanges      []FocalRangeStat `json:"focal_ranges"`
	GPS              GPSStat          `json:"gps"`
	Monthly          []MonthlyStat    `json:"monthly"`
	Hourly           []HourlyStat     `json:"hourly"`
}

// GetPhotoStats 获取综合统计信息
func GetPhotoStats() (*PhotoStats, error) {
	stats := &PhotoStats{}

	// 总数
	if err := db.Model(&model.Photo{}).Count(&stats.Total).Error; err != nil {
		return nil, fmt.Errorf("count photos failed: %w", err)
	}

	// 描述统计
	if err := db.Model(&model.Photo{}).Where("description != ''").Count(&stats.WithDescription).Error; err != nil {
		return nil, fmt.Errorf("stats with_description failed: %w", err)
	}
	stats.WithoutDescription = stats.Total - stats.WithDescription

	// 品牌分布
	if err := db.Model(&model.Photo{}).
		Select("brand as name, COUNT(*) as count").
		Where("brand != ''").
		Group("brand").
		Order("count DESC").
		Scan(&stats.Brands).Error; err != nil {
		return nil, fmt.Errorf("stats brands failed: %w", err)
	}

	// 镜头分布
	if err := db.Model(&model.Photo{}).
		Select("lens as name, COUNT(*) as count").
		Where("lens != ''").
		Group("lens").
		Order("count DESC").
		Scan(&stats.Lens).Error; err != nil {
		return nil, fmt.Errorf("stats lens failed: %w", err)
	}

	// GPS 统计
	if err := db.Model(&model.Photo{}).
		Select("COUNT(CASE WHEN latitude IS NOT NULL THEN 1 END) as with_gps, COUNT(CASE WHEN latitude IS NULL THEN 1 END) as without_gps").
		Scan(&stats.GPS).Error; err != nil {
		return nil, fmt.Errorf("stats gps failed: %w", err)
	}

	// 月度分布
	if err := db.Model(&model.Photo{}).
		Select("strftime('%Y-%m', shot_at) as month, COUNT(*) as count").
		Where("shot_at IS NOT NULL").
		Group("month").
		Order("month").
		Scan(&stats.Monthly).Error; err != nil {
		return nil, fmt.Errorf("stats monthly failed: %w", err)
	}

	// 时段分布
	if err := db.Model(&model.Photo{}).
		Select("CAST(strftime('%H', shot_at) AS INTEGER) as hour, COUNT(*) as count").
		Where("shot_at IS NOT NULL").
		Group("hour").
		Order("hour").
		Scan(&stats.Hourly).Error; err != nil {
		return nil, fmt.Errorf("stats hourly failed: %w", err)
	}

	// 焦距段分布（在 Go 中完成分桶）
	focalRanges, err := computeFocalRangeStats()
	if err != nil {
		return nil, fmt.Errorf("stats focal ranges failed: %w", err)
	}
	stats.FocalRanges = focalRanges

	return stats, nil
}

// computeFocalRangeStats 统计焦距段分布
// 焦距存储为 "35mm" 格式，需要在 Go 中解析数值并分桶。
func computeFocalRangeStats() ([]FocalRangeStat, error) {
	var rows []struct {
		FocalLength string
	}
	if err := db.Model(&model.Photo{}).
		Select("focal_length").
		Where("focal_length != ''").
		Scan(&rows).Error; err != nil {
		return nil, err
	}

	// 焦距段分桶定义
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

// parseFocalLength 解析 "35mm" 格式的焦距字符串，返回数值（mm）。
// 无法解析时返回 -1。
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

// buildOrderClause 根据排序参数构建 SQL ORDER BY 子句。
func buildOrderClause(sortBy, sortOrder string) string {
	// 默认排序：拍摄时间倒序 + 导入时间倒序
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

// AttributeValues 结构化属性的去重值集合，供 Text-to-SQL prompt 动态拼入。
type AttributeValues struct {
	Objects     []string `json:"objects"`
	Colors      []string `json:"colors"`
	Scene       []string `json:"scene"`
	Lighting    []string `json:"lighting"`
	Mood        []string `json:"mood"`
	Composition []string `json:"composition"`
}

// ListDistinctAttributeValues 查询所有结构化属性的去重值。
// objects/colors/composition 是逗号分隔的多值字段，返回拆分后的独立值。
func ListDistinctAttributeValues() (*AttributeValues, error) {
	result := &AttributeValues{}

	// 单值字段: scene, lighting, mood
	for _, spec := range []struct {
		col string
		dst *[]string
	}{
		{"scene", &result.Scene},
		{"lighting", &result.Lighting},
		{"mood", &result.Mood},
	} {
		if err := db.Model(&model.Photo{}).
			Where(spec.col+" != ?", "").
			Distinct().
			Pluck(spec.col, spec.dst).Error; err != nil {
			return nil, fmt.Errorf("query %s failed: %w", spec.col, err)
		}
	}

	// 逗号分隔多值字段: objects, colors, composition
	for _, spec := range []struct {
		col string
		dst *[]string
	}{
		{"objects", &result.Objects},
		{"colors", &result.Colors},
		{"composition", &result.Composition},
	} {
		vals, err := _pluckDistinctSplit(spec.col)
		if err != nil {
			return nil, err
		}
		*spec.dst = vals
	}

	return result, nil
}

// _pluckDistinctSplit 查询逗号分隔字段的拆分去重值。
func _pluckDistinctSplit(col string) ([]string, error) {
	var rows []string
	if err := db.Model(&model.Photo{}).
		Where(col+" != ?", "").
		Distinct().
		Pluck(col, &rows).Error; err != nil {
		return nil, fmt.Errorf("query %s failed: %w", col, err)
	}

	seen := make(map[string]struct{})
	result := make([]string, 0)
	for _, r := range rows {
		for _, part := range strings.Split(r, ",") {
			part = strings.TrimSpace(part)
			if part == "" {
				continue
			}
			if _, ok := seen[part]; !ok {
				seen[part] = struct{}{}
				result = append(result, part)
			}
		}
	}
	return result, nil
}

// ListDistinctTags 查询所有不重复的标签
func ListDistinctTags() ([]string, error) {
	var rows []struct {
		Tags string
	}
	if err := db.Model(&model.Photo{}).
		Where("tags != ?", "").
		Distinct().
		Pluck("tags", &rows).Error; err != nil {
		return nil, fmt.Errorf("query tags failed: %w", err)
	}

	tagSet := make(map[string]struct{})
	for _, r := range rows {
		var tags []string
		if err := json.Unmarshal([]byte(r.Tags), &tags); err == nil {
			for _, t := range tags {
				if t != "" {
					tagSet[t] = struct{}{}
				}
			}
		}
	}

	result := make([]string, 0, len(tagSet))
	for t := range tagSet {
		result = append(result, t)
	}
	return result, nil
}

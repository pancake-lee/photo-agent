package data

import (
	"backend/internal/pkg/db"
	"backend/internal/pkg/db/model"
	"backend/internal/pkg/perr"
	"strings"

	"github.com/pancake-lee/pgo/pkg/papp"
)

// UpdateTags 更新照片标签字段
func (*photoDAO) UpdateTags(ctx *papp.AppCtx, photoID, tags string) error {
	if photoID == "" {
		return perr.ErrParamInvalid
	}
	q := db.GetQuery().Photo
	_, err := q.WithContext(ctx).
		Where(q.ID.Eq(photoID)).
		Update(q.Tags, tags)
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

// GetPhotosByTag 根据标签查询照片
func (*photoDAO) GetPhotosByTag(ctx *papp.AppCtx, tag string) ([]*model.Photo, error) {
	q := db.GetQuery().Photo
	photos, err := q.WithContext(ctx).
		Where(q.Tags.Like("%"+tag+"%")).
		Order(q.ShotAt.Desc(), q.ImportedAt.Desc()).
		Find()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return photos, nil
}

// BatchAddTag 批量给照片绑定标签，返回成功数
func (*photoDAO) BatchAddTag(ctx *papp.AppCtx, photoIDList []string, tag string) (int32, error) {
	if len(photoIDList) == 0 || tag == "" {
		return 0, perr.ErrParamInvalid
	}

	q := db.GetQuery().Photo
	photos, err := q.WithContext(ctx).Where(q.ID.In(photoIDList...)).Find()
	if err != nil {
		return 0, ctx.Log.LogErr(err)
	}

	tag = strings.TrimSpace(tag)
	var success int32
	for _, p := range photos {
		newTags := appendTag(p.Tags, tag)
		if newTags == p.Tags {
			success++
			continue
		}
		_, err := q.WithContext(ctx).Where(q.ID.Eq(p.ID)).Update(q.Tags, newTags)
		if err != nil {
			ctx.Log.Warnf("BatchAddTag: update photo %s failed: %v", p.ID, err)
			continue
		}
		success++
	}
	return success, nil
}

// BatchDelTag 批量从照片解绑标签，返回成功数
func (*photoDAO) BatchDelTag(ctx *papp.AppCtx, photoIDList []string, tag string) (int32, error) {
	if len(photoIDList) == 0 || tag == "" {
		return 0, perr.ErrParamInvalid
	}

	q := db.GetQuery().Photo
	photos, err := q.WithContext(ctx).Where(q.ID.In(photoIDList...)).Find()
	if err != nil {
		return 0, ctx.Log.LogErr(err)
	}

	tag = strings.TrimSpace(tag)
	var success int32
	for _, p := range photos {
		newTags := removeTag(p.Tags, tag)
		if newTags == p.Tags {
			success++
			continue
		}
		_, err := q.WithContext(ctx).Where(q.ID.Eq(p.ID)).Update(q.Tags, newTags)
		if err != nil {
			ctx.Log.Warnf("BatchDelTag: update photo %s failed: %v", p.ID, err)
			continue
		}
		success++
	}
	return success, nil
}

// appendTag 在逗号分隔的标签字符串中添加标签（去重）
func appendTag(tagsStr, tag string) string {
	if tag == "" {
		return tagsStr
	}
	tags := splitTags(tagsStr)
	for _, t := range tags {
		if t == tag {
			return tagsStr
		}
	}
	tags = append(tags, tag)
	return strings.Join(tags, ",")
}

// removeTag 从逗号分隔的标签字符串中移除标签
func removeTag(tagsStr, tag string) string {
	if tag == "" {
		return tagsStr
	}
	tags := splitTags(tagsStr)
	result := make([]string, 0, len(tags))
	for _, t := range tags {
		if t != tag {
			result = append(result, t)
		}
	}
	return strings.Join(result, ",")
}

// splitTags 将逗号分隔的标签字符串解析为标签列表
func splitTags(tagsStr string) []string {
	if tagsStr == "" {
		return nil
	}
	parts := strings.Split(tagsStr, ",")
	result := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			result = append(result, p)
		}
	}
	return result
}

// GetDistinctTagList 查询所有不重复的标签
func (*photoDAO) GetDistinctTagList(ctx *papp.AppCtx) ([]string, error) {
	q := db.GetQuery().Photo
	var rows []string
	err := q.WithContext(ctx).
		Where(q.Tags.Neq("")).
		Distinct().
		Pluck(q.Tags, &rows)
	if err != nil {
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

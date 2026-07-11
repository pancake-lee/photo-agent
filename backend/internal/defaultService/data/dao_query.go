package data

import (
	"strings"

	"backend/internal/pkg/db"

	"github.com/pancake-lee/pgo/pkg/papp"
	"gorm.io/gen/field"
)

// AttributeValuesDTO 结构化属性的去重值集合，供 Text-to-SQL prompt 动态拼入。
type AttributeValuesDTO struct {
	Objects     []string
	Colors      []string
	Scene       []string
	Lighting    []string
	Mood        []string
	Composition []string
}

// GetDistinctAttributeValues 查询所有结构化属性的去重值。
//
// 字段分类硬编码在 DAO 层：
//   - 单值字段：scene, lighting, mood，直接 SELECT DISTINCT 即可
//   - 多值字段：objects, colors, composition，逗号分隔，需拆分后去重
func GetDistinctAttributeValues(ctx *papp.AppCtx) (*AttributeValuesDTO, error) {
	p := db.GetQuery().Photo // gen 生成的类型安全字段表达式
	result := &AttributeValuesDTO{}

	// 单值字段
	err := p.WithContext(ctx).Where(p.Scene.Neq("")).Distinct().Pluck(p.Scene, &result.Scene)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	err = p.WithContext(ctx).Where(p.Lighting.Neq("")).Distinct().Pluck(p.Lighting, &result.Lighting)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	err = p.WithContext(ctx).Where(p.Mood.Neq("")).Distinct().Pluck(p.Mood, &result.Mood)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 逗号分隔多值字段
	result.Objects = pluckDistinctMulti(ctx, p.Objects)
	result.Colors = pluckDistinctMulti(ctx, p.Colors)
	result.Composition = pluckDistinctMulti(ctx, p.Composition)

	return result, nil
}

// pluckDistinctMulti 查询逗号分隔字段的拆分去重值。
// objects/colors/composition 是逗号分隔的多值字段，返回拆分后的独立值。
func pluckDistinctMulti(ctx *papp.AppCtx, col field.String) []string {
	q := db.GetQuery().Photo
	var rows []string
	err := q.WithContext(ctx).Where(col.Neq("")).Distinct().Pluck(col, &rows)
	if err != nil {
		ctx.Log.Warnf("pluckDistinctMulti: %v", err)
		return nil
	}

	seen := make(map[string]struct{})
	result := make([]string, 0)
	for _, r := range rows {
		for _, part := range strings.Split(r, ",") {
			part = strings.TrimSpace(part)
			if part == "" {
				continue
			}
			_, ok := seen[part]
			if !ok {
				seen[part] = struct{}{}
				result = append(result, part)
			}
		}
	}
	return result
}

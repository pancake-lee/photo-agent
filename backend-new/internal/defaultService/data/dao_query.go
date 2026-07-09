package data

import (
	"strings"

	"backend-new/internal/pkg/db"
	"backend-new/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"gorm.io/gorm"
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

// ListDistinctAttributeValues 查询所有结构化属性的去重值。
//
// 字段分类硬编码在 DAO 层：
//   - 单值字段：scene, lighting, mood，直接 SELECT DISTINCT 即可
//   - 多值字段：objects, colors, composition，逗号分隔，需拆分后去重
func ListDistinctAttributeValues(ctx *papp.AppCtx) (*AttributeValuesDTO, error) {
	p := db.GetQuery().Photo                                    // gen 生成的类型安全字段表达式
	gdb := pdb.GetGormDB().WithContext(ctx).Model(&model.Photo{}) // 底层 GORM 执行查询
	result := &AttributeValuesDTO{}

	// 单值字段
	for _, spec := range []struct {
		col string
		dst *[]string
	}{
		{string(p.Scene.ColumnName()), &result.Scene},
		{string(p.Lighting.ColumnName()), &result.Lighting},
		{string(p.Mood.ColumnName()), &result.Mood},
	} {
		if err := gdb.Where(spec.col+" != ?", "").
			Distinct().
			Pluck(spec.col, spec.dst).Error; err != nil {
			return nil, ctx.Log.LogErr(err)
		}
	}

	// 逗号分隔多值字段
	for _, spec := range []struct {
		col string
		dst *[]string
	}{
		{string(p.Objects.ColumnName()), &result.Objects},
		{string(p.Colors.ColumnName()), &result.Colors},
		{string(p.Composition.ColumnName()), &result.Composition},
	} {
		vals, err := pluckDistinctMulti(gdb, spec.col)
		if err != nil {
			return nil, ctx.Log.LogErr(err)
		}
		*spec.dst = vals
	}

	return result, nil
}

// pluckDistinctMulti 查询逗号分隔字段的拆分去重值。
// objects/colors/composition 是逗号分隔的多值字段，返回拆分后的独立值。
func pluckDistinctMulti(gdb *gorm.DB, col string) ([]string, error) {
	var rows []string
	if err := gdb.Where(col+" != ?", "").
		Distinct().
		Pluck(col, &rows).Error; err != nil {
		return nil, err
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

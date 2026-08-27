package data

import (
	"backend/internal/pkg/db"
	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/papp"
)

// GetPhotosWithoutDescription 返回 description 为空的照片列表，按导入时间倒序。
func (*photoDAO) GetPhotosWithoutDescription(ctx *papp.AppCtx) ([]*model.Photo, error) {
	q := db.GetQuery().Photo
	photos, err := q.WithContext(ctx).
		Where(q.Description.Eq(""), q.FileType.Neq("nef")).
		Order(q.ImportedAt.Desc()).
		Find()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return photos, nil
}

// CountPhotosWithoutDescription 返回 description 为空的照片数量。
func (*photoDAO) CountPhotosWithoutDescription(ctx *papp.AppCtx) (int64, error) {
	q := db.GetQuery().Photo
	count, err := q.WithContext(ctx).
		Where(q.Description.Eq("")).
		Count()
	if err != nil {
		return 0, ctx.Log.LogErr(err)
	}
	return count, nil
}

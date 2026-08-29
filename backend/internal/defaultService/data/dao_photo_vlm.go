package data

import (
	"fmt"
	"time"

	"backend/internal/pkg/db"
	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/papp"
	"gorm.io/gorm"
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

// GetPhotosForVlmAudit 返回批量 VLM 本地审查所需的 JPG 照片。
func (*photoDAO) GetPhotosForVlmAudit(ctx *papp.AppCtx) ([]*model.Photo, error) {
	q := db.GetQuery().Photo
	photos, err := q.WithContext(ctx).
		Where(q.FileType.Neq("nef")).
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

// UpdateVlmDescription 更新 VLM 描述、结构化属性及其处理时间。
func (*photoDAO) UpdateVlmDescription(ctx *papp.AppCtx, photoID string, updates map[string]any) error {
	q := db.GetQuery().Photo
	if _, err := q.WithContext(ctx).Where(q.ID.Eq(photoID)).Updates(updates); err != nil {
		return ctx.Log.LogErr(fmt.Errorf("update VLM description failed: %w", err))
	}
	return nil
}

// UpdatePhotoAfterOverwrite 回写覆盖上传后从新源文件提取的照片元数据。
func (*photoDAO) UpdatePhotoAfterOverwrite(ctx *papp.AppCtx, photoID string, updates map[string]any) error {
	q := db.GetQuery().Photo
	if _, err := q.WithContext(ctx).Where(q.ID.Eq(photoID)).Updates(updates); err != nil {
		return ctx.Log.LogErr(fmt.Errorf("update overwritten photo failed: %w", err))
	}
	return nil
}

// GetLatestPhotoImportTime 返回最新照片导入时间；没有照片时返回零值。
func (*photoDAO) GetLatestPhotoImportTime(ctx *papp.AppCtx) (time.Time, error) {
	q := db.GetQuery().Photo
	photo, err := q.WithContext(ctx).Order(q.ImportedAt.Desc()).First()
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return time.Time{}, nil
		}
		return time.Time{}, ctx.Log.LogErr(fmt.Errorf("get latest photo import time failed: %w", err))
	}
	return photo.ImportedAt, nil
}

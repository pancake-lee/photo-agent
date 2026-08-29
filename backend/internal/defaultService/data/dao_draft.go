package data

import (
	"backend/internal/pkg/db/model"
	"backend/internal/pkg/perr"
	"time"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
)

type DraftDO = model.Draft

type draftDAO struct{}

var DraftDAO draftDAO

func (*draftDAO) Add(ctx *papp.AppCtx, draft *DraftDO) error {
	if draft == nil || draft.ID == "" {
		return ctx.Log.LogErr(perr.ErrParamInvalid)
	}
	now := time.Now()
	draft.CreatedAt = now
	draft.UpdatedAt = now
	err := pdb.GetGormDB().WithContext(ctx).Create(draft).Error
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

func (*draftDAO) GetByID(ctx *papp.AppCtx, id string) (*DraftDO, error) {
	if id == "" {
		return nil, ctx.Log.LogErr(perr.ErrParamInvalid)
	}
	var draft DraftDO
	err := pdb.GetGormDB().WithContext(ctx).Where("id = ?", id).First(&draft).Error
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return &draft, nil
}

func (*draftDAO) GetAll(ctx *papp.AppCtx) ([]*DraftDO, error) {
	var list []*DraftDO
	err := pdb.GetGormDB().WithContext(ctx).Order("updated_at DESC").Find(&list).Error
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return list, nil
}

func (*draftDAO) Update(ctx *papp.AppCtx, draft *DraftDO) error {
	if draft == nil || draft.ID == "" {
		return ctx.Log.LogErr(perr.ErrParamInvalid)
	}
	draft.UpdatedAt = time.Now()
	err := pdb.GetGormDB().WithContext(ctx).Model(draft).
		Select("title", "content", "photo_ids", "style", "source", "input_mode", "prompt", "draft_input", "status", "updated_at").
		Updates(draft).Error
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

func (*draftDAO) DelByID(ctx *papp.AppCtx, id string) error {
	if id == "" {
		return ctx.Log.LogErr(perr.ErrParamInvalid)
	}
	err := pdb.GetGormDB().WithContext(ctx).Where("id = ?", id).Delete(&model.Draft{}).Error
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

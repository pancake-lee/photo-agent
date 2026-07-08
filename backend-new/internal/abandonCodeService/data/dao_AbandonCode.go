package data

import (
	"backend-new/internal/pkg/db"
	"backend-new/internal/pkg/db/model"
	"backend-new/internal/pkg/perr"
	"github.com/pancake-lee/pgo/pkg/papp"
)

type AbandonCodeDO = model.AbandonCode

type abandonCodeDAO struct{}

var AbandonCodeDAO abandonCodeDAO

func (*abandonCodeDAO) Add(ctx *papp.AppCtx, abandonCode *AbandonCodeDO) error {
	if abandonCode == nil {
		return ctx.Log.LogErr(perr.ErrParamInvalid)
	}
	// TODO 用反射识别是否有create/update字段，自动赋值
	q := db.GetQuery().AbandonCode
	err := q.WithContext(ctx).Create(abandonCode)
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

func (*abandonCodeDAO) GetAll(ctx *papp.AppCtx,
) (abandonCodeList []*AbandonCodeDO, err error) {
	q := db.GetQuery().AbandonCode
	abandonCodeList, err = q.WithContext(ctx).Find()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return abandonCodeList, nil
}

func (*abandonCodeDAO) GetByIndex(ctx *papp.AppCtx,
	// MARK REPLACE IDX COL START
	idx1List []int32,
	idx2List []int32,
	idx3List []int32,
	// MARK REPLACE IDX COL END
) ([]*AbandonCodeDO, error) {
	q := db.GetQuery().AbandonCode
	do := q.WithContext(ctx)
	// MARK REPLACE IDX WHERE START
	if len(idx1List) > 0 {
		do = do.Where(q.Idx1.In(idx1List...))
	}
	if len(idx2List) > 0 {
		do = do.Where(q.Idx2.In(idx2List...))
	}
	if len(idx3List) > 0 {
		do = do.Where(q.Idx3.In(idx3List...))
	}
	// MARK REPLACE IDX WHERE END
	list, err := do.Find()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return list, nil
}

// MARK REMOVE IF NO PRIMARY KEY START
func (*abandonCodeDAO) UpdateByIdx1(ctx *papp.AppCtx, do *AbandonCodeDO) error {
	if do.Idx1 == 0 {
		return ctx.Log.LogErr(perr.ErrParamInvalid)
	}
	q := db.GetQuery().AbandonCode
	_, err := q.WithContext(ctx).Where(q.Idx1.Eq(do.Idx1)).Updates(do)
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

func (*abandonCodeDAO) DelByIdx1(ctx *papp.AppCtx, idx1 int32) error {
	if idx1 == 0 {
		return ctx.Log.LogErr(perr.ErrParamInvalid)
	}
	q := db.GetQuery().AbandonCode
	_, err := q.WithContext(ctx).Where(q.Idx1.Eq(idx1)).Delete()
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

func (*abandonCodeDAO) DelByIdx1List(ctx *papp.AppCtx, idx1List []int32) error {
	if len(idx1List) == 0 {
		return nil
	}
	q := db.GetQuery().AbandonCode
	_, err := q.WithContext(ctx).
		Where(q.Idx1.In(idx1List...)).Delete()
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

func (*abandonCodeDAO) GetByIdx1(ctx *papp.AppCtx, idx1 int32,
) (abandonCode *AbandonCodeDO, err error) {
	if idx1 == 0 {
		return abandonCode, ctx.Log.LogErr(perr.ErrParamInvalid)
	}

	q := db.GetQuery().AbandonCode
	abandonCode, err = q.WithContext(ctx).
		Where(q.Idx1.Eq(idx1)).First()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return abandonCode, nil
}

func (*abandonCodeDAO) GetByIdx1List(ctx *papp.AppCtx, idx1List []int32,
) (abandonCodeMap map[int32]*AbandonCodeDO, err error) {
	if len(idx1List) == 0 {
		return nil, nil
	}

	q := db.GetQuery().AbandonCode
	l, err := q.WithContext(ctx).
		Where(q.Idx1.In(idx1List...)).Find()
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	abandonCodeMap = make(map[int32]*AbandonCodeDO)
	for _, i := range l {
		abandonCodeMap[i.Idx1] = i
	}
	return abandonCodeMap, nil
}

// MARK REMOVE IF NO PRIMARY KEY END

package service

// MARK REPLACE IMPORT START
// MARK REPLACE IMPORT END

import (
	"context"

	"backend-new/api"
	"backend-new/internal/abandonCodeService/data"
	"github.com/pancake-lee/pgo/pkg/papp"
)

func DO2DTO_AbandonCode(do *data.AbandonCodeDO) *api.AbandonCodeInfo {
	if do == nil {
		return nil
	}
	return &api.AbandonCodeInfo{
		// MARK REPLACE DO2DTO START 替换内容，所有字段DO2DTO
		Idx1: do.Idx1,
		Col1: do.Col1,
		// MARK REPLACE DO2DTO END
	}
}
func DTO2DO_AbandonCode(dto *api.AbandonCodeInfo) *data.AbandonCodeDO {
	if dto == nil {
		return nil
	}
	return &data.AbandonCodeDO{
		// MARK REPLACE DTO2DO START 替换内容，所有字段DTO2DO
		Idx1: dto.Idx1,
		Col1: dto.Col1,
		// MARK REPLACE DTO2DO END
	}
}

func (s *AbandonCodeCURDServer) AddAbandonCode(
	_ctx context.Context, req *api.AddAbandonCodeRequest,
) (resp *api.AddAbandonCodeResponse, err error) {
	ctx := papp.NewAppCtx(_ctx)

	if req.AbandonCode == nil {
		return nil, api.ErrorInvalidArgument("")
	}
	newData := DTO2DO_AbandonCode(req.AbandonCode)

	err = data.AbandonCodeDAO.Add(ctx, newData)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// MARK REMOVE IF NO PRIMARY KEY START
	ctx.Log.Debugf("AddAbandonCode: %v", newData.Idx1)
	// MARK REMOVE IF NO PRIMARY KEY END

	resp = new(api.AddAbandonCodeResponse)
	resp.AbandonCode = DO2DTO_AbandonCode(newData)
	return resp, nil
}

func (s *AbandonCodeCURDServer) GetAbandonCodeList(
	_ctx context.Context, req *api.GetAbandonCodeListRequest,
) (resp *api.GetAbandonCodeListResponse, err error) {
	ctx := papp.NewAppCtx(_ctx)

	var dataList []*data.AbandonCodeDO

	// MARK REMOVE IF NO PRIMARY KEY START 1
	if len(req.Idx1List) != 0 {
		ctx.Log.Debugf("GetAbandonCodeList: %v", req.Idx1List)

		dataList, err = data.AbandonCodeDAO.GetByIndex(ctx,
			// MARK REPLACE IDX COL START
			req.Idx1List,
			req.Idx2List,
			req.Idx3List,
			// MARK REPLACE IDX COL END
		)
		if err != nil {
			return nil, ctx.Log.LogErr(err)
		}
	} else {
		// MARK REMOVE IF NO PRIMARY KEY END 1

		dataList, err = data.AbandonCodeDAO.GetAll(ctx)
		if err != nil {
			return nil, ctx.Log.LogErr(err)
		}

		// MARK REMOVE IF NO PRIMARY KEY START 2
	}
	// MARK REMOVE IF NO PRIMARY KEY END 2

	ctx.Log.Debugf("GetAbandonCodeList resp len %v", len(dataList))

	resp = new(api.GetAbandonCodeListResponse)
	resp.AbandonCodeList = make([]*api.AbandonCodeInfo, 0, len(dataList))
	for _, data := range dataList {
		resp.AbandonCodeList = append(resp.AbandonCodeList, DO2DTO_AbandonCode(data))
	}
	return resp, nil
}

// MARK REMOVE IF NO PRIMARY KEY START

func (s *AbandonCodeCURDServer) UpdateAbandonCode(
	_ctx context.Context, req *api.UpdateAbandonCodeRequest,
) (resp *api.UpdateAbandonCodeResponse, err error) {
	ctx := papp.NewAppCtx(_ctx)

	if req.AbandonCode == nil {
		return nil, api.ErrorInvalidArgument("")
	}

	do := DTO2DO_AbandonCode(req.AbandonCode)
	err = data.AbandonCodeDAO.UpdateByIdx1(ctx, do)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	ctx.Log.Debugf("UpdateAbandonCode %v", req.AbandonCode.Idx1)

	resp = new(api.UpdateAbandonCodeResponse)
	d, err := data.AbandonCodeDAO.GetByIdx1(ctx, req.AbandonCode.Idx1)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	resp.AbandonCode = DO2DTO_AbandonCode(d)
	return resp, nil
}

func (s *AbandonCodeCURDServer) DelAbandonCodeByIdx1List(
	_ctx context.Context, req *api.DelAbandonCodeByIdx1ListRequest,
) (resp *api.Empty, err error) {
	ctx := papp.NewAppCtx(_ctx)

	if len(req.Idx1List) == 0 {
		return nil, nil
	}
	err = data.AbandonCodeDAO.DelByIdx1List(ctx, req.Idx1List)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	ctx.Log.Debugf("DelAbandonCodeByIdx1List %v", req.Idx1List)
	return nil, nil
}

// MARK REMOVE IF NO PRIMARY KEY END

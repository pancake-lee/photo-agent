package service

import (
	"context"
	"fmt"

	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"

	"github.com/pancake-lee/pgo/pkg/papp"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

// TagServer 标签服务
type TagServer struct {
	api.UnimplementedTagServiceServer
}

func (s *TagServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if grpcSrv != nil {
		api.RegisterTagServiceServer(grpcSrv, s)
	}
	if httpSrv != nil {
		api.RegisterTagServiceHTTPServer(httpSrv, s)
	}
}

// ListTags 获取所有标签列表
func (s *TagServer) ListTags(_ctx context.Context, _ *api.Empty) (*api.ListTagsResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	tags, err := data.PhotoDAO.GetDistinctTagList(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	return &api.ListTagsResponse{Tags: tags}, nil
}

// GetPhotosByTag 获取某标签下的照片
func (s *TagServer) GetPhotosByTag(_ctx context.Context, req *api.GetPhotosByTagRequest) (*api.GetPhotosByTagResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	photos, err := data.PhotoDAO.GetPhotosByTag(ctx, req.Name)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	items := make([]*api.PhotoItem, len(photos))
	for i, p := range photos {
		items[i] = photoDO2Item(p)
	}

	return &api.GetPhotosByTagResponse{
		Tag:   req.Name,
		Items: items,
		Total: int32(len(items)),
	}, nil
}

// BindTags 批量给照片绑定标签
func (s *TagServer) BindTags(_ctx context.Context, req *api.BindTagsRequest) (*api.BindTagsResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	if len(req.PhotoIds) == 0 {
		return nil, ctx.Log.LogErr(fmt.Errorf("photo_ids 不能为空"))
	}
	if req.Tag == "" {
		return nil, ctx.Log.LogErr(fmt.Errorf("tag 不能为空"))
	}

	successCount, err := data.PhotoDAO.BatchAddTag(ctx, req.PhotoIds, req.Tag)
	if err != nil {
		return nil, err
	}

	return &api.BindTagsResponse{
		SuccessCount: successCount,
		Message:      fmt.Sprintf("成功为 %d/%d 张照片绑定标签", successCount, len(req.PhotoIds)),
	}, nil
}

// UnbindTags 批量从照片解绑标签
func (s *TagServer) UnbindTags(_ctx context.Context, req *api.UnbindTagsRequest) (*api.UnbindTagsResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	if len(req.PhotoIds) == 0 {
		return nil, ctx.Log.LogErr(fmt.Errorf("photo_ids 不能为空"))
	}
	if req.Tag == "" {
		return nil, ctx.Log.LogErr(fmt.Errorf("tag 不能为空"))
	}

	successCount, err := data.PhotoDAO.BatchDelTag(ctx, req.PhotoIds, req.Tag)
	if err != nil {
		return nil, err
	}

	return &api.UnbindTagsResponse{
		SuccessCount: successCount,
		Message:      fmt.Sprintf("成功从 %d/%d 张照片解绑标签", successCount, len(req.PhotoIds)),
	}, nil
}

package service

import (
	"context"
	"sort"

	"backend-new/internal/defaultService/conf"
	"backend-new/internal/defaultService/data"
	"backend-new/internal/pkg/api"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
)

// TimelineServer 时间线服务
type TimelineServer struct {
	api.UnimplementedTimelineServiceServer
}

func (s *TimelineServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if grpcSrv != nil {
		api.RegisterTimelineServiceServer(grpcSrv, s)
	}
	if httpSrv != nil {
		api.RegisterTimelineServiceHTTPServer(httpSrv, s)
	}
}

// ListTimelines 列出所有时间线，按 timeline.json 文件中的顺序排列。
func (s *TimelineServer) ListTimelines(_ctx context.Context, _ *api.Empty) (*api.ListTimelinesResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	timelines, err := data.PhotoDAO.GetDistinctTimelineList(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	sorted := sortTimelinesByFileOrder(timelines)
	return &api.ListTimelinesResponse{Timelines: sorted}, nil
}

// GetPhotosByTimeline 查询某个时间线下的所有照片，按 shot_at 倒序。
func (s *TimelineServer) GetPhotosByTimeline(_ctx context.Context, req *api.GetPhotosByTimelineRequest) (*api.GetPhotosByTimelineResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	if req.Name == "" {
		return &api.GetPhotosByTimelineResponse{}, nil
	}

	photos, err := data.PhotoDAO.GetPhotosByTimeline(ctx, req.Name)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	items := make([]*api.PhotoItem, len(photos))
	for i, p := range photos {
		items[i] = photoDO2Item(p)
	}

	return &api.GetPhotosByTimelineResponse{
		Timeline: req.Name,
		Items:    items,
		Total:    int32(len(items)),
	}, nil
}

// sortTimelinesByFileOrder 按 timeline JSON 文件中条目出现的先后顺序排列 timelines，
// 文件中未出现的条目排在最后，相对顺序保持不变。
func sortTimelinesByFileOrder(timelines []string) []string {
	entries, _ := loadTimeline(conf.C.Storage.TimelinePath)
	if len(entries) == 0 {
		return timelines
	}

	orderMap := make(map[string]int, len(entries))
	for i, e := range entries {
		if _, exists := orderMap[e.Event]; !exists {
			orderMap[e.Event] = i
		}
	}

	sorted := make([]string, len(timelines))
	copy(sorted, timelines)
	sort.SliceStable(sorted, func(i, j int) bool {
		oi, hasI := orderMap[sorted[i]]
		oj, hasJ := orderMap[sorted[j]]
		if !hasI && !hasJ {
			return i < j
		}
		if !hasI {
			return false
		}
		if !hasJ {
			return true
		}
		return oi < oj
	})

	return sorted
}

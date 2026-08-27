package service

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"
	"backend/internal/pkg/perr"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"
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

// ListTimelines 列出所有时间线（照片库实际存在的 timeline 值），
// 按事件表日期顺序排列，散片组按时间序混入，事件表未出现的值排最后。
func (s *TimelineServer) ListTimelines(_ctx context.Context, _ *api.Empty) (*api.ListTimelinesResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	timelines, err := data.PhotoDAO.GetDistinctTimelineList(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	sorted := sortTimelinesByEventOrder(ctx, timelines)
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

// sortTimelinesByEventOrder 按事件表日期顺序排列 timelines，
// 散片名按其年月排入对应位置，事件表未出现的条目排在最后，相对顺序保持不变。
func sortTimelinesByEventOrder(ctx *papp.AppCtx, timelines []string) []string {
	entries, err := loadTimeline(ctx)
	if err != nil || len(entries) == 0 {
		return timelines
	}

	// 事件名 → 序号；散片名 → 按年月折算的排序键（比该月最后一个事件大、比下月事件小）
	orderMap := make(map[string]int, len(entries))
	for i, e := range entries {
		if _, exists := orderMap[e.Event]; !exists {
			orderMap[e.Event] = i
		}
	}
	scatteredOrder := func(name string) (int, bool) {
		if !isScatteredName(name) {
			return 0, false
		}
		// 散片排在同年月最后一个事件之后：序号 = 最后同月事件序号 + 1，
		// 同月多个散片组按名内 N 排序由 name 本身的字典序补充
		last := -1
		for i, e := range entries {
			if monthOf(e.Date) == name[:7] && i > last {
				last = i
			}
		}
		if last == -1 {
			return 0, false // 该月无事件，排最后
		}
		return last + 1, true
	}

	sorted := make([]string, len(timelines))
	copy(sorted, timelines)
	sort.SliceStable(sorted, func(i, j int) bool {
		keyOf := func(name string) (int, bool) {
			if o, ok := orderMap[name]; ok {
				return o, true
			}
			return scatteredOrder(name)
		}
		oi, hasI := keyOf(sorted[i])
		oj, hasJ := keyOf(sorted[j])
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

// --------------------------------------------------
// 时间线事件 CRUD
// --------------------------------------------------

// ListEvents 事件列表 + 散片组只读展示。
func (s *TimelineServer) ListEvents(_ctx context.Context, _ *api.Empty) (*api.ListTimelineEventsResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	events, err := data.TimelineEventDAO.GetTimelineEventsOrderByDate(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 每个 timeline 值的照片数（活动 + 散片）
	photos, err := data.PhotoDAO.GetAll(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	countMap := make(map[string]int32, len(photos))
	for _, p := range photos {
		if p.Timeline != "" {
			countMap[p.Timeline]++
		}
	}

	resp := &api.ListTimelineEventsResponse{
		Events:    make([]*api.TimelineEventDetail, 0, len(events)),
		Scattered: make([]*api.TimelineEventDetail, 0),
	}
	// 展示层倒序：DAO 按日期升序返回（供重算匹配用），此处新的排前面
	for i := len(events) - 1; i >= 0; i-- {
		e := events[i]
		resp.Events = append(resp.Events, &api.TimelineEventDetail{
			Id:         e.ID,
			Date:       e.EventDate.Local().Format("2006-01-02"),
			Event:      e.Event,
			Note:       e.Note,
			PhotoCount: countMap[e.Event],
		})
	}

	// 散片组：按 timeline 值聚合，只读
	scatterSet := make(map[string]struct{})
	for name := range countMap {
		if isScatteredName(name) {
			scatterSet[name] = struct{}{}
		}
	}
	scatterNames := make([]string, 0, len(scatterSet))
	for name := range scatterSet {
		scatterNames = append(scatterNames, name)
	}
	sort.Sort(sort.Reverse(sort.StringSlice(scatterNames))) // YYYY-MM-散片N 字典序即时间序，倒序=新的在前
	for _, name := range scatterNames {
		resp.Scattered = append(resp.Scattered, &api.TimelineEventDetail{
			Date:        name[:7],
			Event:       name,
			PhotoCount:  countMap[name],
			IsScattered: true,
		})
	}

	return resp, nil
}

// SaveEvent 保存事件（新建与更新合一，id 为空则新建）。
func (s *TimelineServer) SaveEvent(_ctx context.Context, req *api.SaveTimelineEventRequest) (*api.SaveTimelineEventResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	event := strings.TrimSpace(req.Event)
	if event == "" {
		return nil, ctx.Log.LogErr(perr.ErrParamInvalid)
	}
	date, err := time.ParseInLocation("2006-01-02", req.Date, time.Local)
	if err != nil {
		return nil, ctx.Log.LogErr(perr.ErrParamInvalid)
	}

	if req.Id == "" {
		do := &data.TimelineEventDO{
			ID:        putil.UUID(),
			EventDate: date,
			Event:     event,
			Note:      req.Note,
			CreatedAt: time.Now(),
			UpdatedAt: time.Now(),
		}
		if err := data.TimelineEventDAO.Add(ctx, do); err != nil {
			return nil, ctx.Log.LogErr(err)
		}
		return &api.SaveTimelineEventResponse{Id: do.ID}, nil
	}

	do, err := data.TimelineEventDAO.GetByID(ctx, req.Id)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	do.EventDate = date
	do.Event = event
	do.Note = req.Note
	do.UpdatedAt = time.Now()
	if err := data.TimelineEventDAO.UpdateByID(ctx, do); err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return &api.SaveTimelineEventResponse{Id: do.ID}, nil
}

// DeleteEvent 删除事件（照片 timeline 不动，等待下次重算清理过期值）。
func (s *TimelineServer) DeleteEvent(_ctx context.Context, req *api.DeleteTimelineEventRequest) (*api.Empty, error) {
	ctx := papp.NewAppCtx(_ctx)

	if req.Id == "" {
		return nil, ctx.Log.LogErr(perr.ErrParamInvalid)
	}
	if err := data.TimelineEventDAO.DelByID(ctx, req.Id); err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return &api.Empty{}, nil
}

// --------------------------------------------------
// 全量重算
// --------------------------------------------------

// timelineRecomputeManager 重算运行时状态（模式与 burstGroupManager 一致）
type timelineRecomputeManager struct {
	mu             sync.Mutex
	running        bool
	processed      int32
	total          int32
	eventCount     int32
	scatteredCount int32
}

func (m *timelineRecomputeManager) snapshot() *api.GetRecomputeTimelinesStatusResponse {
	m.mu.Lock()
	defer m.mu.Unlock()
	return &api.GetRecomputeTimelinesStatusResponse{
		Running:        m.running,
		Processed:      m.processed,
		Total:          m.total,
		EventCount:     m.eventCount,
		ScatteredCount: m.scatteredCount,
	}
}

func (m *timelineRecomputeManager) isRunning() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.running
}

// start 返回 false 表示已在运行中。
func (m *timelineRecomputeManager) start(total int32) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.running {
		return false
	}
	m.running = true
	m.processed = 0
	m.total = total
	m.eventCount = 0
	m.scatteredCount = 0
	return true
}

func (m *timelineRecomputeManager) stop(eventCount, scatteredCount int32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.running = false
	m.eventCount = eventCount
	m.scatteredCount = scatteredCount
}

func (m *timelineRecomputeManager) setProcessed(n int32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.processed = n
}

// 全局时间线重算管理器
var timelineRecompute = &timelineRecomputeManager{}

// RecomputeTimelines 触发全量重算照片 timeline（异步后台执行）。
func (s *TimelineServer) RecomputeTimelines(
	_ctx context.Context, _ *api.Empty,
) (*api.RecomputeTimelinesResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	if timelineRecompute.isRunning() {
		return &api.RecomputeTimelinesResponse{Status: "already_running"}, nil
	}

	photos, err := data.PhotoDAO.GetAllPhotosOrderByShotAt(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	entries, err := loadTimeline(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	if !timelineRecompute.start(int32(len(photos))) {
		return &api.RecomputeTimelinesResponse{Status: "already_running"}, nil
	}

	go runTimelineRecompute(photos, entries)
	return &api.RecomputeTimelinesResponse{Status: "running"}, nil
}

// GetRecomputeTimelinesStatus 轮询重算进度。
func (s *TimelineServer) GetRecomputeTimelinesStatus(
	_ctx context.Context, _ *api.Empty,
) (*api.GetRecomputeTimelinesStatusResponse, error) {
	return timelineRecompute.snapshot(), nil
}

// runTimelineRecompute 后台执行全量重算。
//
// 重算语义（保留人工值）：
//   - timeline_manual=1 的照片不动
//   - 其余按事件表匹配，匹配上给事件名
//   - 匹配不上的给散片名（事件间空隙按月切段）
//   - 写回统一清 manual 标记（事件与散片都是自动产物）
func runTimelineRecompute(photos []*data.PhotoDO, entries []TimelineEntry) {
	eventCount, scatteredCount, err := recomputeTimelines(photos, entries, conf.C.Storage.TimelineWindowDays)
	if err != nil {
		plogger.Errorf("timeline recompute failed: %v", err)
	}
	timelineRecompute.stop(eventCount, scatteredCount)
	plogger.Infof("timeline recompute done: event %d / scattered %d photos from %d photos",
		eventCount, scatteredCount, len(photos))
}

// validTimelineShotAtFloor shot_at 有效下界（与连拍分组同口径），早于该时间视为零值记录
var validTimelineShotAtFloor = time.Date(2000, 1, 1, 0, 0, 0, 0, time.UTC)

// recomputeTimelines 重算主体（与 DB 交互，进度经 manager 上报）。
func recomputeTimelines(photos []*data.PhotoDO, entries []TimelineEntry, windowDays int) (int32, int32, error) {
	ctx := newAppCtxForBackground()

	// 1. 分类：手动的不动；事件匹配的按事件名分桶；其余进散片候选
	var scatteredCandidates []scatteredPhoto
	eventBuckets := make(map[string][]string) // 事件名 → 照片 id 列表
	processed := int32(0)

	for _, p := range photos {
		// shot_at 零值（0001 年）记录不参与重算
		if p.ShotAt.Before(validTimelineShotAtFloor) {
			processed++
			continue
		}
		if p.TimelineManual == 1 {
			processed++
			continue
		}
		if event := findEventByTime(p.ShotAt, entries, windowDays); event != "" {
			eventBuckets[event] = append(eventBuckets[event], p.ID)
		} else {
			scatteredCandidates = append(scatteredCandidates, scatteredPhoto{
				PhotoID: p.ID,
				ShotAt:  p.ShotAt,
			})
		}
		processed++
		timelineRecompute.setProcessed(processed)
	}

	// 2. 散片分组
	scatteredGroups := splitScatteredPhotos(scatteredCandidates, entries, windowDays)

	// 3. 写回：事件桶
	var eventCount, scatteredCount int32
	for event, idList := range eventBuckets {
		if err := data.PhotoDAO.UpdatePhotosTimelineBatch(ctx, idList, event); err != nil {
			return eventCount, scatteredCount, fmt.Errorf("update event timeline %q failed: %w", event, err)
		}
		eventCount += int32(len(idList))
	}

	// 4. 写回：散片组
	for _, g := range scatteredGroups {
		if err := data.PhotoDAO.UpdatePhotosTimelineBatch(ctx, g.IDList, g.Name); err != nil {
			return eventCount, scatteredCount, fmt.Errorf("update scattered timeline %q failed: %w", g.Name, err)
		}
		scatteredCount += int32(len(g.IDList))
	}

	return eventCount, scatteredCount, nil
}

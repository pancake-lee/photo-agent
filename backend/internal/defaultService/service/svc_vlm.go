package service

import (
	"context"
	"fmt"
	"sync"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"
	"backend/internal/pkg/db"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

// TODO 队列运行模式，加上队列状态的管理等，可以封装到pgo的runner中
// vlmQueueManager 管理 VLM 批量处理队列的运行时状态。
type vlmQueueManager struct {
	mu          sync.Mutex
	running     bool
	taskID      string
	total       int32
	completed   int32
	failed      int32
	currentFile string
	cancel      context.CancelFunc
}

// snapshot 返回当前队列状态的线程安全快照。
func (m *vlmQueueManager) snapshot() *api.VlmQueueStatus {
	m.mu.Lock()
	defer m.mu.Unlock()
	return &api.VlmQueueStatus{
		Running:     m.running,
		Total:       m.total,
		Completed:   m.completed,
		Failed:      m.failed,
		CurrentFile: m.currentFile,
	}
}

// isRunning 检查队列是否正在运行。
func (m *vlmQueueManager) isRunning() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.running
}

// start 将队列标记为运行状态，设置 taskID 和取消函数。
// 返回 false 表示已在运行中。
func (m *vlmQueueManager) start(taskID string, cancel context.CancelFunc) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.running {
		return false
	}
	m.running = true
	m.taskID = taskID
	m.total = 0
	m.completed = 0
	m.failed = 0
	m.currentFile = ""
	m.cancel = cancel
	return true
}

// stop 停止队列并返回是否在运行中。
func (m *vlmQueueManager) stop() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.running {
		return false
	}
	m.running = false
	if m.cancel != nil {
		m.cancel()
		m.cancel = nil
	}
	return true
}

// incrCompleted 增加已完成计数并更新当前处理文件名。
func (m *vlmQueueManager) incrCompleted(currentFile string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.completed++
	m.currentFile = currentFile
}

// incrFailed 增加失败计数。
func (m *vlmQueueManager) incrFailed(currentFile string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.failed++
	m.currentFile = currentFile
}

// setTotal 设置待处理总数。
func (m *vlmQueueManager) setTotal(n int32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.total = n
}

// 全局 VLM 队列管理器实例
var vlmQueue = &vlmQueueManager{}

// --------------------------------------------------
// VlmServer VLM 队列服务
type VlmServer struct {
	api.UnimplementedVlmServiceServer
}

func (s *VlmServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if grpcSrv != nil {
		api.RegisterVlmServiceServer(grpcSrv, s)
	}
	if httpSrv != nil {
		api.RegisterVlmServiceHTTPServer(httpSrv, s)
	}
}

// --------------------------------------------------
// StartVlmQueue 启动 VLM 队列处理。
// force 为 true 时，若已在运行则先停止再重新启动。
func (s *VlmServer) StartVlmQueue(_ctx context.Context, req *api.StartVlmQueueRequest) (*api.StartVlmQueueResponse, error) {
	if vlmQueue.isRunning() {
		if !req.Force {
			snap := vlmQueue.snapshot()
			return &api.StartVlmQueueResponse{
				TaskId:  vlmQueue.taskID,
				Total:   snap.Total,
				Message: fmt.Sprintf("queue already running (completed %d/%d), use force=true to restart", snap.Completed, snap.Total),
			}, nil
		}
		vlmQueue.stop()
	}

	bgCtx := context.Background()
	ctx, cancel := context.WithCancel(bgCtx)
	taskID := putil.UUID()

	if !vlmQueue.start(taskID, cancel) {
		cancel()
		return &api.StartVlmQueueResponse{
			Message: "failed to start queue",
		}, nil
	}

	// 在后台 goroutine 中执行队列处理
	go runVlmQueue(ctx, taskID)

	snap := vlmQueue.snapshot()
	return &api.StartVlmQueueResponse{
		TaskId:  taskID,
		Total:   snap.Total,
		Message: "queue started",
	}, nil
}

// StopVlmQueue 停止 VLM 队列处理。
func (s *VlmServer) StopVlmQueue(_ctx context.Context, _ *api.Empty) (*api.StopVlmQueueResponse, error) {
	stopped := vlmQueue.stop()
	return &api.StopVlmQueueResponse{Stopped: stopped}, nil
}

// GetVlmQueueStatus 获取 VLM 队列当前状态。
func (s *VlmServer) GetVlmQueueStatus(_ctx context.Context, _ *api.Empty) (*api.GetVlmQueueStatusResponse, error) {
	return &api.GetVlmQueueStatusResponse{
		Status: vlmQueue.snapshot(),
	}, nil
}

// DescribePhoto 对单张照片触发 VLM 描述（从预生成文件中同步）。
func (s *VlmServer) DescribePhoto(_ctx context.Context, req *api.DescribePhotoRequest) (*api.DescribePhotoResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	photo, err := data.PhotoDAO.GetByID(ctx, req.Id)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	entry, found := getDescriptionEntry(photo.FilePath, conf.C.Storage.DescriptionsPath)
	if !found || entry.Description == "" {
		return &api.DescribePhotoResponse{Queued: false}, nil
	}

	if err := applyDescriptionToPhoto(ctx, photo.ID, &entry); err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	return &api.DescribePhotoResponse{Queued: true}, nil
}

// ----------------------------------------------------------------
// 队列处理逻辑
// ----------------------------------------------------------------

// runVlmQueue 在后台 goroutine 中执行 VLM 队列处理。
func runVlmQueue(ctx context.Context, taskID string) {
	defer func() {
		vlmQueue.stop()
		plogger.Infof("VLM queue %s finished", taskID)
	}()

	// 加载预生成描述
	descMap, err := loadDescriptions(conf.C.Storage.DescriptionsPath)
	if err != nil {
		plogger.Warnf("VLM queue %s: failed to load descriptions: %v", taskID, err)
		return
	}
	if descMap == nil {
		plogger.Infof("VLM queue %s: no descriptions file found, nothing to sync", taskID)
		return
	}

	// 获取无描述的照片列表
	appCtx := papp.NewAppCtx(ctx)
	photos, err := data.PhotoDAO.GetPhotosWithoutDescription(appCtx)
	if err != nil {
		plogger.Warnf("VLM queue %s: failed to query photos: %v", taskID, err)
		return
	}

	vlmQueue.setTotal(int32(len(photos)))
	plogger.Infof("VLM queue %s: starting with %d photos to process", taskID, len(photos))

	for _, p := range photos {
		select {
		case <-ctx.Done():
			plogger.Infof("VLM queue %s: cancelled, processed %d/%d", taskID, vlmQueue.snapshot().Completed, len(photos))
			return
		default:
		}

		entry := findDescInMap(descMap, p.FilePath)
		if entry.Description == "" {
			vlmQueue.incrFailed(p.Filename)
			plogger.Infof("VLM queue %s: no description found for %s", taskID, p.Filename)
			continue
		}

		appCtx := papp.NewAppCtx(ctx)
		if err := applyDescriptionToPhoto(appCtx, p.ID, &entry); err != nil {
			vlmQueue.incrFailed(p.Filename)
			plogger.Warnf("VLM queue %s: failed to update %s: %v", taskID, p.Filename, err)
			continue
		}

		vlmQueue.incrCompleted(p.Filename)
		plogger.Infof("VLM queue %s: [%d/%d] processed %s", taskID, vlmQueue.snapshot().Completed, len(photos), p.Filename)

		// 小延迟避免过快的 DB 写入
		select {
		case <-ctx.Done():
			return
		case <-time.After(50 * time.Millisecond):
		}
	}
}

// applyDescriptionToPhoto 将描述记录写入 photo 数据库行。
func applyDescriptionToPhoto(ctx *papp.AppCtx, photoID string, entry *descriptionEntry) error {
	updates := map[string]any{
		"description": entry.Description,
	}
	if entry.Description != "" {
		objects, colors, scene, lighting, mood, composition := parseVlmAttrs(entry.Description)
		updates["objects"] = objects
		updates["colors"] = colors
		updates["scene"] = scene
		updates["lighting"] = lighting
		updates["mood"] = mood
		updates["composition"] = composition
	}

	q := db.GetQuery().Photo
	_, err := q.WithContext(ctx).Where(q.ID.Eq(photoID)).Updates(updates)
	if err != nil {
		return ctx.Log.LogErr(err)
	}
	return nil
}

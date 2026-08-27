package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
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

// vlmQueueManager 管理 VLM 批量处理队列的运行时状态。
type vlmQueueManager struct {
	mu           sync.Mutex
	running      bool
	taskID       string
	total        int32
	completed    int32
	failed       int32
	currentFile  string
	batchPending map[string]struct{}
	stopCh       chan struct{} // 关闭时通知 goroutine 停止（优雅中止）
	done         chan struct{} // goroutine 退出时关闭
}

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

func (m *vlmQueueManager) isRunning() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.running
}

func (m *vlmQueueManager) start(taskID string) bool {
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
	m.stopCh = make(chan struct{})
	m.done = make(chan struct{})
	return true
}

// stop 发送优雅中止信号。当前正在执行的照片会完成处理，但不再处理新照片。
func (m *vlmQueueManager) stop() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.running {
		return false
	}
	select {
	case <-m.stopCh:
		// 已经发过停止信号
	default:
		close(m.stopCh)
	}
	return true
}

// waitExit 等待当前 goroutine 退出，最多等 timeout。返回 true 表示已退出。
func (m *vlmQueueManager) waitExit(timeout time.Duration) bool {
	m.mu.Lock()
	done := m.done
	m.mu.Unlock()
	if done == nil {
		return true
	}
	select {
	case <-done:
		return true
	case <-time.After(timeout):
		return false
	}
}

func (m *vlmQueueManager) incrCompleted(currentFile string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.completed++
	m.currentFile = currentFile
}

func (m *vlmQueueManager) incrFailed(currentFile string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.failed++
	m.currentFile = currentFile
}

func (m *vlmQueueManager) setTotal(n int32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.total = n
}

func (m *vlmQueueManager) setBatchPending(ids []string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.batchPending = make(map[string]struct{}, len(ids))
	for _, id := range ids {
		m.batchPending[id] = struct{}{}
	}
}

func (m *vlmQueueManager) hasBatchPending(id string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	_, ok := m.batchPending[id]
	return ok
}

func (m *vlmQueueManager) removeBatchPending(id string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.batchPending, id)
}

func (m *vlmQueueManager) clearBatchPending() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.batchPending = nil
}

var vlmQueue = &vlmQueueManager{}

// --------------------------------------------------
// describeTracker 跟踪正在执行单张 VLM 描述的照片 ID（纯内存，不持久化）。
type describeTracker struct {
	mu    sync.RWMutex
	items map[string]struct{}
}

var describeProgress = &describeTracker{items: make(map[string]struct{})}

func (t *describeTracker) add(id string) {
	t.mu.Lock()
	t.items[id] = struct{}{}
	t.mu.Unlock()
}

func (t *describeTracker) remove(id string) {
	t.mu.Lock()
	delete(t.items, id)
	t.mu.Unlock()
}

func (t *describeTracker) has(id string) bool {
	t.mu.RLock()
	defer t.mu.RUnlock()
	_, ok := t.items[id]
	return ok
}

func (t *describeTracker) list() []string {
	t.mu.RLock()
	defer t.mu.RUnlock()
	ids := make([]string, 0, len(t.items))
	for id := range t.items {
		ids = append(ids, id)
	}
	return ids
}

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
		// 优雅中止当前队列，等待 goroutine 退出
		vlmQueue.stop()
		vlmQueue.waitExit(30 * time.Second)
	}

	// 先查询照片，再启动队列，避免空启动
	appCtx := papp.NewAppCtx(context.Background())
	photos, err := data.PhotoDAO.GetPhotosWithoutDescription(appCtx)
	if err != nil {
		return nil, fmt.Errorf("query photos without description: %w", err)
	}

	// 过滤掉正在被单张处理的照片，避免冲突
	filtered := make([]*data.PhotoDO, 0, len(photos))
	for _, p := range photos {
		if !describeProgress.has(p.ID) {
			filtered = append(filtered, p)
		}
	}

	if len(filtered) == 0 {
		return &api.StartVlmQueueResponse{
			Total:   0,
			Message: "all photos already have descriptions",
		}, nil
	}

	taskID := putil.UUID()
	if !vlmQueue.start(taskID) {
		return &api.StartVlmQueueResponse{
			Message: "failed to start queue",
		}, nil
	}
	vlmQueue.setTotal(int32(len(filtered)))

	// 记录批量待处理 ID，阻止单张请求冲突
	ids := make([]string, len(filtered))
	for i, p := range filtered {
		ids[i] = p.ID
	}
	vlmQueue.setBatchPending(ids)

	go runVlmQueue(taskID, filtered)

	return &api.StartVlmQueueResponse{
		TaskId:  taskID,
		Total:   int32(len(filtered)),
		Message: "queue started",
	}, nil
}

func (s *VlmServer) StopVlmQueue(_ctx context.Context, _ *api.Empty) (*api.StopVlmQueueResponse, error) {
	stopped := vlmQueue.stop()
	return &api.StopVlmQueueResponse{Stopped: stopped}, nil
}

func (s *VlmServer) GetVlmQueueStatus(_ctx context.Context, _ *api.Empty) (*api.GetVlmQueueStatusResponse, error) {
	return &api.GetVlmQueueStatusResponse{
		Status: vlmQueue.snapshot(),
	}, nil
}

// DescribePhoto 对单张照片异步调用 VLM 生成描述。
// 防重入：如果该照片正在处理中，直接返回；否则启动后台 goroutine 处理。
func (s *VlmServer) DescribePhoto(_ctx context.Context, req *api.DescribePhotoRequest) (*api.DescribePhotoResponse, error) {
	if describeProgress.has(req.Id) {
		return &api.DescribePhotoResponse{Queued: true}, nil
	}
	if vlmQueue.hasBatchPending(req.Id) {
		return &api.DescribePhotoResponse{Queued: false}, nil
	}

	ctx := papp.NewAppCtx(_ctx)
	photo, err := data.PhotoDAO.GetByID(ctx, req.Id)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	describeProgress.add(req.Id)
	go func() {
		defer describeProgress.remove(req.Id)

		bgCtx := papp.NewAppCtx(context.Background())
		_ = updateAIState(bgCtx, photo.ID, aiStatusWorking, "", aiStatusWorking, "", aiStatusPending)
		imagePath := photoFilePath(photo)
		description, modelUsed, err := describeImage(imagePath)
		if err != nil {
			_ = updateAIState(bgCtx, photo.ID, aiStatusFailed, err.Error(), aiStatusFailed, err.Error(), aiStatusStale)
			recordAIHistory(photo.ID, "", "vlm", aiStatusFailed, err.Error())
			plogger.Errorf("VLM describe %s failed: %v", photo.Filename, err)
			return
		}

		entry := &vlmDescriptionEntry{
			Description: description,
			Model:       modelUsed,
			Time:        nowTimeString(),
		}
		if err := applyDescriptionToPhoto(bgCtx, photo.ID, entry); err != nil {
			_ = updateAIState(bgCtx, photo.ID, aiStatusFailed, err.Error(), aiStatusFailed, err.Error(), aiStatusStale)
			plogger.Errorf("VLM save %s failed: %v", photo.Filename, err)
		}
	}()

	return &api.DescribePhotoResponse{Queued: true}, nil
}

// GetDescribeProgress 返回当前正在执行 VLM 描述的照片 ID 列表。
func (s *VlmServer) GetDescribeProgress(_ctx context.Context, _ *api.Empty) (*api.GetDescribeProgressResponse, error) {
	return &api.GetDescribeProgressResponse{ProcessingIds: describeProgress.list()}, nil
}

// ----------------------------------------------------------------
// 队列处理逻辑
// ----------------------------------------------------------------

func runVlmQueue(taskID string, photos []*data.PhotoDO) {
	const concurrency = 4

	defer func() {
		vlmQueue.mu.Lock()
		if vlmQueue.taskID == taskID {
			vlmQueue.running = false
			vlmQueue.batchPending = nil
		}
		done := vlmQueue.done
		vlmQueue.mu.Unlock()
		if done != nil {
			close(done)
		}
		plogger.Infof("VLM queue %s finished, processed %d/%d", taskID, vlmQueue.snapshot().Completed, len(photos))
	}()

	plogger.Infof("VLM queue %s: starting with %d photos, concurrency=%d", taskID, len(photos), concurrency)

	workCh := make(chan *data.PhotoDO, len(photos))

	var wg sync.WaitGroup
	for i := 0; i < concurrency; i++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			for {
				// 每张照片处理前检查中止信号
				vlmQueue.mu.Lock()
				stopCh := vlmQueue.stopCh
				vlmQueue.mu.Unlock()
				select {
				case <-stopCh:
					return
				default:
				}

				p, ok := <-workCh
				if !ok {
					return
				}

				if describeProgress.has(p.ID) {
					vlmQueue.removeBatchPending(p.ID)
					plogger.Infof("VLM queue %s: worker-%d skipping %s (single processing)", taskID, workerID, p.Filename)
					continue
				}

				imagePath := photoFilePath(p)
				appCtx := papp.NewAppCtx(context.Background())
				_ = updateAIState(appCtx, p.ID, aiStatusWorking, "", aiStatusWorking, "", aiStatusPending)
				description, modelUsed, err := describeImage(imagePath)
				if err != nil {
					_ = updateAIState(appCtx, p.ID, aiStatusFailed, err.Error(), aiStatusFailed, err.Error(), aiStatusStale)
					recordAIHistory(p.ID, taskID, "vlm", aiStatusFailed, err.Error())
					vlmQueue.removeBatchPending(p.ID)
					vlmQueue.incrFailed(p.Filename)
					plogger.Warnf("VLM queue %s: worker-%d VLM failed for %s: %v", taskID, workerID, p.Filename, err)
					if errors.Is(err, errQuotaExceeded) {
						plogger.Errorf("VLM queue %s: quota exceeded, stopping all workers", taskID)
						vlmQueue.stop()
					}
					continue
				}

				entry := &vlmDescriptionEntry{
					Description: description,
					Model:       modelUsed,
					Time:        nowTimeString(),
				}

				if err := applyDescriptionToPhoto(appCtx, p.ID, entry); err != nil {
					_ = updateAIState(appCtx, p.ID, aiStatusFailed, err.Error(), aiStatusFailed, err.Error(), aiStatusStale)
					vlmQueue.removeBatchPending(p.ID)
					vlmQueue.incrFailed(p.Filename)
					plogger.Warnf("VLM queue %s: worker-%d failed to update %s: %v", taskID, workerID, p.Filename, err)
					continue
				}

				vlmQueue.removeBatchPending(p.ID)
				vlmQueue.incrCompleted(p.Filename)
				plogger.Infof("VLM queue %s: worker-%d [%d/%d] processed %s", taskID, workerID, vlmQueue.snapshot().Completed, len(photos), p.Filename)
			}
		}(i)
	}

	// 向 work channel 投喂照片，同时监听中止信号
	vlmQueue.mu.Lock()
	stopCh := vlmQueue.stopCh
	vlmQueue.mu.Unlock()
	for _, p := range photos {
		select {
		case <-stopCh:
			goto drain
		case workCh <- p:
		}
	}

drain:
	close(workCh)
	wg.Wait()
}

// photoFilePath 返回照片用于 VLM 处理的文件路径（PhotoSrc 下的源文件）。
func photoFilePath(photo *data.PhotoDO) string {
	return filepath.Join(conf.C.Storage.PhotoSrc, photo.FilePath)
}

// vlmDescriptionEntry VLM 生成的描述结果。
type vlmDescriptionEntry struct {
	Description string
	Model       string
	Time        string
}

// applyDescriptionToPhoto 将描述记录写入 photo 数据库行。
func applyDescriptionToPhoto(ctx *papp.AppCtx, photoID string, entry *vlmDescriptionEntry) error {
	if err := validateVlmDescription(entry.Description); err != nil {
		q := db.GetQuery().Photo
		if _, saveErr := q.WithContext(ctx).Where(q.ID.Eq(photoID)).Updates(map[string]any{
			"description_raw":   entry.Description,
			"description_model": entry.Model,
			"description_time":  entry.Time,
		}); saveErr != nil {
			return saveErr
		}
		if updateErr := updateAIState(ctx, photoID, aiStatusReview, err.Error(), aiStatusReview, err.Error(), aiStatusStale); updateErr != nil {
			return updateErr
		}
		recordAIHistory(photoID, "", "vlm", aiStatusReview, err.Error())
		return nil
	}

	updates := map[string]any{
		"description":                entry.Description,
		"description_raw":            entry.Description,
		"description_model":          entry.Model,
		"description_time":           entry.Time,
		"ai_health_status":           aiStatusPending,
		"ai_health_reason":           "等待 Embedding",
		"vlm_status":                 aiStatusHealthy,
		"vlm_reason":                 "",
		"embedding_status":           aiStatusPending,
		"embedding_description_time": entry.Time,
	}
	if entry.Description != "" {
		objects, colors, scene, lighting, mood, composition := parseVlmAttrs(photoID, entry.Description)
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
	recordAIHistory(photoID, "", "vlm", aiStatusHealthy, "")
	return nil
}

// ----------------------------------------------------------------
// VLM JSON 解析（从 descriptions.json 时代保留，用于解析 VLM 输出中的结构化属性）
// ----------------------------------------------------------------

type vlmJSON struct {
	Subject struct {
		MainObjects []string `json:"main_objects"`
	} `json:"subject"`
	Scene struct {
		Environment string `json:"environment"`
		Setting     string `json:"setting"`
		TimeOfDay   string `json:"time_of_day"`
	} `json:"scene"`
	Lighting struct {
		Source string `json:"source"`
	} `json:"lighting"`
	ColorPalette struct {
		DominantColors []string `json:"dominant_colors"`
	} `json:"color_palette"`
	Mood        string `json:"mood"`
	Composition struct {
		Focus    string `json:"focus"`
		Depth    string `json:"depth"`
		Symmetry string `json:"symmetry"`
	} `json:"composition"`
}

func parseVlmAttrs(photoIdentifier, description string) (objects, colors, scene, lighting, mood, composition string) {
	if description == "" {
		return
	}

	jsonStr := extractJSONBlock(description)
	if jsonStr == "" {
		plogger.Warnf("parseVlmAttrs: no JSON block in description, photo=%s", photoIdentifier)
		return
	}

	var v vlmJSON
	if err := json.Unmarshal([]byte(jsonStr), &v); err != nil {
		plogger.Warnf("parseVlmAttrs: JSON unmarshal failed, photo=%s, err=%v", photoIdentifier, err)
		return
	}

	objects = strings.Join(v.Subject.MainObjects, "、")
	colors = strings.Join(v.ColorPalette.DominantColors, "、")

	var sceneParts []string
	if v.Scene.Environment != "" {
		sceneParts = append(sceneParts, v.Scene.Environment)
	}
	if v.Scene.Setting != "" {
		sceneParts = append(sceneParts, v.Scene.Setting)
	}
	scene = strings.Join(sceneParts, "，")

	var lightingParts []string
	if v.Lighting.Source != "" {
		lightingParts = append(lightingParts, v.Lighting.Source)
	}
	if v.Scene.TimeOfDay != "" && v.Scene.TimeOfDay != "不确定" {
		lightingParts = append(lightingParts, v.Scene.TimeOfDay)
	}
	lighting = strings.Join(lightingParts, "，")

	mood = v.Mood

	var compParts []string
	if v.Composition.Focus != "" {
		compParts = append(compParts, v.Composition.Focus)
	}
	if v.Composition.Depth != "" {
		compParts = append(compParts, v.Composition.Depth)
	}
	if v.Composition.Symmetry != "" {
		compParts = append(compParts, v.Composition.Symmetry)
	}
	composition = strings.Join(compParts, "，")

	return
}

func extractJSONBlock(text string) string {
	start := strings.Index(text, "```json")
	if start == -1 {
		start = strings.Index(text, "```")
	}
	if start == -1 {
		return text
	}

	lineEnd := strings.Index(text[start:], "\n")
	if lineEnd == -1 {
		return ""
	}
	contentStart := start + lineEnd + 1

	end := strings.Index(text[contentStart:], "```")
	if end == -1 {
		return strings.TrimSpace(text[contentStart:])
	}

	return strings.TrimSpace(text[contentStart : contentStart+end])
}

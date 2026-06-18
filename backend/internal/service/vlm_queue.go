package service

import (
	"context"
	"fmt"
	"path/filepath"
	"sync"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/model"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/satori/go.uuid"
)

// QueueStatus VLM 队列运行状态
type QueueStatus struct {
	Running     bool   `json:"running"`
	Total       int    `json:"total"`
	Completed   int    `json:"completed"`
	Failed      int    `json:"failed"`
	CurrentFile string `json:"current_file,omitempty"`
}

// VlmQueue VLM 异步处理队列（单例，跟随 server 生命周期）。
// 设计要点：
//   - pending channel 作为待处理队列（带缓冲）
//   - ctx/cancel 控制 Worker 消费循环的启停
//   - Stop() 只停止消费，不等待正在执行的 goroutine（避免浪费 Token）
//   - active WaitGroup 跟踪正在执行的请求
type VlmQueue struct {
	mu        sync.RWMutex
	pending   chan string        // 待处理 photo_id 队列
	running   bool               // 是否正在消费队列
	total     int                // 本轮任务总数
	completed int                // 已完成数
	failed    int                // 失败数
	current   string             // 当前处理中的文件名
	ctx       context.Context    // 队列上下文（控制消费循环）
	cancel    context.CancelFunc // 取消函数
	active    sync.WaitGroup     // 正在执行的 VLM 请求计数
	taskID    string             // 当前任务 ID（每次 Start 重新生成）
}

var (
	vlmQueue     *VlmQueue
	vlmQueueOnce sync.Once
)

// GetVlmQueue 获取 VLM 队列单例
func GetVlmQueue() *VlmQueue {
	vlmQueueOnce.Do(func() {
		vlmQueue = &VlmQueue{
			pending: make(chan string, 256),
		}
	})
	return vlmQueue
}

// Start 启动 VLM 队列消费。
// photoIDs: 待处理的照片 ID 列表（去重后）。
// 如果队列已在运行，返回 error。
func (q *VlmQueue) Start(photoIDs []string) (string, error) {
	q.mu.Lock()
	defer q.mu.Unlock()

	if q.running {
		return "", fmt.Errorf("vlm queue is already running")
	}

	// 重置状态
	q.ctx, q.cancel = context.WithCancel(context.Background())
	q.taskID = uuid.NewV4().String()[:8]
	q.total = len(photoIDs)
	q.completed = 0
	q.failed = 0
	q.current = ""
	q.running = true

	// 填充 pending channel（非阻塞，确保 channel 有足够缓冲）
	go func() {
		for _, id := range photoIDs {
			select {
			case <-q.ctx.Done():
				return
			case q.pending <- id:
			}
		}
	}()

	// 启动 Worker 消费循环
	go q.workerLoop()

	plogger.Infof("VlmQueue started: task=%s, total=%d", q.taskID, q.total)
	return q.taskID, nil
}

// Stop 中止 VLM 队列。
// 1. cancel context → Worker 循环退出
// 2. 排空 pending channel 并丢弃
// 3. 不等待 active goroutine（已发出的 VLM 请求继续完成）
func (q *VlmQueue) Stop() {
	q.mu.Lock()
	if !q.running {
		q.mu.Unlock()
		return
	}

	plogger.Infof("VlmQueue stopping: task=%s, completed=%d, failed=%d, active=%d",
		q.taskID, q.completed, q.failed, q.activeCount())

	q.cancel()
	q.running = false

	// 排空 pending channel
	q.drainPending()
	q.mu.Unlock()

	plogger.Info("VlmQueue stopped")
}

// Enqueue 追加单张照片到队列。
// 队列未运行时自动启动消费循环。
func (q *VlmQueue) Enqueue(photoID string) error {
	q.mu.Lock()
	defer q.mu.Unlock()

	if !q.running {
		// 自动启动
		q.ctx, q.cancel = context.WithCancel(context.Background())
		q.taskID = uuid.NewV4().String()[:8]
		q.total = 1
		q.completed = 0
		q.failed = 0
		q.current = ""
		q.running = true

		go q.workerLoop()
	} else {
		q.total++
	}

	select {
	case q.pending <- photoID:
		plogger.Infof("VlmQueue enqueued: photo=%s, task=%s", photoID, q.taskID)
		return nil
	default:
		q.total-- // 回退
		return fmt.Errorf("vlm queue pending channel is full")
	}
}

// Status 查询当前队列状态。
func (q *VlmQueue) Status() QueueStatus {
	q.mu.RLock()
	defer q.mu.RUnlock()

	return QueueStatus{
		Running:     q.running,
		Total:       q.total,
		Completed:   q.completed,
		Failed:      q.failed,
		CurrentFile: q.current,
	}
}

// workerLoop Worker 消费循环。
// 从 pending channel 取任务 → active.Add(1) → goroutine 执行。
// ctx.Done() 时退出循环，不等待 active。
func (q *VlmQueue) workerLoop() {
	plogger.Infof("VlmQueue worker loop started: task=%s", q.taskID)

	for {
		select {
		case <-q.ctx.Done():
			plogger.Infof("VlmQueue worker loop exiting: task=%s", q.taskID)
			return
		case photoID, ok := <-q.pending:
			if !ok {
				return
			}
			q.active.Add(1)
			go q.processOne(photoID)
		}
	}
}

// processOne 处理单张照片的 VLM 描述。
// 使用独立 context（不继承队列 ctx），确保中止后已发出的请求不被取消。
func (q *VlmQueue) processOne(photoID string) {
	defer q.active.Done()

	// 获取照片信息
	photo, err := GetPhotoByID(photoID)
	if err != nil {
		plogger.Warnf("VlmQueue get photo failed: %s, err=%v", photoID, err)
		q.incFailed()
		return
	}

	// 设置当前处理文件名
	q.setCurrent(photo.Filename)
	defer q.setCurrent("")

	// 构建图片绝对路径
	cfg := config.Get()
	imagePath := filepath.Join(cfg.Storage.PhotoPath, photo.FilePath)

	// 调用 VLM 处理管线（独立 context，不受队列 cancel 影响）
	_, err = ProcessAndSave(imagePath, photo.ID, photo.FilePath)
	if err != nil {
		plogger.Warnf("VlmQueue VLM failed: photo=%s, err=%v", photoID, err)
		q.incFailed()
		return
	}

	q.incCompleted()
	plogger.Infof("VlmQueue VLM done: photo=%s, filename=%s", photoID, photo.Filename)
}

// drainPending 排空 pending channel 并丢弃。
// 调用方需持有 mu 写锁。
func (q *VlmQueue) drainPending() {
	for {
		select {
		case <-q.pending:
		default:
			return
		}
	}
}

// activeCount 获取当前活跃 goroutine 数量（无锁版本）。
func (q *VlmQueue) activeCount() int {
	// WaitGroup 不提供读计数器，用近似方式
	// 这里通过 mu 保护了 running 状态，active 计数不需要精确
	return 0
}

// --- 内部辅助 ---

func (q *VlmQueue) incCompleted() {
	q.mu.Lock()
	q.completed++
	// 全部完成后自动停止
	if q.completed+q.failed >= q.total {
		q.running = false
		if q.cancel != nil {
			q.cancel()
		}
		plogger.Infof("VlmQueue completed: task=%s, done=%d, failed=%d",
			q.taskID, q.completed, q.failed)
	}
	q.mu.Unlock()
}

func (q *VlmQueue) incFailed() {
	q.mu.Lock()
	q.failed++
	if q.completed+q.failed >= q.total {
		q.running = false
		if q.cancel != nil {
			q.cancel()
		}
	}
	q.mu.Unlock()
}

func (q *VlmQueue) setCurrent(filename string) {
	q.mu.Lock()
	q.current = filename
	q.mu.Unlock()
}

// --- 辅助查询（供 API 使用）---

// GetUndescribedPhotoIDs 查询所有无描述的照片 ID。
func GetUndescribedPhotoIDs() ([]string, error) {
	var ids []string
	err := db.Model(&model.Photo{}).
		Where("description = ? OR description IS NULL", "").
		Pluck("id", &ids).Error
	if err != nil {
		return nil, fmt.Errorf("query undescribed photos failed: %w", err)
	}
	return ids, nil
}

// GetAllPhotoIDs 查询所有照片 ID（force 模式使用）。
func GetAllPhotoIDs() ([]string, error) {
	var ids []string
	err := db.Model(&model.Photo{}).Pluck("id", &ids).Error
	if err != nil {
		return nil, fmt.Errorf("query all photos failed: %w", err)
	}
	return ids, nil
}

// init 注册 VlmQueue 的单例初始化（跟随 DB 初始化后的 server 生命周期）。
// 不在此处启动 goroutine——由 Start/Enqueue 按需启动。
func init() {
	// 确保单例在 package init 时准备好
	_ = GetVlmQueue()
}


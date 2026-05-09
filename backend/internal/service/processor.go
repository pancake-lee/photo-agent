package service

import (
	"context"
	"fmt"
	"image"
	"os"
	"sync"
	"time"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/model"
	"github.com/pancake-lee/photo-agent/internal/vlm"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/rwcarlsen/goexif/exif"
	"github.com/satori/go.uuid"
)

// ImportProcessor 导入处理器
type ImportProcessor struct {
	mu sync.Mutex
}

var importProcessor = &ImportProcessor{}

// GetImportProcessor 获取导入处理器单例
func GetImportProcessor() *ImportProcessor {
	return importProcessor
}

// Process 执行导入流程
func (p *ImportProcessor) Process(ctx context.Context, jobID, sourcePath string, recursive bool) {
	p.updateJobStatus(jobID, model.JobStatusProcessing, "")

	cfg := config.Get()

	// 1. 扫描目录
	images, err := ScanDirectory(sourcePath, recursive)
	if err != nil {
		p.updateJobStatus(jobID, model.JobStatusFailed, fmt.Sprintf("scan failed: %v", err))
		return
	}

	p.updateJobTotal(jobID, len(images))
	if len(images) == 0 {
		p.updateJobStatus(jobID, model.JobStatusCompleted, "no images found")
		return
	}

	// 2. 加载预描述（如果存在）
	preDesc, _ := LoadDescriptions()
	_ = preDesc

	// 3. 并发处理
	sem := make(chan struct{}, cfg.VLM.Concurrency)
	var wg sync.WaitGroup

	for i, img := range images {
		select {
		case <-ctx.Done():
			p.updateJobStatus(jobID, model.JobStatusFailed, "canceled")
			return
		default:
		}

		wg.Add(1)
		sem <- struct{}{}

		go func(idx int, imageInfo ImageInfo) {
			defer wg.Done()
			defer func() { <-sem }()

			p.processSingleImage(jobID, imageInfo, idx+1, len(images))
		}(i, img)
	}

	wg.Wait()

	// 4. 更新最终状态
	job := p.getJob(jobID)
	if job != nil && job.FailedPhotos == job.TotalPhotos && job.TotalPhotos > 0 {
		p.updateJobStatus(jobID, model.JobStatusFailed, "all photos failed")
	} else if job != nil && job.FailedPhotos > 0 {
		p.updateJobStatus(jobID, model.JobStatusCompleted, fmt.Sprintf("partial success, %d failed", job.FailedPhotos))
	} else {
		p.updateJobStatus(jobID, model.JobStatusCompleted, "success")
	}
}

// processSingleImage 处理单张图片
func (p *ImportProcessor) processSingleImage(jobID string, img ImageInfo, current, total int) {
	plogger.Infof("[%d/%d] Processing: %s", current, total, img.Filename)

	// 复制文件（若已有压缩版本则直接复用）
	relPath, err := StorePhoto(img.SourcePath, "")
	if err != nil {
		p.appendJobLog(jobID, fmt.Sprintf("store failed %s: %v", img.Filename, err))
		p.incFailed(jobID)
		return
	}

	// 获取图片尺寸与 EXIF 拍摄时间
	width, height := getImageSize(img.SourcePath)
	shotAt := getExifShotAt(img.SourcePath)

	// 根据拍摄时间匹配活动
	timeline := ""
	if shotAt != nil {
		timeline = FindEventByTime(*shotAt)
	}

	// 获取描述（仅从预描述文件读取）
	description := ""
	if desc, ok := GetPreDescription(relPath); ok {
		description = desc
		plogger.Infof("Using pre-description for %s", img.Filename)
	} else {
		plogger.Infof("No pre-description for %s, importing with empty description", img.Filename)
	}

	// 保存到数据库
	photo, err := SavePhoto(img.Filename, relPath, timeline, "", description, width, height, shotAt)
	if err != nil {
		p.appendJobLog(jobID, fmt.Sprintf("save db failed %s: %v", img.Filename, err))
		p.incFailed(jobID)
		return
	}

	// 写入 Dify 知识库（如果配置）
	if config.Get().Dify.APIKey != "" && config.Get().Dify.DatasetID != "" {
		if err := vlm.WriteToKnowledgeBase(photo.ID, description, photo.Timeline); err != nil {
			p.appendJobLog(jobID, fmt.Sprintf("dify write failed %s: %v", img.Filename, err))
			// 不标记为失败，DB 已保存
		}
	}

	p.incProcessed(jobID)
}

// --- job helpers ---

// CreateImportJob 创建导入任务
func CreateImportJob(sourcePath string, recursive bool) (*model.ImportJob, error) {
	job := &model.ImportJob{
		ID:         uuid.NewV4().String(),
		Status:     model.JobStatusPending,
		SourcePath: sourcePath,
		CreatedAt:  time.Now(),
	}

	if err := db.Create(job).Error; err != nil {
		return nil, fmt.Errorf("create job failed: %w", err)
	}

	// 异步启动处理
	go GetImportProcessor().Process(context.Background(), job.ID, sourcePath, recursive)

	return job, nil
}

// GetImportJob 查询导入任务
func GetImportJob(id string) (*model.ImportJob, error) {
	var job model.ImportJob
	if err := db.Where("id = ?", id).First(&job).Error; err != nil {
		return nil, err
	}
	return &job, nil
}

// --- private helpers ---

func (p *ImportProcessor) getJob(id string) *model.ImportJob {
	job, _ := GetImportJob(id)
	return job
}

func (p *ImportProcessor) updateJobStatus(id, status, log string) {
	p.mu.Lock()
	defer p.mu.Unlock()

	updates := map[string]any{"status": status}
	if log != "" {
		updates["log"] = log
	}
	if status == model.JobStatusCompleted || status == model.JobStatusFailed {
		now := time.Now()
		updates["completed_at"] = &now
	}

	db.Model(&model.ImportJob{}).Where("id = ?", id).Updates(updates)
	plogger.Infof("Job %s status -> %s, log: %s", id, status, log)
}

func (p *ImportProcessor) updateJobTotal(id string, total int) {
	p.mu.Lock()
	defer p.mu.Unlock()
	db.Model(&model.ImportJob{}).Where("id = ?", id).Update("total_photos", total)
}

func (p *ImportProcessor) incProcessed(id string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	db.Model(&model.ImportJob{}).Where("id = ?", id).UpdateColumn("processed_photos", db.Raw("processed_photos + 1"))
}

func (p *ImportProcessor) incFailed(id string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	db.Model(&model.ImportJob{}).Where("id = ?", id).UpdateColumn("failed_photos", db.Raw("failed_photos + 1"))
}

func (p *ImportProcessor) appendJobLog(id, msg string) {
	p.mu.Lock()
	defer p.mu.Unlock()

	var job model.ImportJob
	if err := db.Where("id = ?", id).First(&job).Error; err != nil {
		return
	}

	newLog := job.Log
	if newLog != "" {
		newLog += "\n"
	}
	newLog += msg
	db.Model(&model.ImportJob{}).Where("id = ?", id).Update("log", newLog)
}

// --- util ---

func getImageSize(path string) (int, int) {
	file, err := os.Open(path)
	if err != nil {
		return 0, 0
	}
	defer file.Close()

	config, _, err := image.DecodeConfig(file)
	if err != nil {
		return 0, 0
	}
	return config.Width, config.Height
}

func getExifShotAt(path string) *time.Time {
	file, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer file.Close()

	x, err := exif.Decode(file)
	if err != nil {
		return nil
	}

	tm, err := x.DateTime()
	if err != nil {
		return nil
	}
	return &tm
}

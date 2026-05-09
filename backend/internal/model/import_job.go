package model

import "time"

// ImportJob 导入任务模型
type ImportJob struct {
	ID              string     `gorm:"primaryKey" json:"id"`
	Status          string     `json:"status"`
	SourcePath      string     `json:"source_path"`
	TotalPhotos     int        `json:"total_photos"`
	ProcessedPhotos int        `json:"processed_photos"`
	FailedPhotos    int        `json:"failed_photos"`
	Log             string     `json:"log"`
	CreatedAt       time.Time  `json:"created_at"`
	CompletedAt     *time.Time `json:"completed_at"`
}

// TableName 指定表名
func (ImportJob) TableName() string {
	return "import_jobs"
}

// Job status constants
const (
	JobStatusPending    = "pending"
	JobStatusProcessing = "processing"
	JobStatusCompleted  = "completed"
	JobStatusFailed     = "failed"
)

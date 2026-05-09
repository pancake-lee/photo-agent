package model

import "time"

// Photo 照片元数据模型
type Photo struct {
	ID          string     `gorm:"primaryKey" json:"id"`
	Filename    string     `json:"filename"`
	FilePath    string     `json:"file_path"`
	Timeline    string     `json:"timeline"`
	Tags        string     `json:"tags"`
	Description string     `json:"description"`
	ShotAt      *time.Time `json:"shot_at"`
	Width       int        `json:"width"`
	Height      int        `json:"height"`
	ImportedAt  time.Time  `json:"imported_at"`
}

// TableName 指定表名
func (Photo) TableName() string {
	return "photos"
}

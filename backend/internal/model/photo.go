package model

import "time"

// Photo 照片元数据模型
type Photo struct {
	ID           string     `gorm:"primaryKey" json:"id"`
	Filename     string     `json:"filename"`
	FilePath     string     `json:"file_path"`
	Timeline     string     `json:"timeline"`
	Tags         string     `json:"tags"`
	Description  string     `json:"description"`
	Objects      string     `json:"objects" gorm:"type:text"`     // 主体物体/人物，逗号分隔（VLM 提取）
	Colors       string     `json:"colors" gorm:"type:text"`      // 主色调，逗号分隔（VLM 提取）
	Scene        string     `json:"scene"`                        // 场景类型（VLM 提取）
	Lighting     string     `json:"lighting"`                     // 光线特征（VLM 提取）
	Mood         string     `json:"mood"`                         // 情感氛围（VLM 提取）
	Composition  string     `json:"composition" gorm:"type:text"` // 构图特点，逗号分隔（VLM 提取）
	ShotAt       *time.Time `json:"shot_at"`
	Width        int        `json:"width"`
	Height       int        `json:"height"`
	Brand        string     `json:"brand"`
	Model        string     `json:"model"`
	Lens         string     `json:"lens"`
	FocalLength  string     `json:"focal_length"`
	Aperture     string     `json:"aperture"`
	ISO          int        `json:"iso"`
	ExposureTime string     `json:"exposure_time"`
	Latitude     *float64   `json:"latitude"`
	Longitude    *float64   `json:"longitude"`
	Altitude     *float64   `json:"altitude"`
	ImportedAt   time.Time  `json:"imported_at"`
}

// TableName 指定表名
func (Photo) TableName() string {
	return "photos"
}

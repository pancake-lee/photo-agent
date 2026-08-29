package model

import "time"

const TableNameDraft = "drafts"

type Draft struct {
	ID         string    `gorm:"column:id;primaryKey" json:"id"`
	Title      string    `gorm:"column:title;not null;default:''" json:"title"`
	Content    string    `gorm:"column:content;type:text;not null;default:''" json:"content"`
	PhotoIDs   string    `gorm:"column:photo_ids;type:text;not null;default:''" json:"photo_ids"`
	Style      string    `gorm:"column:style;not null;default:''" json:"style"`
	Source     string    `gorm:"column:source;not null;default:''" json:"source"`
	InputMode  string    `gorm:"column:input_mode;not null;default:'prompt'" json:"input_mode"`
	Prompt     string    `gorm:"column:prompt;type:text;not null;default:''" json:"prompt"`
	DraftInput string    `gorm:"column:draft_input;type:text;not null;default:''" json:"draft_input"`
	Status     string    `gorm:"column:status;not null;default:'draft'" json:"status"`
	CreatedAt  time.Time `gorm:"column:created_at;not null;default:CURRENT_TIMESTAMP" json:"created_at"`
	UpdatedAt  time.Time `gorm:"column:updated_at;not null;default:CURRENT_TIMESTAMP" json:"updated_at"`
}

func (*Draft) TableName() string { return TableNameDraft }

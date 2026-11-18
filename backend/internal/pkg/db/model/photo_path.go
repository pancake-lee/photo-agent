package model

import (
	"path/filepath"

	"gorm.io/gorm"
)

// FilePath is an API projection. Activity and filename own the stored location.
func (p *Photo) AfterFind(_ *gorm.DB) error {
	p.FilePath = filepath.Join(p.Timeline, p.Filename)
	return nil
}

// Preserve the projection even when model tags are refreshed by code generation.
func (p *Photo) BeforeSave(tx *gorm.DB) error {
	tx.Statement.Omits = append(tx.Statement.Omits, "file_path")
	return nil
}

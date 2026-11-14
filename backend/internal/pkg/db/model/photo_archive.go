package model

import "time"

// PhotoArchive tracks verified imports and manual favorites by photo identity.
type PhotoArchive struct {
	PhotoID   string `gorm:"primaryKey"`
	ImportKey string `gorm:"index"`
	Favorite  bool
	JPGSHA256 string
	NEFSHA256 string
}

func (PhotoArchive) TableName() string { return "photo_archives" }

// PhotoRecycle stores a durable file-move journal independently of live photos.
type PhotoRecycle struct {
	ID        string `gorm:"primaryKey"`
	PhotoID   string `gorm:"index"`
	Kind      string
	State     string
	DeletedAt time.Time
	PhotoJSON []byte
	FilesJSON []byte
	LastError string
}

func (PhotoRecycle) TableName() string { return "photo_recycle" }

// PhotoImportReservation binds a partial upload to its exact JPG/NEF manifest.
type PhotoImportReservation struct {
	Target    string `gorm:"primaryKey"`
	ImportKey string `gorm:"uniqueIndex"`
}

func (PhotoImportReservation) TableName() string { return "photo_import_reservations" }

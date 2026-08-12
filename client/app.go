package main

import (
	"context"
)

// App struct
type App struct {
	ctx context.Context
}

// NewApp creates a new App application struct
func NewApp() *App {
	return &App{}
}

// startup is called when the app starts. The context is saved
// so we can call the runtime methods
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
}

// IsWails returns true to indicate we are running in Wails environment.
// This is called by the frontend to detect the runtime environment.
func (a *App) IsWails() bool {
	return true
}

// ================================================================
// 导入工作流绑定方法（暴露给前端 JS，委托给 import.go 核心逻辑）
// ================================================================

// CreateStagingDirs 创建中转目录 full/like/nef。
func (a *App) CreateStagingDirs(stagingPath string) (*CreateStagingResult, error) {
	return createStagingDirs(stagingPath)
}

// ScanStaging 扫描中转目录，返回三目录文件列表与计数。
func (a *App) ScanStaging(stagingPath string) (*StagingScan, error) {
	return scanStaging(stagingPath)
}

// AnalyzeStaging 比对 full/like/nef，返回保留/删除分类、时间范围与异常检测。
func (a *App) AnalyzeStaging(stagingPath string) (*ImportAnalysis, error) {
	return analyzeStaging(stagingPath)
}

// MigrateKeptNef 将保留的 NEF 从 nef/ 复制到 like/，不删除任何文件。
func (a *App) MigrateKeptNef(stagingPath string, keepList []string) (*MigrateResult, error) {
	return migrateKeptNef(stagingPath, keepList)
}

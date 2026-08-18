package main

import (
	"context"
	"log"
	"runtime/debug"

	"github.com/wailsapp/wails/v2/pkg/runtime"
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
	applyInitialWindow(ctx)
}

// beforeClose 退出前保存当前窗口状态（尺寸/位置/是否最大化），供下次启动恢复。
func (a *App) beforeClose(ctx context.Context) bool {
	saveWindowStateOnClose(ctx)
	return false
}

// IsWails returns true to indicate we are running in Wails environment.
// This is called by the frontend to detect the runtime environment.
func (a *App) IsWails() bool {
	return true
}

// recoverPanic 捕获绑定方法内的 panic 并记录堆栈，避免进程无信息崩溃。
func (a *App) recoverPanic() {
	if r := recover(); r != nil {
		log.Printf("PANIC: %v\n%s", r, debug.Stack())
	}
}

// ChooseDirectory 弹出系统目录选择器，返回用户选择的目录路径（取消时返回空字符串）。
func (a *App) ChooseDirectory() (string, error) {
	defer a.recoverPanic()
	return runtime.OpenDirectoryDialog(a.ctx, runtime.OpenDialogOptions{
		Title:                "选择中转目录",
		CanCreateDirectories: true,
	})
}

// ================================================================
// 导入工作流绑定方法（暴露给前端 JS，委托给 import.go 核心逻辑）
// ================================================================

// CreateStagingDirs 在中转目录下创建 full/<folderName>、like/<folderName>、nef/<folderName>。
func (a *App) CreateStagingDirs(stagingPath, folderName string) (*CreateStagingResult, error) {
	defer a.recoverPanic()
	return createStagingDirs(stagingPath, folderName)
}

// ScanStaging 扫描中转目录的归档子目录，返回三目录文件列表与计数。
func (a *App) ScanStaging(stagingPath, folderName string) (*StagingScan, error) {
	defer a.recoverPanic()
	return scanStaging(stagingPath, folderName)
}

// AnalyzeStaging 比对 full/like/nef 的归档子目录，返回保留/删除分类、时间范围与异常检测。
func (a *App) AnalyzeStaging(stagingPath, folderName string) (*ImportAnalysis, error) {
	defer a.recoverPanic()
	return analyzeStaging(stagingPath, folderName)
}

// MigrateKeptNef 将保留的 NEF 从 nef/<folderName> 复制到 like/<folderName>，不删除任何文件。
func (a *App) MigrateKeptNef(stagingPath, folderName string, keepList []string) (*MigrateResult, error) {
	defer a.recoverPanic()
	return migrateKeptNef(stagingPath, folderName, keepList)
}

// PreviewImage 读取本地图片文件，返回 base64 内容供前端预览。
func (a *App) PreviewImage(path string) (string, error) {
	defer a.recoverPanic()
	return previewImage(path)
}

// GetStorageInfo 查询服务端存储目录状态。
func (a *App) GetStorageInfo(serverURL string) (*StorageInfo, error) {
	defer a.recoverPanic()
	log.Printf("GetStorageInfo: server=%s", serverURL)
	return fetchStorageInfo(serverURL)
}

// CheckConflicts 上传前检查 like/<folderName> 目录下与服务端重名的文件，供前端展示汇总并二次确认。
func (a *App) CheckConflicts(stagingPath, folderName, serverURL string) (*ConflictCheck, error) {
	defer a.recoverPanic()
	log.Printf("CheckConflicts: staging=%s folder=%s server=%s", stagingPath, folderName, serverURL)
	return checkConflicts(stagingPath, folderName, serverURL)
}

// SyncToServer 将 like/<folderName> 目录下的 JPG 与 NEF 并行上传到服务端 folderName 归档目录。
// resolution：""（沿用服务端冲突检测）、"skip"（跳过已存在文件）、"overwrite"（覆盖现有文件）。
func (a *App) SyncToServer(stagingPath, folderName, serverURL, resolution string) (*SyncResult, error) {
	defer a.recoverPanic()
	log.Printf("SyncToServer: staging=%s folder=%s server=%s resolution=%s", stagingPath, folderName, serverURL, resolution)
	return syncLikeDir(stagingPath, folderName, serverURL, resolution)
}

// Log 供前端写入客户端日志文件，便于在无法打开 devtools 时排查前端调用链路。
func (a *App) Log(msg string) {
	log.Printf("[frontend] %s", msg)
}

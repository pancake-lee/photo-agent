package main

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

// ================================================================
// 窗口初始大小与位置：首次启动按主屏 70% 居中，之后恢复上次状态。
// 状态持久化到用户配置目录（与日志同目录）下的 window.json。
// ================================================================

// WindowState 持久化的窗口状态。
//
// Width/Height 为逻辑像素（与 WindowSetSize 一致），X/Y 为绝对屏幕坐标
// （与 WindowGetPosition 一致，物理像素）。
type WindowState struct {
	Width     int  `json:"width"`
	Height    int  `json:"height"`
	X         int  `json:"x"`
	Y         int  `json:"y"`
	Maximised bool `json:"maximised"`
}

// 主屏尺寸读取失败时的兜底尺寸。
const (
	defaultWindowWidth  = 1280
	defaultWindowHeight = 800
)

// 首次启动窗口占主屏的比例。
const initialWindowRatio = 0.7

// configDir 返回客户端配置目录（os.UserConfigDir()/photo-agent），失败回退到临时目录。
func configDir() string {
	dir, err := os.UserConfigDir()
	if err != nil || dir == "" {
		dir = os.TempDir()
	}
	return filepath.Join(dir, "photo-agent")
}

// windowStatePath 窗口状态文件路径。
func windowStatePath() string {
	return filepath.Join(configDir(), "window.json")
}

// loadWindowState 读取窗口状态，文件不存在或解析失败返回 ok=false。
func loadWindowState() (WindowState, bool) {
	return loadWindowStateFrom(windowStatePath())
}

func loadWindowStateFrom(path string) (WindowState, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return WindowState{}, false
	}
	var s WindowState
	if err := json.Unmarshal(data, &s); err != nil {
		return WindowState{}, false
	}
	return s, true
}

// saveWindowState 写入窗口状态，失败静默忽略（不影响退出）。
func saveWindowState(s WindowState) {
	_ = saveWindowStateTo(windowStatePath(), s)
}

func saveWindowStateTo(path string, s WindowState) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}

// primaryScreen 返回主屏逻辑尺寸（WindowSetSize 使用的坐标系）。
// 失败时返回 0，由调用方回退默认尺寸。
func primaryScreen(ctx context.Context) (w, h int) {
	screens, err := runtime.ScreenGetAll(ctx)
	if err != nil {
		return 0, 0
	}
	idx := -1
	for i := range screens {
		if screens[i].IsPrimary {
			idx = i
			break
		}
	}
	if idx < 0 && len(screens) > 0 {
		idx = 0
	}
	if idx < 0 {
		return 0, 0
	}
	return screens[idx].Size.Width, screens[idx].Size.Height
}

// applyInitialWindow 在 OnStartup 中调用：查询主屏，恢复上次状态或按 70% 初始化，再显示窗口。
func applyInitialWindow(ctx context.Context) {
	sw, sh := primaryScreen(ctx)
	if sw <= 0 || sh <= 0 {
		sw, sh = defaultWindowWidth, defaultWindowHeight
	}

	s, ok := loadWindowState()
	// 尺寸有效且不超过主屏时恢复，否则按主屏 70% 初始化（覆盖分辨率变化、状态损坏等场景）。
	restore := ok && s.Width > 0 && s.Height > 0 && s.Width <= sw && s.Height <= sh
	if !restore {
		s = WindowState{
			Width:  int(float64(sw) * initialWindowRatio),
			Height: int(float64(sh) * initialWindowRatio),
		}
	}

	runtime.WindowSetSize(ctx, s.Width, s.Height)

	if restore {
		restorePosition(ctx, s.X, s.Y)
	} else {
		// 首次启动：居中后读回实际绝对位置再保存，避免下次误以为目标在 (0,0)。
		runtime.WindowCenter(ctx)
		s.X, s.Y = runtime.WindowGetPosition(ctx)
		saveWindowState(s)
	}

	if s.Maximised {
		runtime.WindowMaximise(ctx)
	}

	runtime.WindowShow(ctx)
}

// restorePosition 将窗口恢复到绝对屏幕坐标 (ax, ay)。
//
// Wails 的 WindowSetPosition 传入的是「相对当前显示器工作区左上角」的偏移，
// 而 WindowGetPosition 返回的是「绝对屏幕坐标」，两者坐标系不一致。
// 这里先把窗口移到当前显示器工作区原点，读出该原点的绝对坐标，再据此换算偏移量，
// 使最终位置落到 (ax, ay)，与窗口当前落在哪个显示器无关。
func restorePosition(ctx context.Context, ax, ay int) {
	runtime.WindowSetPosition(ctx, 0, 0)
	ox, oy := runtime.WindowGetPosition(ctx)
	runtime.WindowSetPosition(ctx, ax-ox, ay-oy)
}

// saveWindowStateOnClose 在 OnBeforeClose 中调用，保存退出时的窗口状态。
// 最大化时仅更新 Maximised 标记，保留上次记录的正常尺寸，便于取消最大化后正确恢复。
func saveWindowStateOnClose(ctx context.Context) {
	if runtime.WindowIsMaximised(ctx) {
		if s, ok := loadWindowState(); ok {
			s.Maximised = true
			saveWindowState(s)
		}
		return
	}
	w, h := runtime.WindowGetSize(ctx)
	x, y := runtime.WindowGetPosition(ctx)
	// Width/Height 是逻辑像素，X/Y 是绝对物理坐标，都按 Wails 原生返回原样保存。
	saveWindowState(WindowState{
		Width:     w,
		Height:    h,
		X:         x,
		Y:         y,
		Maximised: false,
	})
}

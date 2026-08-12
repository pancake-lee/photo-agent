package main

import (
	"embed"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	// WebView2 DevTools：通过 Wails build tags (devtools + debug) 启用
	// - 右键 → 检查 / Inspect
	// - F12 / Ctrl+Shift+I 打开 DevTools
	// - 启动时自动弹出 DevTools 窗口

	app := NewApp()

	err := wails.Run(&options.App{
		Title:  "Photo Agent",
		Width:  1280,
		Height: 800,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		BackgroundColour:         &options.RGBA{R: 16, G: 16, B: 20, A: 1},
		EnableDefaultContextMenu: true,
		OnStartup:                app.startup,
		Bind: []interface{}{
			app,
		},
	})

	if err != nil {
		println("Error:", err.Error())
	}
}

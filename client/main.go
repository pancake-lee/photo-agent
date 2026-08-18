package main

import (
	"embed"
	"log"
	"runtime/debug"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	// 尽早初始化日志，捕获启动期与运行期崩溃信息（panic / 致命错误 / 访问违例）
	setupLogging()

	app := NewApp()

	defer func() {
		if r := recover(); r != nil {
			log.Printf("PANIC (main): %v\n%s", r, debug.Stack())
		}
	}()

	err := wails.Run(&options.App{
		Title:  "Photo Agent",
		Width:  1280,
		Height: 800,
		// 隐藏启动：在 OnStartup 中按主屏 70% 或上次状态计算好尺寸再显示，避免启动瞬间尺寸跳变。
		StartHidden:               true,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		BackgroundColour:         &options.RGBA{R: 16, G: 16, B: 20, A: 1},
		EnableDefaultContextMenu: true,
		OnStartup:                app.startup,
		OnBeforeClose:            app.beforeClose,
		Bind: []interface{}{
			app,
		},
	})

	if err != nil {
		log.Printf("wails.Run error: %v", err)
		println("Error:", err.Error())
	}
}

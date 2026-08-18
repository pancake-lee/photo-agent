package main

import (
	"log"
	"os"
	"path/filepath"
	"runtime"
	"runtime/debug"
)

// setupLogging 将日志与标准错误输出重定向到文件，便于收集崩溃信息。
// 必须在 main 最早阶段调用，确保启动期崩溃也能被捕获。
func setupLogging() {
	// 崩溃 / panic 时打印全部 goroutine 堆栈
	debug.SetTraceback("all")

	dir := configDir()
	_ = os.MkdirAll(dir, 0o755)

	f, err := os.OpenFile(filepath.Join(dir, "photo-agent.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return
	}

	log.SetOutput(f)
	log.SetFlags(log.LstdFlags | log.Lmicroseconds | log.Lshortfile)

	// 让 Go 代码层的 stdout / stderr 也写入日志
	os.Stdout = f
	os.Stderr = f
	// 重定向底层句柄，捕获 runtime 的致命错误（panic / 访问违例）
	redirectStdError(f)

	log.Printf("=== photo-agent 启动 === pid=%d go=%s", os.Getpid(), runtime.Version())
}

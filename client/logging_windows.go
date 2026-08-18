//go:build windows

package main

import (
	"os"

	"golang.org/x/sys/windows"
)

// redirectStdError 重定向标准错误 / 输出句柄，使 runtime 崩溃信息写入日志文件。
func redirectStdError(f *os.File) {
	h := windows.Handle(f.Fd())
	_ = windows.SetStdHandle(windows.STD_ERROR_HANDLE, h)
	_ = windows.SetStdHandle(windows.STD_OUTPUT_HANDLE, h)
}

//go:build !windows

package main

import "os"

// redirectStdError 非 Windows 平台无需额外处理，runtime 崩溃信息由终端直接展示。
func redirectStdError(f *os.File) {}

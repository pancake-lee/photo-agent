//go:build !windows

package main

import "os"

// preserveTimes 非 Windows 平台仅回写修改时间（创建时间不可回写）。
func preserveTimes(dst string, srcInfo os.FileInfo) error {
	mtime := srcInfo.ModTime()
	return os.Chtimes(dst, mtime, mtime)
}

//go:build windows

package main

import (
	"os"
	"syscall"

	"golang.org/x/sys/windows"
)

// preserveTimes 复制后回写源文件的创建/访问/修改时间，使副本时间戳与原文件一致。
func preserveTimes(dst string, srcInfo os.FileInfo) error {
	srcWin, ok := srcInfo.Sys().(*syscall.Win32FileAttributeData)
	if !ok {
		// 兜底：仅回写修改时间
		mtime := srcInfo.ModTime()
		return os.Chtimes(dst, mtime, mtime)
	}

	path, err := windows.UTF16PtrFromString(dst)
	if err != nil {
		return err
	}
	h, err := windows.CreateFile(path, windows.GENERIC_WRITE,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE, nil,
		windows.OPEN_EXISTING, windows.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(h)

	// syscall.Filetime 与 windows.Filetime 布局一致，逐字段转换。
	ct := windows.Filetime{LowDateTime: srcWin.CreationTime.LowDateTime, HighDateTime: srcWin.CreationTime.HighDateTime}
	at := windows.Filetime{LowDateTime: srcWin.LastAccessTime.LowDateTime, HighDateTime: srcWin.LastAccessTime.HighDateTime}
	wt := windows.Filetime{LowDateTime: srcWin.LastWriteTime.LowDateTime, HighDateTime: srcWin.LastWriteTime.HighDateTime}
	return windows.SetFileTime(h, &ct, &at, &wt)
}

//go:build windows

package main

import (
	"fmt"
	"runtime"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	recycleShell = windows.NewLazySystemDLL("shell32.dll")
	recycleCOM   = windows.NewLazySystemDLL("ole32.dll")
	recycleClass = windows.GUID{Data1: 0x3ad05575, Data2: 0x8857, Data3: 0x4850,
		Data4: [8]byte{0x92, 0x77, 0x11, 0xb8, 0x5b, 0xdb, 0x8e, 0x09}}
	recycleIID = windows.GUID{Data1: 0x947aab5f, Data2: 0x0a5c, Data3: 0x4c13,
		Data4: [8]byte{0xb4, 0xd6, 0x4b, 0xf7, 0x83, 0x6f, 0xc9, 0xf8}}
	recycleShellItemIID = windows.GUID{Data1: 0x43826d1e, Data2: 0xe718, Data3: 0x42ee,
		Data4: [8]byte{0xbc, 0x55, 0xa1, 0xe2, 0x61, 0xc3, 0x7b, 0xfe}}
)

func importRecycleVolume(path string) (string, error) {
	file, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return "", err
	}
	buffer := make([]uint16, windows.MAX_PATH)
	err = windows.GetVolumePathName(file, &buffer[0], uint32(len(buffer)))
	if err != nil {
		return "", err
	}
	root := windows.UTF16ToString(buffer)
	drive := windows.GetDriveType(&buffer[0])
	if drive != windows.DRIVE_FIXED && drive != windows.DRIVE_REMOVABLE {
		return "", fmt.Errorf("卷不支持回收站: %s", root)
	}
	// SHQUERYRBINFO uses native alignment on 64-bit Windows.
	info := struct {
		Size         uint32
		Bytes, Items int64
	}{}
	info.Size = uint32(unsafe.Sizeof(info))
	hr, _, _ := recycleShell.NewProc("SHQueryRecycleBinW").Call(
		uintptr(unsafe.Pointer(&buffer[0])), uintptr(unsafe.Pointer(&info)),
	)
	if hr != 0 {
		return "", fmt.Errorf("卷回收站不可用: %s (0x%08x)", root, uint32(hr))
	}
	return root, nil
}

func moveImportFile(source, target string) error {
	from, err := windows.UTF16PtrFromString(source)
	if err != nil {
		return err
	}
	to, err := windows.UTF16PtrFromString(target)
	if err != nil {
		return err
	}
	return windows.MoveFileEx(from, to, windows.MOVEFILE_WRITE_THROUGH)
}

func recycleCOMCall(object *[1]*[23]uintptr, index int, args ...uintptr) error {
	hr, _, _ := syscall.SyscallN(object[0][index], append([]uintptr{uintptr(unsafe.Pointer(object))}, args...)...)
	if int32(hr) < 0 {
		return fmt.Errorf("Windows 回收站调用失败 (0x%08x)", uint32(hr))
	}
	return nil
}

func sendImportDirectoryToRecycleBin(path string) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	hr, _, _ := recycleCOM.NewProc("CoInitializeEx").Call(0, 2)
	if int32(hr) < 0 {
		return fmt.Errorf("初始化 Windows 回收站失败 (0x%08x)", uint32(hr))
	}
	defer recycleCOM.NewProc("CoUninitialize").Call()
	var operation, item *[1]*[23]uintptr
	hr, _, _ = recycleCOM.NewProc("CoCreateInstance").Call(
		uintptr(unsafe.Pointer(&recycleClass)), 0, 1,
		uintptr(unsafe.Pointer(&recycleIID)), uintptr(unsafe.Pointer(&operation)),
	)
	if int32(hr) < 0 {
		return fmt.Errorf("开启 Windows 回收站失败 (0x%08x)", uint32(hr))
	}
	var pin runtime.Pinner
	defer pin.Unpin()
	defer recycleCOMCall(operation, 2) // IUnknown.Release
	p, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return err
	}
	hr, _, _ = recycleShell.NewProc("SHCreateItemFromParsingName").Call(
		uintptr(unsafe.Pointer(p)), 0, uintptr(unsafe.Pointer(&recycleShellItemIID)),
		uintptr(unsafe.Pointer(&item)),
	)
	if int32(hr) < 0 {
		return fmt.Errorf("定位 Windows 回收目录失败 (0x%08x)", uint32(hr))
	}
	defer recycleCOMCall(item, 2)
	const (
		recycleOnDelete = 0x00080000
		earlyFailure    = 0x00100000
		noErrorUI       = 0x0400
		wantNukeWarning = 0x4000
	)
	sink := &recycleProgressSink{vtable: &recycleSinkVTable}
	pin.Pin(sink)
	err = recycleCOMCall(operation, 5, recycleOnDelete|earlyFailure|noErrorUI|wantNukeWarning)
	if err == nil {
		err = recycleCOMCall(operation, 18, uintptr(unsafe.Pointer(item)), uintptr(unsafe.Pointer(sink)))
	}
	if err == nil {
		err = recycleCOMCall(operation, 21)
	}
	if err != nil {
		return err
	}
	var aborted uint32
	err = recycleCOMCall(operation, 22, uintptr(unsafe.Pointer(&aborted)))
	if err == nil && (aborted != 0 || sink.recycled == 0) {
		err = fmt.Errorf("Windows 回收站未确认接收该目录")
	}
	return err
}

// IFileOperation may fall back to a permanent delete on volumes with no
// usable Recycle Bin. Veto the fallback before the Shell changes any file.
type recycleProgressSink struct {
	vtable   *[19]uintptr
	recycled uint32
}

var recycleSinkIID = windows.GUID{
	Data1: 0x04b0f1a7, Data2: 0x9490, Data3: 0x44bc,
	Data4: [8]byte{0x96, 0xe1, 0x42, 0x96, 0xa3, 0x12, 0x52, 0xe2},
}

var recycleIUnknownIID = windows.GUID{Data4: [8]byte{0xc0, 0, 0, 0, 0, 0, 0, 0x46}}

var recycleSinkVTable = [19]uintptr{
	syscall.NewCallback(func(self, iid, out uintptr) uintptr {
		requested := (*windows.GUID)(unsafe.Pointer(iid))
		pointer := (*uintptr)(unsafe.Pointer(out))
		if *requested != recycleSinkIID && *requested != recycleIUnknownIID {
			*pointer = 0
			return 0x80004002 // E_NOINTERFACE
		}
		*pointer = self
		return 0
	}),
	syscall.NewCallback(func(uintptr) uintptr { return 2 }),
	syscall.NewCallback(func(uintptr) uintptr { return 1 }),
	syscall.NewCallback(func(uintptr) uintptr { return 0 }),                            // StartOperations
	syscall.NewCallback(func(uintptr, uintptr) uintptr { return 0 }),                   // FinishOperations
	syscall.NewCallback(func(uintptr, uintptr, uintptr, uintptr) uintptr { return 0 }), // PreRenameItem
	syscall.NewCallback(func(uintptr, uintptr, uintptr, uintptr, uintptr, uintptr) uintptr { return 0 }),
	syscall.NewCallback(func(uintptr, uintptr, uintptr, uintptr, uintptr) uintptr { return 0 }), // PreMoveItem
	syscall.NewCallback(func(uintptr, uintptr, uintptr, uintptr, uintptr, uintptr, uintptr) uintptr { return 0 }),
	syscall.NewCallback(func(uintptr, uintptr, uintptr, uintptr, uintptr) uintptr { return 0 }), // PreCopyItem
	syscall.NewCallback(func(uintptr, uintptr, uintptr, uintptr, uintptr, uintptr, uintptr) uintptr { return 0 }),
	syscall.NewCallback(func(_ uintptr, flags uintptr, _ uintptr) uintptr {
		const recycleIfPossible = 0x80
		if flags&recycleIfPossible == 0 {
			return 0x80004004 // E_ABORT
		}
		return 0
	}),
	syscall.NewCallback(func(self, _ uintptr, _ uintptr, hr, newItem uintptr) uintptr {
		if int32(hr) >= 0 && newItem != 0 {
			sink := (*recycleProgressSink)(unsafe.Pointer(self))
			sink.recycled++
		}
		return 0
	}),
	syscall.NewCallback(func(uintptr, uintptr, uintptr, uintptr) uintptr { return 0 }), // PreNewItem
	syscall.NewCallback(func(uintptr, uintptr, uintptr, uintptr, uintptr, uintptr, uintptr, uintptr) uintptr { return 0 }),
	syscall.NewCallback(func(uintptr, uintptr, uintptr) uintptr { return 0 }), // UpdateProgress
	syscall.NewCallback(func(uintptr) uintptr { return 0 }),                   // ResetTimer
	syscall.NewCallback(func(uintptr) uintptr { return 0 }),                   // PauseTimer
	syscall.NewCallback(func(uintptr) uintptr { return 0 }),                   // ResumeTimer
}

//go:build windows

package main

import (
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/windows"
)

// ================================================================
// 单实例约束：客户端只允许一个实例运行。
// 新实例启动时检测到旧实例，直接强杀旧实例，等待其退出释放
// 互斥体后重新占坑，再继续正常启动。
// ================================================================

// mutexName 命名互斥体，用 Local\ 前缀（当前用户会话内可见）。
const mutexName = `Local\PhotoAgentSingleInstance`

// mutexReleaseTimeout 强杀旧实例后等待其释放互斥体的总时长。
const mutexReleaseTimeout = 5 * time.Second

// mutexReleaseInterval 轮询互斥体是否释放的间隔。
const mutexReleaseInterval = 50 * time.Millisecond

// ensureSingleInstance 保证单实例运行，必须在 wails.Run 之前调用。
//
// 首实例创建并持有互斥体（进程退出时由系统释放），写入 PID 文件。
// 非首实例检测到旧实例后直接强杀，等互斥体释放后重新占坑继续启动。
func ensureSingleInstance() {
	mutex, created, err := createMutex(mutexName)
	if err != nil {
		// 创建失败（权限等极端场景）不阻塞启动，退化为允许多开。
		log.Printf("singleinstance: create mutex failed: %v", err)
		return
	}

	if created {
		// 首实例：句柄保持打开直至进程退出（uintptr 不被 GC 回收），写 PID 供后续实例强杀。
		_ = mutex
		writePidFile()
		return
	}

	// 非首实例：旧实例在运行，直接强杀。
	log.Printf("singleinstance: 检测到旧实例，强杀后接管")
	windows.CloseHandle(mutex)

	killOldInstance()

	// 等旧实例进程完全退出、释放互斥体后，重新获取并持有，成为新的守护者。
	waitMutexReleased(mutexReleaseTimeout)

	_, created2, err2 := createMutex(mutexName)
	if err2 != nil {
		log.Printf("singleinstance: 重新获取互斥体失败: %v", err2)
		return
	}
	if created2 {
		writePidFile()
	} else {
		// 理论上不会走到这：旧实例已被强杀，互斥体应已释放。
		log.Printf("singleinstance: 重新占坑失败，互斥体仍被占用")
	}
}

// killOldInstance 读 PID 文件并强杀旧实例。PID 缺失或进程已退出时仅记日志。
func killOldInstance() {
	pid, ok := readPidFile()
	if !ok {
		log.Printf("singleinstance: 无 PID 文件，无法定位旧实例")
		return
	}
	if err := terminateProcessByPid(pid); err != nil {
		log.Printf("singleinstance: 强杀旧实例 pid=%d 失败: %v", pid, err)
	} else {
		log.Printf("singleinstance: 已强杀旧实例 pid=%d", pid)
	}
}

// waitMutexReleased 轮询等待互斥体释放（旧实例进程完全退出）。
func waitMutexReleased(timeout time.Duration) {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		h, err := tryOpenMutex(mutexName)
		if err != nil {
			return // 互斥体已释放
		}
		windows.CloseHandle(h)
		time.Sleep(mutexReleaseInterval)
	}
	log.Printf("singleinstance: 等待旧实例释放互斥体超时 %v", timeout)
}

// createMutex 创建命名互斥体。created=false 表示已存在（有旧实例）。
// 返回的句柄在进程生命周期内保持打开。
func createMutex(name string) (handle windows.Handle, created bool, err error) {
	ptr, err := windows.UTF16PtrFromString(name)
	if err != nil {
		return 0, false, err
	}
	h, err := windows.CreateMutex(nil, false, ptr)
	if err != nil && err != windows.ERROR_ALREADY_EXISTS {
		return 0, false, err
	}
	// CreateMutex 对已存在对象返回句柄 + ERROR_ALREADY_EXISTS，两者都算成功打开。
	return h, err == nil, nil
}

// tryOpenMutex 尝试按 SYNCHRONIZE 打开命名互斥体，用于探测是否仍被持有。
func tryOpenMutex(name string) (windows.Handle, error) {
	ptr, err := windows.UTF16PtrFromString(name)
	if err != nil {
		return 0, err
	}
	return windows.OpenMutex(windows.SYNCHRONIZE, false, ptr)
}

// terminateProcessByPid 强杀指定进程。PID 已不存在时视为成功。
func terminateProcessByPid(pid int) error {
	h, err := windows.OpenProcess(windows.PROCESS_TERMINATE, false, uint32(pid))
	if err != nil {
		if err == windows.ERROR_INVALID_PARAMETER {
			// 进程不存在：可能已自行退出。
			return nil
		}
		return err
	}
	defer windows.CloseHandle(h)
	return windows.TerminateProcess(h, 1)
}

// ── PID 文件（强杀定位用） ──

// pidFilePath PID 文件路径，与日志、窗口状态同目录。
func pidFilePath() string {
	return filepath.Join(configDir(), "pid")
}

// writePidFile 写入当前进程 PID，失败仅记日志不影响启动。
func writePidFile() {
	if err := os.MkdirAll(configDir(), 0o755); err != nil {
		log.Printf("singleinstance: mkdir config dir failed: %v", err)
		return
	}
	if err := os.WriteFile(pidFilePath(), []byte(strconv.Itoa(os.Getpid())), 0o644); err != nil {
		log.Printf("singleinstance: write pid file failed: %v", err)
	}
}

// readPidFile 读取 PID 文件，文件不存在或内容非法返回 ok=false。
func readPidFile() (pid int, ok bool) {
	return readPidFileFrom(pidFilePath())
}

func readPidFileFrom(path string) (pid int, ok bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	p, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil || p <= 0 {
		return 0, false
	}
	return p, true
}

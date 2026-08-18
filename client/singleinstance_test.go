//go:build windows

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPidFileRoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "pid")

	if _, ok := readPidFileFrom(path); ok {
		t.Fatal("不存在的 PID 文件不应读取成功")
	}

	if err := os.WriteFile(path, []byte("1234"), 0o644); err != nil {
		t.Fatal(err)
	}
	pid, ok := readPidFileFrom(path)
	if !ok || pid != 1234 {
		t.Fatalf("期望 1234/true，得到 %d/%v", pid, ok)
	}
}

func TestPidFileCorrupt(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "pid")

	for _, content := range []string{"", "abc", "-5", "0"} {
		if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
		if _, ok := readPidFileFrom(path); ok {
			t.Fatalf("非法内容 %q 不应读取成功", content)
		}
	}
}

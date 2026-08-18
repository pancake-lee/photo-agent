package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestSaveAndLoadWindowState(t *testing.T) {
	path := filepath.Join(t.TempDir(), "window.json")

	want := WindowState{Width: 1200, Height: 700, X: 30, Y: 40, Maximised: true}
	if err := saveWindowStateTo(path, want); err != nil {
		t.Fatalf("saveWindowStateTo: %v", err)
	}
	got, ok := loadWindowStateFrom(path)
	if !ok {
		t.Fatal("loadWindowStateFrom 返回 ok=false，期望 true")
	}
	if got != want {
		t.Fatalf("往返结果不一致: got=%+v want=%+v", got, want)
	}
}

func TestLoadWindowStateMissing(t *testing.T) {
	if _, ok := loadWindowStateFrom(filepath.Join(t.TempDir(), "not-exist.json")); ok {
		t.Fatal("文件不存在时应返回 ok=false")
	}
}

func TestLoadWindowStateCorrupt(t *testing.T) {
	path := filepath.Join(t.TempDir(), "window.json")
	if err := os.WriteFile(path, []byte("{not json"), 0o644); err != nil {
		t.Fatalf("write: %v", err)
	}
	if _, ok := loadWindowStateFrom(path); ok {
		t.Fatal("内容损坏时应返回 ok=false")
	}
}

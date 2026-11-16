//go:build !windows

package main

import (
	"errors"
	"fmt"
	"os"
	"syscall"
)

func importRecycleVolume(path string) (string, error) {
	return "", fmt.Errorf("卷不支持 Windows 回收站: %s", path)
}

func isImportCrossVolume(err error) bool {
	return errors.Is(err, syscall.EXDEV)
}

func sendImportDirectoryToRecycleBin(path string) error {
	return fmt.Errorf("Windows 回收站不可用: %s", path)
}

func moveImportFile(source, target string) error {
	err := os.Link(source, target)
	if err != nil {
		return err
	}
	err = os.Remove(source)
	if err != nil {
		_ = os.Remove(target)
	}
	return err
}

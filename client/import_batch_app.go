package main

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

func (a *App) ChooseImportSource() (string, error) {
	return runtime.OpenDirectoryDialog(a.ctx, runtime.OpenDialogOptions{
		Title: "选择照片来源目录",
	})
}

func (a *App) ListImportBatches() ([]ImportBatchSummary, error) {
	a.batchMu.Lock()
	defer a.batchMu.Unlock()
	return listImportBatches(importBatchRoot())
}

func (a *App) GetImportBatch(id string) (*ImportBatch, error) {
	a.batchMu.Lock()
	defer a.batchMu.Unlock()
	return loadImportBatch(importBatchRoot(), id)
}

func validImportActivity(activity string) bool {
	return strings.TrimSpace(activity) == activity &&
		activity != "" && activity != "." && activity != ".." &&
		!strings.HasSuffix(activity, ".") &&
		!strings.ContainsAny(activity, "/\\:*?\"<>|\x00\n\r\t") &&
		len(activity) <= 150
}

func (a *App) ScanImportBatch(
	id, activity string, sources []ImportBatchSource, complete bool,
) (*ImportBatch, error) {
	a.batchMu.Lock()
	defer a.batchMu.Unlock()

	if !validImportActivity(activity) || len(sources) == 0 {
		return nil, fmt.Errorf("填写有效的活动目录名，并至少添加一个来源")
	}
	hasRetained := false
	for _, source := range sources {
		switch source.Role {
		case "local", "favorite", "starting":
		case "retained":
			hasRetained = true
		default:
			return nil, fmt.Errorf("未知来源类型 %q", source.Role)
		}
		if !filepath.IsAbs(source.Path) {
			return nil, fmt.Errorf("需要绝对目录路径: %s", source.Path)
		}
	}
	if complete && !hasRetained {
		return nil, fmt.Errorf("推导废弃需要完整留存导出目录")
	}
	var old *ImportBatch
	var err error
	root := importBatchRoot()
	if id == "" {
		id, err = newImportBatchID()
	} else {
		old, err = loadImportBatch(root, id)
	}
	if err != nil {
		return nil, err
	}
	if old != nil && old.Activity != activity {
		return nil, fmt.Errorf("批次活动不可改名，请新建批次")
	}
	batch := &ImportBatch{
		ID: id, Activity: activity, Sources: sources,
		Complete: complete,
	}
	scanImportBatch(root, batch, old)
	return batch, saveImportBatch(root, batch)
}

func (a *App) DecideImportBatch(
	id string, entries []string, decision string,
) (*ImportBatch, error) {
	return a.editImportBatch(id, func(batch *ImportBatch) error {
		return batch.setDecisions(entries, decision)
	})
}

func (a *App) UndoImportBatch(id string) (*ImportBatch, error) {
	return a.editImportBatch(id, func(batch *ImportBatch) error {
		batch.undoDecisions()
		return nil
	})
}

func (a *App) ResolveImportPair(id, entryID, nefPath string) (*ImportBatch, error) {
	return a.editImportBatch(id, func(batch *ImportBatch) error {
		for i := range batch.Entries {
			entry := &batch.Entries[i]
			if entry.ID != entryID || entry.JPG == nil || entry.Upload != nil {
				continue
			}
			if nefPath == "" && !entry.ReferenceOnly {
				entry.NEF, entry.Pair = nil, "manual"
				return nil
			}
			for _, candidate := range entry.NEFCandidates {
				if candidate.Path != nefPath {
					continue
				}
				for j := range batch.Entries {
					other := &batch.Entries[j]
					if i != j && other.JPG != nil && other.NEF != nil &&
						other.NEF.Path == nefPath {
						return fmt.Errorf("NEF 已配对到 %s", other.JPG.Path)
					}
				}
				entry.NEF, entry.Pair = candidate, "manual"
				for j := range batch.Entries {
					other := &batch.Entries[j]
					if other.JPG == nil && other.NEF != nil && other.NEF.Path == nefPath {
						batch.Entries = append(batch.Entries[:j], batch.Entries[j+1:]...)
						break
					}
				}
				return nil
			}
		}
		return fmt.Errorf("NEF 不在此条目的待核对清单中")
	})
}

func (a *App) SetImportShotAt(id, entryID, shotAt string) (*ImportBatch, error) {
	return a.editImportBatch(id, func(batch *ImportBatch) error {
		parsed := parseImportShotTime(shotAt)
		if shotAt != "" && parsed == "" {
			return fmt.Errorf("拍摄时间格式应为 YYYY-MM-DD HH:mm:ss")
		}
		for i := range batch.Entries {
			entry := &batch.Entries[i]
			if entry.ID == entryID && entry.JPG != nil && entry.Upload == nil {
				entry.ShotAt = parsed
				batch.Bursts = nil
				return nil
			}
		}
		return fmt.Errorf("此条目无法修改拍摄时间")
	})
}

func (a *App) editImportBatch(id string, edit func(*ImportBatch) error) (*ImportBatch, error) {
	a.batchMu.Lock()
	defer a.batchMu.Unlock()
	root := importBatchRoot()
	batch, err := loadImportBatch(root, id)
	if err != nil {
		return nil, err
	}
	err = edit(batch)
	if err != nil {
		return nil, err
	}
	return batch, saveImportBatch(root, batch)
}

package main

import (
	"context"
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

func (a *App) ChooseImportRecycleDirectory() (string, error) {
	return runtime.OpenDirectoryDialog(a.ctx, runtime.OpenDialogOptions{
		Title: "选择回收归集位置",
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
	root := importBatchRoot()
	batch, err := loadImportBatch(root, id)
	if err != nil {
		return nil, err
	}
	batch.Name, err = importBatchName(root, batch)
	return batch, err
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
	if old != nil && old.workflowStep() != "review" {
		return nil, fmt.Errorf("返回选片后再重新扫描来源")
	}
	batch := &ImportBatch{
		ID: id, Activity: activity, Sources: sources,
		Complete: complete,
	}
	if old != nil {
		batch.Name, batch.StageServers = old.Name, old.StageServers
	}
	batch.Name, err = importBatchName(root, batch)
	if err != nil {
		return nil, err
	}
	scanImportBatch(root, batch, old)
	return batch, saveImportBatch(root, batch)
}

func (a *App) DecideImportBatch(
	id string, entries []string, decision string,
) (*ImportBatch, error) {
	return a.editImportReview(id, func(batch *ImportBatch) error {
		return batch.setDecisions(entries, decision)
	})
}

func (a *App) UndoImportBatch(id string) (*ImportBatch, error) {
	return a.editImportReview(id, func(batch *ImportBatch) error {
		batch.undoDecisions()
		return nil
	})
}

func (a *App) ResolveImportPair(id, entryID, nefPath string) (*ImportBatch, error) {
	return a.editImportReview(id, func(batch *ImportBatch) error {
		for i := range batch.Entries {
			entry := &batch.Entries[i]
			if entry.ID != entryID || entry.JPG == nil || entry.Upload != nil {
				continue
			}
			if nefPath == "" && !entry.ReferenceOnly {
				entry.NEF, entry.Pair = nil, "manual"
				batch.Bursts = nil
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
				batch.Bursts = nil
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
	return a.editImportReview(id, func(batch *ImportBatch) error {
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

func (a *App) editImportReview(id string, edit func(*ImportBatch) error) (*ImportBatch, error) {
	return a.editImportBatch(id, func(batch *ImportBatch) error {
		if batch.workflowStep() != "review" {
			return fmt.Errorf("请在选片步骤修改照片")
		}
		return edit(batch)
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
	batch.Name, err = importBatchName(root, batch)
	if err != nil {
		return nil, err
	}
	err = edit(batch)
	if err != nil {
		return nil, err
	}
	return batch, saveImportBatch(root, batch)
}

func (batch *ImportBatch) workflowStep() string {
	if batch.Step == "" {
		return "review"
	}
	return batch.Step
}

func (a *App) AdvanceImportBatch(id, next string, leaveLocal bool) (*ImportBatch, error) {
	return a.editImportBatch(id, func(batch *ImportBatch) error {
		return batch.advance(next, leaveLocal)
	})
}

func (batch *ImportBatch) advance(next string, leaveLocal bool) error {
	step := batch.workflowStep()
	switch {
	case next == "review" && (step == "reject" || step == "archive"):
	case step == "review" && next == "reject":
		if len(batch.Entries) == 0 {
			return fmt.Errorf("请先扫描照片来源")
		}
	case step == "reject" && next == "archive":
		if err := checkImportRecycleStep(batch, "discarded", leaveLocal); err != nil {
			return err
		}
	case step == "archive" && next == "keep":
		for _, entry := range batch.Entries {
			if entry.canUpload() && (entry.Upload == nil || !entry.Upload.Verified) {
				return fmt.Errorf("仍有照片未通过入库核验，请重试或返回选片")
			}
		}
	case step == "keep" && next == "finish":
		if err := checkImportRecycleStep(batch, "imported", leaveLocal); err != nil {
			return err
		}
	default:
		return fmt.Errorf("请按当前导入步骤继续")
	}
	batch.Step = next
	return nil
}

func (a *App) FinishImportBatch(id string) (*ImportBatch, error) {
	return a.editImportBatch(id, func(batch *ImportBatch) error {
		if batch.Step == "done" {
			return nil
		}
		if batch.Step != "finish" {
			return fmt.Errorf("请先完成入库和本地原片回收步骤")
		}
		servers := append([]string(nil), batch.StageServers...)
		for _, entry := range batch.Entries {
			servers = append(servers, entry.StagedServer)
		}
		if batch.Bursts != nil {
			servers = append(servers, batch.Bursts.Server)
		}
		seen := make(map[string]bool)
		for _, server := range servers {
			if server == "" || seen[server] {
				continue
			}
			seen[server] = true
			err := cleanupImportStage(context.Background(), server, batch.ID)
			if err != nil {
				return fmt.Errorf("清理 %s 上的批次暂存失败: %w", server, err)
			}
		}
		for i := range batch.Entries {
			batch.Entries[i].StagedServer = ""
		}
		batch.StageServers = nil
		batch.Step = "done"
		return nil
	})
}

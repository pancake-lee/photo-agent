package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

type ImportRecycleFile struct {
	Source      string `json:"source"`
	Relative    string `json:"relative"`
	SHA256      string `json:"sha256"`
	Status      string `json:"status"`
	RestoredTo  string `json:"restored_to,omitempty"`
	Error       string `json:"error,omitempty"`
	Destination string `json:"destination,omitempty"`
}

type ImportRecycleGroup struct {
	Directory string              `json:"directory"`
	Kind      string              `json:"kind"`
	Status    string              `json:"status"`
	Files     []ImportRecycleFile `json:"files"`
	Error     string              `json:"error,omitempty"`
}

func collectImportRecycle(batch *ImportBatch, kind string) []*ImportBatchFile {
	var result []*ImportBatchFile
	seen := make(map[string]bool)
	protected := make(map[string]bool)
	for _, entry := range batch.Entries {
		if importRecycleEligible(entry, kind) || entry.Pair == "nef_only" || entry.Historical {
			continue
		}
		for _, file := range append([]*ImportBatchFile{entry.JPG, entry.NEF}, entry.NEFCandidates...) {
			if file != nil {
				protected[file.Path] = true
			}
		}
	}
	for _, entry := range batch.Entries {
		if !importRecycleEligible(entry, kind) {
			continue
		}
		jpg := entry.JPG
		if entry.ReferenceOnly {
			jpg = nil
		}
		for _, file := range []*ImportBatchFile{jpg, entry.NEF} {
			if file == nil || protected[file.Path] || seen[file.Path] {
				continue
			}
			seen[file.Path] = true
			result = append(result, file)
		}
	}
	return result
}

func importRecycleEligible(entry ImportBatchEntry, kind string) bool {
	if entry.Historical || entry.JPG == nil || entry.Conflict || entry.Pair == "review" {
		return false
	}
	if kind == "imported" {
		return entry.canUpload() && entry.Upload != nil && entry.Upload.Verified
	}
	return kind == "discarded" && entry.Decision == batchDiscarded && entry.Origin == "manual"
}

func verifyArchivedImportForRecycle(batch *ImportBatch) map[string]string {
	failures := make(map[string]string)
	for _, entry := range batch.Entries {
		if !importRecycleEligible(entry, "imported") {
			continue
		}
		receipt := entry.Upload
		req := entry.archiveManifest(batch.Activity)
		result, err := archiveRPC(context.Background(), receipt.Server, "preview", req, "", nil)
		if err == nil && (!result.Verified || result.PhotoID != receipt.PhotoID) {
			err = fmt.Errorf("服务器未核验该照片及所需的原片")
		}
		if err == nil {
			for _, file := range []*ImportBatchFile{entry.JPG, entry.NEF} {
				if file == nil {
					continue
				}
				_, statErr := os.Lstat(file.Path)
				if os.IsNotExist(statErr) {
					// A previous attempt may have already staged it.
					continue
				}
				err = verifyRecycleDigest(file.Path, file.SHA256)
				if err != nil {
					break
				}
			}
		}
		if err != nil {
			failures[entry.JPG.Path] = err.Error()
			if entry.NEF != nil {
				failures[entry.NEF.Path] = err.Error()
			}
		}
	}
	return failures
}

func (a *App) PreviewImportRecycle(id, kind string) ([]ImportRecycleFile, error) {
	batch, err := a.GetImportBatch(id)
	if err != nil {
		return nil, err
	}
	result := make([]ImportRecycleFile, 0)
	for _, file := range pendingImportRecycle(batch, kind) {
		result = append(result, ImportRecycleFile{
			Source: file.Path, SHA256: file.SHA256, Destination: filepath.Dir(file.Path),
		})
	}
	return result, nil
}

func pendingImportRecycle(batch *ImportBatch, kind string) []*ImportBatchFile {
	done := make(map[string]bool)
	for _, group := range batch.Recycling {
		for _, file := range group.Files {
			switch file.Status {
			case "recycled", "deleted":
				done[file.Source] = true
			case "restored":
				delete(done, file.Source)
			}
		}
	}
	var result []*ImportBatchFile
	for _, file := range collectImportRecycle(batch, kind) {
		if !done[file.Path] {
			result = append(result, file)
		}
	}
	return result
}

func checkImportRecycleStep(batch *ImportBatch, kind string, leaveLocal bool) error {
	for _, file := range pendingImportRecycle(batch, kind) {
		if !leaveLocal {
			return fmt.Errorf("还有本地文件待回收")
		}
		err := verifyRecycleDigest(file.Path, file.SHA256)
		if err != nil {
			return fmt.Errorf("请先核对回收站或恢复原片: %w", err)
		}
	}
	return nil
}

func importRecycleDirectory(batch *ImportBatch, parent, kind string) (string, error) {
	suffix := "-reject"
	if kind == "imported" {
		suffix = "-keep"
	}
	name := batch.Name + suffix
	if !filepath.IsLocal(name) || filepath.Base(name) != name {
		return "", fmt.Errorf("批次名无法用作回收目录: %s", name)
	}
	for n := 0; ; n++ {
		dir := filepath.Join(parent, name)
		if n > 0 {
			dir = filepath.Join(parent, fmt.Sprintf("%s-%d%s", batch.Name, n, suffix))
		}
		used := false
		for _, group := range batch.Recycling {
			if strings.EqualFold(dir, group.Directory) {
				used = true
				break
			}
		}
		if used {
			continue
		}
		_, err := os.Lstat(dir)
		if os.IsNotExist(err) {
			return dir, nil
		}
		if err != nil {
			return "", err
		}
	}
}

func recycleRelativePath(parent, source string, used map[string]bool) string {
	rel, err := filepath.Rel(parent, source)
	if err != nil || !filepath.IsLocal(rel) {
		rel = filepath.Base(source)
	}
	next := rel
	ext := filepath.Ext(rel)
	stem := strings.TrimSuffix(rel, ext)
	for n := 1; used[strings.ToLower(next)]; n++ {
		next = fmt.Sprintf("%s-%d%s", stem, n, ext)
	}
	used[strings.ToLower(next)] = true
	return next
}

func (a *App) RecycleImportFiles(id, kind string, paths []string, parent string) (*ImportBatch, error) {
	a.batchMu.Lock()
	defer a.batchMu.Unlock()
	root := importBatchRoot()
	batch, err := loadImportBatch(root, id)
	if err != nil {
		return nil, err
	}
	if kind != "imported" && kind != "discarded" {
		return nil, fmt.Errorf("无效的清理类型")
	}
	if !filepath.IsAbs(parent) {
		return nil, fmt.Errorf("请确认要使用的归集位置")
	}
	parent = filepath.Clean(parent)
	parentInfo, err := os.Lstat(parent)
	if err != nil || !parentInfo.IsDir() {
		return nil, fmt.Errorf("归集位置不是可访问的目录: %s", parent)
	}
	if batch.Step != "" && (kind == "discarded" && batch.Step != "reject" ||
		kind == "imported" && batch.Step != "keep") {
		return nil, fmt.Errorf("请在对应的回收步骤操作")
	}
	batch.Name, err = importBatchName(root, batch)
	if err != nil {
		return nil, err
	}
	selected := make(map[string]bool)
	for _, path := range paths {
		selected[path] = true
	}
	eligible := collectImportRecycle(batch, kind)
	matched := 0
	for _, file := range eligible {
		if selected[file.Path] {
			matched++
		}
	}
	if matched != len(selected) {
		return nil, fmt.Errorf("清理清单已变化，请重新预览")
	}
	_, recycleErr := importRecycleVolume(parent)
	if recycleErr == nil {
		err = changeRecycleLocation(batch, kind, parent, selected, func() error { return saveImportBatch(root, batch) })
		if err != nil {
			return nil, err
		}
	}
	statusByPath := make(map[string]string)
	for _, group := range batch.Recycling {
		for _, item := range group.Files {
			if item.Status == "retained" && statusByPath[item.Source] != "" {
				continue
			}
			statusByPath[item.Source] = item.Status
		}
	}
	var unverified map[string]string
	if kind == "imported" {
		unverified = verifyArchivedImportForRecycle(batch)
	}
	var work *ImportRecycleGroup
	used := make(map[string]bool)
	for _, file := range eligible {
		if !selected[file.Path] {
			continue
		}
		if reason := unverified[file.Path]; reason != "" {
			delete(selected, file.Path)
			batch.Recycling = append(batch.Recycling, ImportRecycleGroup{
				Kind: kind, Status: "retained", Error: reason,
				Files: []ImportRecycleFile{{Source: file.Path, SHA256: file.SHA256, Status: "retained"}},
			})
			continue
		}
		status := statusByPath[file.Path]
		if status == "deleted" || status == "recycled" || status == "deleting" ||
			status == "pending" || status == "staged" {
			continue
		}
		if recycleErr != nil {
			group := &ImportRecycleGroup{Kind: kind, Status: "retained", Error: recycleErr.Error(),
				Files: []ImportRecycleFile{{Source: file.Path, SHA256: file.SHA256, Status: "retained"}}}
			batch.Recycling = append(batch.Recycling, *group)
			continue
		}
		if work == nil {
			dir, err := importRecycleDirectory(batch, parent, kind)
			if err != nil {
				return nil, err
			}
			work = &ImportRecycleGroup{Directory: dir, Kind: kind, Status: "pending"}
		}
		work.Files = append(work.Files, ImportRecycleFile{
			Source: file.Path, Relative: recycleRelativePath(parent, file.Path, used), SHA256: file.SHA256, Status: "pending",
		})
	}
	if work != nil {
		batch.Recycling = append(batch.Recycling, *work)
	}
	err = saveImportBatch(root, batch)
	if err != nil {
		return nil, err
	}
	for i := range batch.Recycling {
		group := &batch.Recycling[i]
		if group.Status == "recycled" || group.Status == "retained" || group.Status == "restored" || group.Status == "uncertain" ||
			group.Kind != kind || recycleErr != nil || !strings.EqualFold(filepath.Dir(group.Directory), parent) {
			continue
		}
		err = runImportRecycle(group, selected, func() error {
			return saveImportBatch(root, batch)
		})
		if err != nil {
			return nil, err
		}
	}
	return batch, nil
}

func changeRecycleLocation(batch *ImportBatch, kind, parent string, selected map[string]bool, save func() error) error {
	for i := range batch.Recycling {
		group := &batch.Recycling[i]
		if group.Kind != kind || group.Directory == "" ||
			(group.Status != "pending" && group.Status != "sending") ||
			strings.EqualFold(filepath.Dir(group.Directory), parent) {
			continue
		}
		remaining := make([]ImportRecycleFile, 0, len(group.Files))
		for j := range group.Files {
			file := group.Files[j]
			if !selected[file.Source] {
				remaining = append(remaining, file)
				continue
			}
			err := restoreImportRecycleFile(group.Directory, &file)
			if err == nil {
				err = verifyRecycleDigest(file.Source, file.SHA256)
			}
			if err != nil {
				group.Files[j] = file
				return errors.Join(fmt.Errorf("请先核对原片或 Windows 回收站后更改归集位置: %w", err), save())
			}
		}
		group.Files = remaining
		if len(remaining) == 0 {
			group.Status, group.Error = "restored", ""
		}
		err := save()
		if err != nil {
			return err
		}
	}
	return nil
}

func runImportRecycle(group *ImportRecycleGroup, selected map[string]bool, save func() error) error {
	if group.Status == "sending" {
		_, err := os.Lstat(group.Directory)
		if os.IsNotExist(err) {
			group.Status = "uncertain"
			group.Error = "归集目录已移走，请在 Windows 回收站核对该目录"
			return save()
		}
		if err != nil {
			return err
		}
	}
	group.Error = ""
	for i := range group.Files {
		item := &group.Files[i]
		if item.Status == "staged" || item.Status == "deleted" {
			continue
		}
		if !selected[item.Source] {
			continue
		}
		item.Error = ""
		dest := filepath.Join(group.Directory, item.Relative)
		err := stageImportRecycle(item.Source, dest, item.SHA256)
		if err == nil {
			item.Status = "staged"
		}
		if err != nil {
			item.Error = err.Error()
		}
		err = save()
		if err != nil {
			return err
		}
	}
	for _, item := range group.Files {
		if !selected[item.Source] || item.Status != "staged" {
			group.Status = "pending"
			return save()
		}
	}
	_, err := importRecycleVolume(group.Directory)
	if err == nil {
		err = verifyRecycleDirectory(group)
	}
	if err != nil {
		group.Error = err.Error()
		return save()
	}
	group.Status = "sending"
	err = save()
	if err != nil {
		return err
	}
	err = sendImportDirectoryToRecycleBin(group.Directory)
	if err != nil {
		group.Error = err.Error()
		_, statErr := os.Lstat(group.Directory)
		if statErr == nil {
			group.Status = "pending"
			for i := range group.Files {
				item := &group.Files[i]
				staged := filepath.Join(group.Directory, item.Relative)
				moveErr := restoreImportRecycleFile(group.Directory, item)
				if moveErr == nil {
					item.Status, item.Error = "pending", ""
					if item.RestoredTo == item.Source {
						item.RestoredTo = ""
					} else {
						item.Status = "restored"
					}
					continue
				}
				item.Error = fmt.Sprintf("归集文件保留于 %s: %v", staged, moveErr)
			}
		}
		return save()
	}
	group.Status = "recycled"
	for i := range group.Files {
		group.Files[i].Status = "recycled"
	}
	return save()
}

func verifyRecycleDigest(path, want string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() {
		return fmt.Errorf("路径不是普通文件: %s", path)
	}
	digest, err := importFileDigest(path)
	if err != nil {
		return err
	}
	if digest != want {
		return fmt.Errorf("文件摘要已变: %s", path)
	}
	return nil
}

func stageImportRecycle(source, dest, digest string) error {
	_, sourceErr := os.Lstat(source)
	if os.IsNotExist(sourceErr) {
		return verifyRecycleDigest(dest, digest)
	}
	if sourceErr != nil {
		return sourceErr
	}
	err := verifyRecycleDigest(source, digest)
	if err != nil {
		return err
	}
	sourceInfo, err := os.Lstat(source)
	if err != nil {
		return err
	}
	destInfo, err := os.Lstat(dest)
	if err == nil {
		if os.SameFile(sourceInfo, destInfo) {
			return os.Remove(source)
		}
		// On another volume the verified copy may have finished before the app
		// recorded or removed the original.
		err = verifyRecycleDigest(dest, digest)
		if err != nil {
			return err
		}
		return os.Remove(source)
	}
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	err = os.MkdirAll(filepath.Dir(dest), 0700)
	if err != nil {
		return err
	}
	return moveVerifiedRecycleFile(source, dest, digest)
}

func moveVerifiedRecycleFile(source, target, digest string) error {
	err := moveImportFile(source, target)
	if !isImportCrossVolume(err) {
		return err
	}
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	info, err := input.Stat()
	if err != nil {
		input.Close()
		return err
	}
	temp, err := os.CreateTemp(filepath.Dir(target), ".recycle-*.tmp")
	if err != nil {
		input.Close()
		return err
	}
	defer os.Remove(temp.Name())
	_, copyErr := io.Copy(temp, input)
	err = errors.Join(copyErr, temp.Sync(), temp.Close(), input.Close())
	if err != nil {
		return err
	}
	err = verifyRecycleDigest(temp.Name(), digest)
	if err != nil {
		return err
	}
	err = os.Chtimes(temp.Name(), info.ModTime(), info.ModTime())
	if err != nil {
		return err
	}
	err = moveImportFile(temp.Name(), target)
	if err != nil {
		return err
	}
	current, err := os.Lstat(source)
	if err != nil {
		return err
	}
	if !os.SameFile(info, current) || info.Size() != current.Size() || !info.ModTime().Equal(current.ModTime()) {
		return fmt.Errorf("复制期间原片发生变化: %s", source)
	}
	return os.Remove(source)
}

func verifyRecycleDirectory(group *ImportRecycleGroup) error {
	expected := make(map[string]bool)
	for _, item := range group.Files {
		if !filepath.IsLocal(item.Relative) {
			return fmt.Errorf("无效的归集文件路径: %s", item.Relative)
		}
		err := verifyRecycleDigest(filepath.Join(group.Directory, item.Relative), item.SHA256)
		if err != nil {
			return err
		}
		expected[filepath.Join(group.Directory, item.Relative)] = true
	}
	return filepath.WalkDir(group.Directory, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() || expected[path] ||
			(filepath.Base(filepath.Dir(group.Directory)) == ".photo-agent-recycle" && path == filepath.Join(group.Directory, "原路径与摘要.tsv")) {
			return nil
		}
		return fmt.Errorf("归集目录中有不在本批次清单的文件: %s", path)
	})
}

func restoreImportRecycleFile(directory string, file *ImportRecycleFile) error {
	staged := filepath.Join(directory, file.Relative)
	if file.RestoredTo != "" {
		return verifyRecycleDigest(file.RestoredTo, file.SHA256)
	}
	_, err := os.Lstat(staged)
	if os.IsNotExist(err) {
		return verifyRecycleDigest(file.Source, file.SHA256)
	}
	if err != nil {
		return err
	}
	err = verifyRecycleDigest(staged, file.SHA256)
	if err != nil {
		return err
	}
	err = os.MkdirAll(filepath.Dir(file.Source), 0700)
	if err != nil {
		return err
	}
	ext := filepath.Ext(file.Source)
	base := strings.TrimSuffix(file.Source, ext)
	for n := 0; n < 100; n++ {
		target := file.Source
		if n > 0 {
			target = fmt.Sprintf("%s-restored-%d%s", base, n, ext)
		}
		err = moveVerifiedRecycleFile(staged, target, file.SHA256)
		if errors.Is(err, os.ErrExist) {
			continue
		}
		if err == nil {
			file.RestoredTo = target
		}
		return err
	}
	return fmt.Errorf("恢复路径发生重名: %s", file.Source)
}

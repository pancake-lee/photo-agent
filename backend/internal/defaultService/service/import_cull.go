package service

import (
	"bufio"
	"bytes"
	"context"
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var cullExtractProgress = regexp.MustCompile(`^\s*(\d+)/(\d+)\s`)

func autocullCommand(executable string) (string, []string, string, error) {
	if executable == "" || !filepath.IsAbs(executable) {
		return "", nil, "", fmt.Errorf("请先配置服务器的 AutoCull.SourceDir")
	}
	path := filepath.Join(executable, ".venv", "bin", "python")
	if filepath.Separator == '\\' {
		path = filepath.Join(executable, ".venv", "Scripts", "python.exe")
	}
	if _, err := os.Stat(path); err != nil {
		return "", nil, "", fmt.Errorf("AutoCull 源码目录缺少 .venv 中的 Python: %w", err)
	}
	return path, []string{"-m", "autocull"}, executable, nil
}

func analyzeImportBatch(
	ctx context.Context, root string, pending []importCullInput, executable, scene string,
	progress func(importCullProgress),
) (map[string]*importCullScore, map[string]bool, error) {
	switch scene {
	case "auto", "concert", "portrait", "event", "wedding", "sports", "landscape", "generic":
	default:
		return nil, nil, fmt.Errorf("未知 AutoCull 场景")
	}
	path, prefix, commandDir, err := autocullCommand(executable)
	if err != nil {
		return nil, nil, fmt.Errorf("找不到 AutoCull 1.4.9: %w", err)
	}
	versionCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	versionCmd := exec.CommandContext(versionCtx, path, append(prefix, "--version")...)
	versionCmd.Dir = commandDir
	version, err := versionCmd.Output()
	if err != nil || strings.TrimSpace(string(version)) != "autocull 1.4.9" {
		return nil, nil, fmt.Errorf("需要 AutoCull 1.4.9 的公开 CLI，实际版本 %q: %v", version, err)
	}
	workspace, err := os.MkdirTemp(root, "cull-")
	if err != nil {
		return nil, nil, err
	}
	defer os.RemoveAll(workspace)

	manifest := make(map[string]importCullInput)
	failures := make(map[string]bool)
	scores := make(map[string]*importCullScore)
	total := len(pending)
	for i, entry := range pending {
		if err = ctx.Err(); err != nil {
			return nil, nil, err
		}
		// An ordinal prefix keeps same-name files distinct and preserves
		// source order when AutoCull uses filename order as a fallback.
		name := fmt.Sprintf("%07d_%s.jpg", i, entry.ID)
		source := filepath.Join(root, entry.SHA256+".jpg")
		err = copyCullInput(source, filepath.Join(workspace, name), entry.SHA256)
		if err != nil {
			failures[entry.ID] = true
		} else {
			manifest[name] = entry
		}
		progress(importCullProgress{Done: len(scores), Total: total, Failed: len(failures),
			Message: fmt.Sprintf("准备待审副本 %d/%d", i+1, len(pending))})
	}
	if len(manifest) == 0 {
		progress(importCullProgress{Done: len(scores), Total: total, Failed: len(failures),
			Message: "初筛完成"})
		return scores, failures, nil
	}
	picks := filepath.Join(workspace, "picks.csv")
	err = os.WriteFile(picks, []byte("filename\n"), 0600)
	if err != nil {
		return nil, nil, err
	}
	args := append(prefix, "run", workspace, "--scene", scene, "--picks", picks, "--face-engine", "yunet")
	cmd := exec.CommandContext(ctx, path, args...)
	cmd.Dir = commandDir
	if cmd.Dir == "" {
		cmd.Dir = workspace
	}
	cmd.WaitDelay = 3 * time.Second
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "PYTHONUNBUFFERED=1")
	var output string
	reader, writer := io.Pipe()
	cmd.Stdout, cmd.Stderr = writer, writer
	drained := make(chan struct{})
	go func() {
		defer close(drained)
		scanner := bufio.NewScanner(reader)
		scanner.Buffer(make([]byte, 4096), 1<<20)
		done, failed := len(scores), len(failures)
		for scanner.Scan() {
			output = scanner.Text()
			if match := cullExtractProgress.FindStringSubmatch(output); len(match) == 3 {
				count, _ := strconv.Atoi(match[1])
				done = len(scores) + min(count, len(manifest))
			}
			if strings.HasPrefix(strings.TrimSpace(output), "ERR ") {
				failed++
			}
			progress(importCullProgress{Done: done, Total: total, Failed: failed, Message: output})
		}
		_ = reader.Close()
	}()
	err = runCullCommand(cmd)
	_ = writer.Close()
	<-drained
	if ctx.Err() != nil {
		return nil, nil, ctx.Err()
	}
	if err != nil {
		return nil, nil, fmt.Errorf("AutoCull 分析失败: %w (%s)", err, output)
	}
	result, err := readCullScores(
		filepath.Join(workspace, "_cull_out", "autocull", "tiers.csv"), manifest, scene,
	)
	if err != nil {
		return nil, nil, err
	}
	for _, entry := range manifest {
		if result[entry.ID] == nil {
			failures[entry.ID] = true
		} else {
			scores[entry.ID] = result[entry.ID]
		}
	}
	progress(importCullProgress{Done: len(scores), Total: total, Failed: len(failures),
		Message: "初筛完成"})
	return scores, failures, nil
}

func copyCullInput(source, target, digest string) error {
	info, err := os.Lstat(source)
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() {
		return fmt.Errorf("暂存 JPG 不是普通文件")
	}
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer input.Close()
	return writeVerifiedArchiveFile(filepath.Dir(target), filepath.Base(target),
		digest, info.ModTime(), input, nil)
}

func readCullScores(
	path string, manifest map[string]importCullInput, scene string,
) (map[string]*importCullScore, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取 AutoCull tiers.csv: %w", err)
	}
	reader := csv.NewReader(bytes.NewReader(bytes.TrimPrefix(raw, []byte{0xef, 0xbb, 0xbf})))
	header, err := reader.Read()
	if err != nil {
		return nil, err
	}
	fields := make(map[string]int)
	for i, field := range header {
		fields[field] = i
	}
	for _, key := range []string{"filename", "tier", "rating", "rank", "why", "cluster"} {
		if _, ok := fields[key]; !ok {
			return nil, fmt.Errorf("AutoCull tiers.csv 缺少 %s 列", key)
		}
	}
	result := make(map[string]*importCullScore)
	duplicates := make(map[string]bool)
	for {
		row, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		entry, exists := manifest[row[fields["filename"]]]
		if !exists {
			return nil, fmt.Errorf("AutoCull 结果引用未知副本 %q", row[fields["filename"]])
		}
		if result[entry.ID] != nil || duplicates[entry.ID] {
			duplicates[entry.ID] = true
			delete(result, entry.ID)
			continue
		}
		rank, rankErr := strconv.Atoi(row[fields["rank"]])
		rating, ratingErr := strconv.Atoi(row[fields["rating"]])
		if rankErr != nil || ratingErr != nil || rating < 0 || rating > 5 {
			duplicates[entry.ID] = true
			continue
		}
		result[entry.ID] = &importCullScore{
			Tier: row[fields["tier"]], Rank: rank, Rating: rating,
			Why: row[fields["why"]], Cluster: row[fields["cluster"]],
			Scene: scene, SHA256: entry.SHA256,
		}
	}
	return result, nil
}

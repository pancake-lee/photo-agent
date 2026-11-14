package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/wailsapp/wails/v2/pkg/runtime"
)

type ImportCullScore struct {
	Tier     string `json:"tier"`
	Rating   int    `json:"rating"`
	Rank     int    `json:"rank"`
	Why      string `json:"why"`
	Cluster  string `json:"cluster"`
	InputKey string `json:"input_key,omitempty"`
	Scene    string `json:"scene"`
	SHA256   string `json:"sha256"`
}

type ImportCullProgress struct {
	BatchID string `json:"batch_id"`
	Done    int    `json:"done"`
	Total   int    `json:"total"`
	Failed  int    `json:"failed"`
	Message string `json:"message"`
}

var cullExtractProgress = regexp.MustCompile(`^\s*(\d+)/(\d+)\s`)

func (a *App) CancelImportCull() {
	a.cullMu.Lock()
	defer a.cullMu.Unlock()
	if a.cancelCull != nil {
		a.cancelCull()
	}
}

func (a *App) ClearImportCull(id string) (*ImportBatch, error) {
	return a.editImportBatch(id, func(batch *ImportBatch) error {
		for i := range batch.Entries {
			batch.Entries[i].Score = nil
		}
		return nil
	})
}

func (a *App) AnalyzeImportBatch(id, executable, scene string) (*ImportBatch, error) {
	a.cullMu.Lock()
	if a.cancelCull != nil {
		a.cullMu.Unlock()
		return nil, fmt.Errorf("已有初筛正在运行")
	}
	ctx, cancel := context.WithCancel(context.Background())
	a.cancelCull = cancel
	a.cullMu.Unlock()
	defer func() {
		cancel()
		a.cullMu.Lock()
		a.cancelCull = nil
		a.cullMu.Unlock()
	}()

	batch, err := a.GetImportBatch(id)
	if err != nil {
		return nil, err
	}
	progress := func(p ImportCullProgress) {
		p.BatchID = id
		if a.ctx != nil {
			runtime.EventsEmit(a.ctx, "import:cull", p)
		}
	}
	base := filepath.Dir(importBatchPath(importBatchRoot(), id))
	scores, failures, err := analyzeImportBatch(ctx, base, batch, executable, scene, progress)
	if err != nil {
		return nil, err
	}
	return a.editImportBatch(id, func(latest *ImportBatch) error {
		for i := range latest.Entries {
			entry := &latest.Entries[i]
			score := scores[entry.ID]
			if score != nil && entry.JPG != nil && entry.JPG.SHA256 == score.SHA256 {
				entry.Score = score
			} else if failures[entry.ID] && entry.JPG != nil {
				entry.Score = nil
			}
		}
		return nil
	})
}

func autocullCommand(executable string) (string, []string, string, error) {
	if executable == "" {
		executable = "autocull"
	}
	if filepath.IsAbs(executable) {
		info, err := os.Stat(executable)
		if err != nil {
			return "", nil, "", err
		}
		if info.IsDir() {
			path := filepath.Join(executable, ".venv", "bin", "python")
			if filepath.Separator == '\\' {
				path = filepath.Join(executable, ".venv", "Scripts", "python.exe")
			}
			if _, err = os.Stat(path); err != nil {
				return "", nil, "", fmt.Errorf("AutoCull 源码目录缺少 .venv 中的 Python: %w", err)
			}
			return path, []string{"-m", "autocull"}, executable, nil
		}
	} else if filepath.Base(executable) != executable {
		return "", nil, "", fmt.Errorf("请填写 AutoCull 源码目录或公开 CLI 的绝对路径")
	}
	path, err := exec.LookPath(executable)
	return path, nil, "", err
}

func analyzeImportBatch(
	ctx context.Context, root string, batch *ImportBatch, executable, scene string,
	progress func(ImportCullProgress),
) (map[string]*ImportCullScore, map[string]bool, error) {
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
	// A process interrupted by a desktop restart can leave analysis copies.
	// The single active analysis job owns these temporary directories.
	dirs, err := os.ReadDir(root)
	if err != nil {
		return nil, nil, err
	}
	for _, dir := range dirs {
		if dir.IsDir() && strings.HasPrefix(dir.Name(), "cull-") {
			err = os.RemoveAll(filepath.Join(root, dir.Name()))
			if err != nil {
				return nil, nil, err
			}
		}
	}
	workspace, err := os.MkdirTemp(root, "cull-")
	if err != nil {
		return nil, nil, err
	}
	defer os.RemoveAll(workspace)

	manifest := make(map[string]ImportBatchEntry)
	failures := make(map[string]bool)
	scores := make(map[string]*ImportCullScore)
	var pending []ImportBatchEntry
	for _, entry := range batch.Entries {
		if entry.Historical || entry.JPG == nil || entry.Decision != batchPending || entry.ReferenceOnly ||
			entry.Conflict || entry.Pair == "review" {
			continue
		}
		pending = append(pending, entry)
	}
	sort.Slice(pending, func(i, j int) bool {
		return pending[i].JPG.Path < pending[j].JPG.Path
	})
	total := len(pending)
	inputs := sha256.New()
	for _, entry := range pending {
		fmt.Fprintln(inputs, entry.ID, entry.JPG.SHA256)
	}
	inputKey := hex.EncodeToString(inputs.Sum(nil))
	for _, entry := range pending {
		if entry.Score != nil && entry.Score.SHA256 == entry.JPG.SHA256 &&
			entry.Score.Scene == scene && entry.Score.InputKey == inputKey {
			digest, digestErr := importFileDigest(entry.JPG.Path)
			if digestErr == nil && digest == entry.JPG.SHA256 {
				scores[entry.ID] = entry.Score
			}
		}
	}
	if len(scores) == total {
		progress(ImportCullProgress{Done: total, Total: total, Message: "初筛完成"})
		return scores, failures, nil
	}
	clear(scores)
	for i, entry := range pending {
		if err = ctx.Err(); err != nil {
			return nil, nil, err
		}
		// An ordinal prefix keeps same-name files distinct and preserves
		// source order when AutoCull uses filename order as a fallback.
		name := fmt.Sprintf("%07d_%s.jpg", i, entry.ID)
		err = copyCullInput(entry.JPG, filepath.Join(workspace, name))
		if err != nil {
			failures[entry.ID] = true
		} else {
			manifest[name] = entry
		}
		progress(ImportCullProgress{Done: len(scores), Total: total, Failed: len(failures),
			Message: fmt.Sprintf("准备待审副本 %d/%d", i+1, len(pending))})
	}
	if len(manifest) == 0 {
		progress(ImportCullProgress{Done: len(scores), Total: total, Failed: len(failures),
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
			progress(ImportCullProgress{Done: done, Total: total, Failed: failed, Message: output})
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
			result[entry.ID].InputKey = inputKey
			scores[entry.ID] = result[entry.ID]
		}
	}
	progress(ImportCullProgress{Done: len(scores), Total: total, Failed: len(failures),
		Message: "初筛完成"})
	return scores, failures, nil
}

func copyCullInput(source *ImportBatchFile, path string) error {
	err := copyFile(source.Path, path)
	if err != nil {
		_ = os.Remove(path)
		return err
	}
	digest, err := importFileDigest(path)
	if err != nil || digest != source.SHA256 {
		_ = os.Remove(path)
		return fmt.Errorf("文件与扫描时不一致: %s", source.Path)
	}
	return nil
}

func importFileDigest(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	digest := sha256.New()
	_, err = io.Copy(digest, file)
	return hex.EncodeToString(digest.Sum(nil)), err
}

func readCullScores(
	path string, manifest map[string]ImportBatchEntry, scene string,
) (map[string]*ImportCullScore, error) {
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
	result := make(map[string]*ImportCullScore)
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
		result[entry.ID] = &ImportCullScore{
			Tier: row[fields["tier"]], Rank: rank, Rating: rating,
			Why: row[fields["why"]], Cluster: row[fields["cluster"]],
			Scene: scene, SHA256: entry.JPG.SHA256,
		}
	}
	return result, nil
}

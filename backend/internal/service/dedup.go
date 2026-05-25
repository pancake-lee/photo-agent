package service

import (
	"crypto/md5"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"

	"github.com/pancake-lee/pgo/pkg/plogger"
)

// DedupRegistry MD5 去重注册表，按 base_url 持久化到 JSON 文件。
// key 为文件 MD5（hex），value 为首次出现的 relPath。
type DedupRegistry struct {
	mu       sync.Mutex
	path     string
	hashes   map[string]string // md5 → relPath (首次遇到的文件路径)
	modified bool
}

// hashEntry JSON 文件中的一条记录
type hashEntry struct {
	MD5     string `json:"md5"`
	RelPath string `json:"rel_path"`
}

// LoadDedupRegistry 加载 MD5 注册表文件，不存在则返回空注册表。
func LoadDedupRegistry(filePath string) *DedupRegistry {
	r := &DedupRegistry{
		path:   filePath,
		hashes: make(map[string]string),
	}

	data, err := os.ReadFile(filePath)
	if err != nil {
		if !os.IsNotExist(err) {
			plogger.Warnf("DedupRegistry load failed: %v", err)
		}
		return r
	}

	entries := make(map[string]string)
	if err := json.Unmarshal(data, &entries); err != nil {
		// 兼容旧格式：数组
		var legacy []hashEntry
		if err2 := json.Unmarshal(data, &legacy); err2 != nil {
			plogger.Warnf("DedupRegistry parse failed: %v", err)
			return r
		}
		for _, e := range legacy {
			entries[e.MD5] = e.RelPath
		}
	}

	r.hashes = entries
	plogger.Infof("DedupRegistry loaded: %d hashes from %s", len(r.hashes), filepath.Base(filePath))
	return r
}

// Exists 检查 MD5 是否已注册，返回首次出现路径。
func (r *DedupRegistry) Exists(md5sum string) (relPath string, found bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	p, ok := r.hashes[md5sum]
	return p, ok
}

// Register 注册一个 MD5 → relPath 映射。
func (r *DedupRegistry) Register(md5sum, relPath string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.hashes[md5sum]; exists {
		return
	}
	r.hashes[md5sum] = relPath
	r.modified = true
}

// Save 持久化注册表（仅在有变更时写入）。
func (r *DedupRegistry) Save() error {
	r.mu.Lock()
	defer r.mu.Unlock()

	if !r.modified {
		return nil
	}

	dir := filepath.Dir(r.path)
	if dir != "" && dir != "." {
		_ = os.MkdirAll(dir, 0755)
	}

	data, err := json.MarshalIndent(r.hashes, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal dedup registry: %w", err)
	}

	tmpPath := r.path + ".tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil {
		return fmt.Errorf("write dedup registry: %w", err)
	}

	if err := os.Rename(tmpPath, r.path); err != nil {
		return fmt.Errorf("rename dedup registry: %w", err)
	}

	r.modified = false
	plogger.Infof("DedupRegistry saved: %d hashes", len(r.hashes))
	return nil
}

// Count 返回当前注册的哈希数。
func (r *DedupRegistry) Count() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.hashes)
}

// ComputeFileMD5 计算文件的 MD5 哈希（hex 字符串）。
func ComputeFileMD5(filePath string) (string, error) {
	f, err := os.Open(filePath)
	if err != nil {
		return "", fmt.Errorf("open file: %w", err)
	}
	defer f.Close()

	h := md5.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", fmt.Errorf("hash file: %w", err)
	}

	return fmt.Sprintf("%x", h.Sum(nil)), nil
}

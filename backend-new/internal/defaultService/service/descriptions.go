package service

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/pancake-lee/pgo/pkg/plogger"
)

// descriptionEntry 预描述文件中的单条记录
type descriptionEntry struct {
	Description string `json:"description"`
	Model       string `json:"model"`
	ProcessedAt string `json:"processed_at"`
	ShotAt      string `json:"shot_at"`
}

// descriptionMap 预描述数据
type descriptionMap map[string]descriptionEntry

var descCache descriptionMap

// loadDescriptions 加载预描述文件
func loadDescriptions(path string) (descriptionMap, error) {
	if descCache != nil {
		return descCache, nil
	}

	if path == "" {
		return nil, nil
	}

	if _, err := os.Stat(path); os.IsNotExist(err) {
		plogger.Infof("Descriptions file not found: %s", path)
		return nil, nil
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read descriptions file failed: %w", err)
	}

	var m descriptionMap
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("unmarshal descriptions failed: %w", err)
	}

	descCache = m
	plogger.Infof("Loaded %d pre-generated descriptions", len(m))
	return m, nil
}

// getDescriptionEntry 从预描述文件中查找完整记录
func getDescriptionEntry(relPath string, descPath string) (descriptionEntry, bool) {
	m, err := loadDescriptions(descPath)
	if err != nil || m == nil {
		return descriptionEntry{}, false
	}

	keys := []string{
		relPath,
		filepath.ToSlash(relPath),
		filepath.FromSlash(relPath),
	}

	for _, k := range keys {
		if entry, ok := m[k]; ok {
			return entry, true
		}
	}

	// 扩展名模糊匹配（原始 RAW 压缩为 jpg 后扩展名变化）
	baseNoExt := strings.TrimSuffix(relPath, filepath.Ext(relPath))
	for k, entry := range m {
		keyNoExt := strings.TrimSuffix(k, filepath.Ext(k))
		if keyNoExt == baseNoExt || keyNoExt == filepath.ToSlash(baseNoExt) {
			return entry, true
		}
	}

	// 文件名匹配（json key 与 photo_path relPath 目录层级不一致时 fallback）
	baseName := strings.ToLower(filepath.Base(relPath))
	for k, entry := range m {
		if strings.ToLower(filepath.Base(k)) == baseName {
			return entry, true
		}
	}

	return descriptionEntry{}, false
}

// ClearDescCache 清除预描述缓存（用于重载）
func ClearDescCache() {
	descCache = nil
}

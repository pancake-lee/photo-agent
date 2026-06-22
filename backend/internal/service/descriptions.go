package service

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

// DescriptionEntry 预描述文件中的单条记录
type DescriptionEntry struct {
	Description string `json:"description"`
	Model       string `json:"model"`
	ProcessedAt string `json:"processed_at"`
	ShotAt      string `json:"shot_at"` // EXIF 拍摄时间，RFC3339 格式
}

// DescriptionMap 预描述数据
type DescriptionMap map[string]DescriptionEntry

var descCache DescriptionMap

// LoadDescriptions 加载预描述文件
func LoadDescriptions() (DescriptionMap, error) {
	if descCache != nil {
		return descCache, nil
	}

	cfg := config.Get()
	path := cfg.ResolvePath(cfg.Storage.DescriptionsPath)
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

	var m DescriptionMap
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("unmarshal descriptions failed: %w", err)
	}

	descCache = m
	plogger.Infof("Loaded %d pre-generated descriptions", len(m))
	return m, nil
}

// GetPreDescription 从预描述文件中查找描述
func GetPreDescription(relPath string) (string, bool) {
	entry, ok := GetDescriptionEntry(relPath)
	return entry.Description, ok
}

// GetDescriptionEntry 从预描述文件中查找完整记录（含描述、拍摄时间等）
func GetDescriptionEntry(relPath string) (DescriptionEntry, bool) {
	m, err := LoadDescriptions()
	if err != nil || m == nil {
		return DescriptionEntry{}, false
	}

	// 尝试多种路径匹配方式
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
	// 例如 json key = "DSC_0009.JPG"，relPath = "proto-agent/DSC_0009.jpg"
	baseName := strings.ToLower(filepath.Base(relPath))
	for k, entry := range m {
		if strings.ToLower(filepath.Base(k)) == baseName {
			return entry, true
		}
	}

	return DescriptionEntry{}, false
}

// ClearDescCache 清除预描述缓存（用于重载）
func ClearDescCache() {
	descCache = nil
}

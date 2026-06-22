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

// vlmStructuredOutput VLM 结构化描述输出的 JSON 结构。
// description 字段内嵌的 ```json ... ``` 块即为此格式。
type vlmStructuredOutput struct {
	Subject struct {
		MainObjects []string `json:"main_objects"`
	} `json:"subject"`
	Scene struct {
		Environment string `json:"environment"`
		Setting     string `json:"setting"`
		TimeOfDay   string `json:"time_of_day"`
	} `json:"scene"`
	Lighting struct {
		Source     string `json:"source"`
		Brightness string `json:"brightness"`
		Contrast   string `json:"contrast"`
	} `json:"lighting"`
	ColorPalette struct {
		DominantColors []string `json:"dominant_colors"`
		OverallTone    string   `json:"overall_tone"`
	} `json:"color_palette"`
	Composition struct {
		Focus   string `json:"focus"`
		Depth   string `json:"depth"`
		Symmetry string `json:"symmetry"`
	} `json:"composition"`
	Mood string `json:"mood"`
}

// ParseStructuredAttributes 从 VLM 描述中解析结构化属性标签。
// VLM 输出的 description 字段是 markdown 包裹的 JSON（```json ... ```），
// 此函数提取 JSON 并将嵌套结构映射为扁平标签字符串，与 Chroma metadata 的
// scene/lighting/mood 允许值对齐。
//
// 返回 6 个维度的标签字符串，JSON 解析失败时静默返回空字符串。
func ParseStructuredAttributes(description string) (objects, colors, scene, lighting, mood, composition string) {
	if description == "" {
		return
	}

	// 提取 JSON 块（去掉 ```json ... ``` 包裹）
	jsonStr := description
	if idx := strings.Index(jsonStr, "```json"); idx >= 0 {
		jsonStr = jsonStr[idx+7:] // skip ```json\n
		if endIdx := strings.LastIndex(jsonStr, "```"); endIdx >= 0 {
			jsonStr = jsonStr[:endIdx]
		}
		jsonStr = strings.TrimSpace(jsonStr)
	}

	// 尝试直接作为 JSON 解析（兼容无 markdown 包裹的纯 JSON）
	var out vlmStructuredOutput
	if err := json.Unmarshal([]byte(jsonStr), &out); err != nil {
		// 尝试用正则提取 JSON 对象
		re := regexp.MustCompile(`\{[^{}]*"subject"[^}]*\}`)
		if match := re.FindString(description); match != "" {
			if err2 := json.Unmarshal([]byte(match), &out); err2 != nil {
				return
			}
		} else {
			return
		}
	}

	// objects: 主体物体列表
	objects = strings.Join(out.Subject.MainObjects, ",")

	// colors: 主色调
	colors = strings.Join(out.ColorPalette.DominantColors, ",")

	// scene: 映射到允许值
	scene = mapScene(out.Scene.Environment, out.Scene.Setting, out.Scene.TimeOfDay)

	// lighting: 映射到允许值
	lighting = mapLighting(out.Lighting.Brightness, out.Lighting.Source, out.Lighting.Contrast)

	// mood: 映射到允许值
	mood = mapMood(out.Mood)

	// composition: 组合构图特征
	var compParts []string
	if out.Composition.Focus != "" {
		compParts = append(compParts, out.Composition.Focus)
	}
	if out.Composition.Depth != "" {
		compParts = append(compParts, out.Composition.Depth)
	}
	if out.Composition.Symmetry != "" {
		compParts = append(compParts, out.Composition.Symmetry)
	}
	composition = strings.Join(compParts, ",")

	return
}

// mapScene 将 VLM 的中文场景描述映射到 Chroma metadata 允许值。
func mapScene(environment, setting, timeOfDay string) string {
	env := strings.TrimSpace(environment)
	set := strings.TrimSpace(setting)
	tod := strings.TrimSpace(timeOfDay)

	// 室内/室外优先
	if strings.Contains(env, "室内") {
		return "indoor"
	}

	// 根据时间段
	if strings.Contains(tod, "夜") || strings.Contains(tod, "晚") {
		return "night"
	}

	// 根据场景描述
	combined := set + tod
	if strings.Contains(combined, "街") || strings.Contains(combined, "城市") {
		return "street"
	}
	if strings.Contains(combined, "山") || strings.Contains(combined, "峰") {
		return "mountain"
	}
	if strings.Contains(combined, "水") || strings.Contains(combined, "河") ||
		strings.Contains(combined, "湖") || strings.Contains(combined, "海") ||
		strings.Contains(combined, "溪") {
		return "water"
	}
	if strings.Contains(combined, "自然") || strings.Contains(combined, "森林") ||
		strings.Contains(combined, "树") || strings.Contains(combined, "公园") ||
		strings.Contains(combined, "田") || strings.Contains(combined, "草") {
		return "nature"
	}
	if strings.Contains(combined, "城市") || strings.Contains(combined, "建筑") ||
		strings.Contains(combined, "楼") {
		return "urban"
	}

	// 室外通用
	if strings.Contains(env, "室外") || strings.Contains(env, "户外") {
		return "outdoor"
	}

	return ""
}

// mapLighting 将 VLM 的光线描述映射到 Chroma metadata 允许值。
func mapLighting(brightness, source, contrast string) string {
	b := strings.TrimSpace(brightness)
	s := strings.TrimSpace(source)
	c := strings.TrimSpace(contrast)

	// 暗光
	if strings.Contains(b, "暗") || strings.Contains(b, "弱") || strings.Contains(b, "低") {
		return "dim"
	}

	// 高对比/强烈
	if strings.Contains(c, "高对比") || strings.Contains(c, "强") {
		return "harsh"
	}

	// 人工光源
	if strings.Contains(s, "人工") || strings.Contains(s, "闪光") || strings.Contains(s, "灯") {
		return "artificial"
	}

	// 背光
	if strings.Contains(s, "背光") || strings.Contains(s, "逆光") {
		return "backlit"
	}

	// 柔和
	if strings.Contains(b, "柔和") || strings.Contains(b, "中等") || strings.Contains(b, "适中") {
		return "soft"
	}

	// 明亮
	if strings.Contains(b, "亮") || strings.Contains(b, "强") || strings.Contains(b, "充足") {
		return "bright"
	}

	return ""
}

// mapMood 将 VLM 的情绪描述映射到 Chroma metadata 允许值。
func mapMood(mood string) string {
	m := strings.TrimSpace(mood)

	switch {
	case strings.Contains(m, "温暖") || strings.Contains(m, "温馨"):
		return "warm"
	case strings.Contains(m, "平静") || strings.Contains(m, "宁静") || strings.Contains(m, "安静") || strings.Contains(m, "安详"):
		return "calm"
	case strings.Contains(m, "戏剧") || strings.Contains(m, "强烈") || strings.Contains(m, "震撼"):
		return "dramatic"
	case strings.Contains(m, "忧郁") || strings.Contains(m, "悲伤") || strings.Contains(m, "伤感"):
		return "melancholy"
	case strings.Contains(m, "愉悦") || strings.Contains(m, "快乐") || strings.Contains(m, "开心") || strings.Contains(m, "轻松") || strings.Contains(m, "欢快"):
		return "joyful"
	case strings.Contains(m, "严肃") || strings.Contains(m, "庄重") || strings.Contains(m, "沉重"):
		return "serious"
	case strings.Contains(m, "神秘") || strings.Contains(m, "迷幻") || strings.Contains(m, "朦胧"):
		return "mysterious"
	default:
		return ""
	}
}

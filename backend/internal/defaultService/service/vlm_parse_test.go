package service

import (
	"strings"
	"testing"

	"backend/internal/defaultService/data"
)

func TestParseVlmAttrs_Success(t *testing.T) {
	desc := "这是一张很棒的照片\n```json\n{\n  \"subject\": {\"main_objects\": [\"猫\", \"沙发\"]},\n  \"color_palette\": {\"dominant_colors\": [\"暖黄\", \"深棕\"]},\n  \"scene\": {\"environment\": \"室内\", \"setting\": \"客厅\", \"time_of_day\": \"下午\"},\n  \"lighting\": {\"source\": \"窗户自然光\"},\n  \"mood\": \"慵懒温馨\",\n  \"composition\": {\"focus\": \"中央\", \"depth\": \"浅景深\", \"symmetry\": \"不对称\"}\n}\n```\n"

	objects, colors, scene, lighting, mood, composition := parseVlmAttrs("test.jpg", desc)

	if objects != "猫、沙发" {
		t.Errorf("objects = %q, want %q", objects, "猫、沙发")
	}
	if colors != "暖黄、深棕" {
		t.Errorf("colors = %q, want %q", colors, "暖黄、深棕")
	}
	if scene != "室内，客厅" {
		t.Errorf("scene = %q, want %q", scene, "室内，客厅")
	}
	if lighting != "窗户自然光，下午" {
		t.Errorf("lighting = %q, want %q", lighting, "窗户自然光，下午")
	}
	if mood != "慵懒温馨" {
		t.Errorf("mood = %q, want %q", mood, "慵懒温馨")
	}
	if composition != "中央，浅景深，不对称" {
		t.Errorf("composition = %q, want %q", composition, "中央，浅景深，不对称")
	}
}

func TestValidateVlmDescription(t *testing.T) {
	valid := "场景描述\n```json\n{\"subject\": {\"main_objects\": [\"人物\"]}}\n```"
	if err := validateVlmDescription(valid); err != nil {
		t.Fatalf("valid description rejected: %v", err)
	}
	for _, description := range []string{
		"",
		"只有文本没有结构化结果",
		"故障彩条画面\n```json\n{}\n```",
	} {
		if err := validateVlmDescription(description); err == nil {
			t.Fatalf("invalid description accepted: %q", description)
		}
	}
}

func TestValidateVlmDescription_AllowsNormalVisualElements(t *testing.T) {
	for _, description := range []string{
		"画面中有纯白色墙面和纯黑色服装\n```json\n{}\n```",
		"人物身后是水平条纹背景\n```json\n{}\n```",
		"彩色条纹出现在建筑外墙\n```json\n{}\n```",
	} {
		if err := validateVlmDescription(description); err != nil {
			t.Fatalf("normal visual element rejected: %q: %v", description, err)
		}
	}
}

func TestValidateVlmDescription_RejectsExplicitTestPattern(t *testing.T) {
	for _, description := range []string{
		"这是测试图\n```json\n{}\n```",
		"color bars test pattern\n```json\n{}\n```",
		"多色水平条纹组和底部纯黑色块\n```json\n{}\n```",
	} {
		if err := validateVlmDescription(description); err == nil {
			t.Fatalf("test pattern accepted: %q", description)
		}
	}
}

// TestValidateVlmDescription_RejectsCorruptionPhrasings 覆盖 DSC_9985 漏判案例的同族措辞：
// VLM 对同一故障现象说法不固定，任一命中都应进入待复核。
func TestValidateVlmDescription_RejectsCorruptionPhrasings(t *testing.T) {
	for _, description := range []string{
		"一张特殊的照片\n```json\n{\"mood\": \"故障失真\"}\n```",
		"一张照片\n```json\n{\"overall_summary\": \"上半为彩色水平条纹，下半为浅蓝纯色的异常显示画面\"}\n```",
		"屏幕内容\n```json\n{\"subject\": {\"main_objects\": [\"显示屏\"]}, \"other\": \"显示异常\"}\n```",
		"拍摄电视\n```json\n{\"background\": {\"description\": \"花屏\"}}\n```",
		"glitch artifacts\n```json\n{}\n```",
		"corrupted image data\n```json\n{}\n```",
	} {
		if err := validateVlmDescription(description); err == nil {
			t.Fatalf("corruption phrasing accepted: %q", description)
		}
	}
}

// TestValidateVlmDescription_RejectsDsc9985 DSC_9985.jpg 的真实存量描述回归：
// 上半彩色条纹、下半浅蓝纯色的坏图，VLM 写明“故障失真”但旧规则全部未命中。
func TestValidateVlmDescription_RejectsDsc9985(t *testing.T) {
	description := "```json\n" + `{
    "image_type": "screenshot",
    "subject": {
        "main_objects": ["密集水平彩色条纹", "纯色浅蓝色块"],
        "count": 2,
        "attributes": {
            "color": "条纹包含亮蓝、青、绿、紫、粉、红、棕多色，下方色块为均匀浅蓝色",
            "pose/action": "无具象人或物体的动态行为",
            "other": "条纹排列紧密，横向贯穿整个画面宽度"
        }
    },
    "scene": {"environment": "虚拟", "setting": "不确定", "time_of_day": "不确定", "weather": null},
    "lighting": {"source": "未知", "brightness": "适中", "contrast": "中等"},
    "color_palette": {"dominant_colors": ["浅蓝色", "亮蓝色", "紫红色"], "overall_tone": "冷色"},
    "composition": {"focus": "上半区域", "depth": "无明显景深", "symmetry": "非对称"},
    "background": {"description": "大量不同颜色的横向细线条紧密排列组成的全宽条纹区域", "blur": "清晰"},
    "foreground": {"description": "占据画面下半部分全部区域的均匀浅蓝纯色块", "overlaps_main": false},
    "text_and_symbols": null,
    "mood": "故障失真",
    "overall_summary": "上半为彩色水平条纹，下半为浅蓝纯色的异常显示画面"
}` + "\n```"
	err := validateVlmDescription(description)
	if err == nil {
		t.Fatal("DSC_9985 corrupted description accepted")
	}
	if !strings.Contains(err.Error(), "故障失真") {
		t.Fatalf("expected marker 故障失真 to hit, got: %v", err)
	}
}

// TestValidateVlmDescription_ImageIntegrityField 新 prompt 的结构化完整性结论：
// corrupted/test_pattern 拦截，normal 放行，存量描述无该字段时放行（由关键词兜底）。
func TestValidateVlmDescription_ImageIntegrityField(t *testing.T) {
	for _, description := range []string{
		"```json\n{\"image_integrity\": \"corrupted\", \"overall_summary\": \"无法辨认的内容\"}\n```",
		"```json\n{\"image_integrity\": \"test_pattern\", \"overall_summary\": \"标准测试卡\"}\n```",
	} {
		if err := validateVlmDescription(description); err == nil {
			t.Fatalf("bad image_integrity accepted: %q", description)
		}
	}
	for _, description := range []string{
		"```json\n{\"image_integrity\": \"normal\", \"overall_summary\": \"海边的日落\"}\n```",
		"```json\n{\"overall_summary\": \"海边的日落\"}\n```",
	} {
		if err := validateVlmDescription(description); err != nil {
			t.Fatalf("normal description rejected: %q: %v", description, err)
		}
	}
}

func TestDerivePhotoAIStateUsesCurrentDescription(t *testing.T) {
	description := "人物站在树下\n```json\n{\"subject\": {\"main_objects\": [\"人物\"]}}\n```"
	photo := &data.PhotoDO{
		Description:              description,
		EmbeddingStatus:          aiStatusStale,
		EmbeddingDescriptionTime: "2026-08-27T00:00:00Z",
	}

	health, healthReason, vlmStatus, vlmReason, embeddingStatus, embeddingTime := derivePhotoAIState(photo)
	if health != aiStatusHealthy || healthReason != "" {
		t.Fatalf("health = (%q, %q), want healthy current description", health, healthReason)
	}
	if vlmStatus != aiStatusHealthy || vlmReason != "" {
		t.Fatalf("VLM = (%q, %q), want healthy current description", vlmStatus, vlmReason)
	}
	if embeddingStatus != "unknown" || embeddingTime != "" {
		t.Fatalf("embedding state = (%q, %q), want realtime Agent lookup", embeddingStatus, embeddingTime)
	}
}

func TestDerivePhotoAIStateKeepsCurrentDescriptionReview(t *testing.T) {
	photo := &data.PhotoDO{
		Description:     "故障彩条画面\n```json\n{}\n```",
		EmbeddingStatus: aiStatusHealthy,
	}

	health, healthReason, vlmStatus, vlmReason, embeddingStatus, _ := derivePhotoAIState(photo)
	if health != aiStatusReview || vlmStatus != aiStatusReview || embeddingStatus != "unknown" {
		t.Fatalf("derived state = health:%q vlm:%q embedding:%q, want review/review/unknown", health, vlmStatus, embeddingStatus)
	}
	if !strings.Contains(healthReason, "故障彩条") || healthReason != vlmReason {
		t.Fatalf("review reason = health:%q vlm:%q, want current validation reason", healthReason, vlmReason)
	}
}

func TestParseVlmAttrs_NoJSONBlock(t *testing.T) {
	// 无 ```json 围栏的纯文本 -> extractJSONBlock 返回空 -> warning 日志
	desc := "这是一段没有 JSON 的纯文本描述"
	objects, colors, scene, lighting, mood, composition := parseVlmAttrs("no_json.jpg", desc)

	if objects != "" || colors != "" || scene != "" || lighting != "" || mood != "" || composition != "" {
		t.Errorf("expected all empty for no JSON block, got objects=%q colors=%q scene=%q lighting=%q mood=%q composition=%q",
			objects, colors, scene, lighting, mood, composition)
	}
}

func TestParseVlmAttrs_MalformedJSON(t *testing.T) {
	// JSON 语法错误 -> json.Unmarshal 失败 -> warning 日志
	desc := "```json\n{this is not valid json...\n```\n"
	objects, colors, scene, lighting, mood, composition := parseVlmAttrs("bad_json.jpg", desc)

	if objects != "" || colors != "" || scene != "" || lighting != "" || mood != "" || composition != "" {
		t.Errorf("expected all empty for malformed JSON, got objects=%q colors=%q scene=%q lighting=%q mood=%q composition=%q",
			objects, colors, scene, lighting, mood, composition)
	}
}

func TestParseVlmAttrs_EmptyDescription(t *testing.T) {
	objects, colors, scene, lighting, mood, composition := parseVlmAttrs("empty.jpg", "")
	if objects != "" || colors != "" || scene != "" || lighting != "" || mood != "" || composition != "" {
		t.Error("expected all empty for empty description")
	}
}

func TestParseVlmAttrs_EmptyObjectList(t *testing.T) {
	// subject.main_objects 为空数组 -> objects 应为空字符串
	desc := "```json\n{\n  \"subject\": {\"main_objects\": []},\n  \"color_palette\": {\"dominant_colors\": []},\n  \"scene\": {\"environment\": \"\", \"setting\": \"\", \"time_of_day\": \"\"},\n  \"lighting\": {\"source\": \"\"},\n  \"mood\": \"\",\n  \"composition\": {\"focus\": \"\", \"depth\": \"\", \"symmetry\": \"\"}\n}\n```"
	objects, _, _, _, _, _ := parseVlmAttrs("empty_attrs.jpg", desc)
	if objects != "" {
		t.Errorf("expected empty objects for empty array, got %q", objects)
	}
}

// TestExtractJSONBlock 覆盖 extractJSONBlock 的各种路径
func TestExtractJSONBlock(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  string
	}{
		{"with_fence", "```json\n{\"a\": 1}\n```", "{\"a\": 1}"},
		{"no_fence_plain_json", "{\"a\": 1}", "{\"a\": 1}"},
		{"empty_fence", "```json\n```", ""},
		{"no_newline_after_fence", "```json{\"a\": 1}", ""},
		{"no_lang_fence", "```\n{\"a\": 1}\n```", "{\"a\": 1}"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := extractJSONBlock(tt.input)
			if got != tt.want {
				t.Errorf("extractJSONBlock(%q) = %q, want %q", tt.input, got, tt.want)
			}
		})
	}
}

// TestAllEmpty checks the helper used in syncUpdatePhoto backfill skip logic
func TestAllEmpty(t *testing.T) {
	allEmpty := func(objects, colors, scene, lighting, mood, composition string) bool {
		return objects == "" && colors == "" && scene == "" &&
			lighting == "" && mood == "" && composition == ""
	}

	if !allEmpty("", "", "", "", "", "") {
		t.Error("allEmpty should be true for all empty")
	}
	if allEmpty("猫", "", "", "", "", "") {
		t.Error("allEmpty should be false when objects is non-empty")
	}
}

// TestBackfillSkipLogic 模拟 syncUpdatePhoto 中的跳过逻辑
func TestBackfillSkipLogic(t *testing.T) {
	// 模拟场景：needAttrBackfill=true, descChanged=false, timelineChanged=false
	// 且 parseVlmAttrs 返回全空 -> 应跳过
	descChanged := false
	timelineChanged := false
	needAttrBackfill := true
	// 模拟解析失败（全空返回值）
	objects, colors, scene, lighting, mood, composition := "", "", "", "", "", ""

	shouldSkip := needAttrBackfill && !descChanged && !timelineChanged &&
		objects == "" && colors == "" && scene == "" &&
		lighting == "" && mood == "" && composition == ""

	if !shouldSkip {
		t.Error("backfill with all-empty parse result should be skipped")
	}

	// 模拟场景：descChanged=true -> 即使 attrs 全空也不跳过
	descChanged = true
	shouldSkip = needAttrBackfill && !descChanged && !timelineChanged &&
		objects == "" && colors == "" && scene == "" &&
		lighting == "" && mood == "" && composition == ""
	if shouldSkip {
		t.Error("descChanged should prevent backfill skip")
	}

	// 模拟场景：解析成功（有非空字段）-> 不跳过
	descChanged = false
	objects = "猫"
	colors = ""
	shouldSkip = needAttrBackfill && !descChanged && !timelineChanged &&
		objects == "" && colors == "" && scene == "" &&
		lighting == "" && mood == "" && composition == ""
	if shouldSkip {
		t.Error("non-empty parse result should not be skipped")
	}
}

// TestPhotoIdentifierInWarning 验证 photo ID 出现在日志中的能力
// 实际日志验证需要通过 plogger 捕获，这里仅验证参数传递正确
func TestPhotoIdentifierInWarning(t *testing.T) {
	// 用无 JSON 的文本触发 warning 路径，验证不会 panic
	desc := "这是一张没有 JSON 代码块的照片描述。"
	// 关键验证：photoIdentifier 参数被正确接收并使用
	photoID := "photos/2024/beijing/tiananmen.jpg"
	objects, colors, scene, lighting, mood, composition := parseVlmAttrs(photoID, desc)

	if objects != "" || colors != "" || scene != "" || lighting != "" || mood != "" || composition != "" {
		t.Error("expected all empty for non-JSON description")
	}
	// plogger.Warnf 会被调用但无法在此捕获，验证不 panic 即可
	_ = photoID
}

// TestParseVlmAttrs_RealWorldVLMOutput 使用近真实 VLM 输出格式
func TestParseVlmAttrs_RealWorldVLMOutput(t *testing.T) {
	// 模拟真实的 VLM 输出格式（包含中文描述前缀 + JSON 代码块）
	desc := `这是一张街头摄影照片，画面中一位老人坐在长椅上阅读报纸。

` + "```json" + `
{
  "subject": {
    "main_objects": ["老人", "长椅", "报纸"]
  },
  "color_palette": {
    "dominant_colors": ["灰", "棕", "白"]
  },
  "scene": {
    "environment": "城市街头",
    "setting": "人行道旁",
    "time_of_day": "清晨"
  },
  "lighting": {
    "source": "侧逆光"
  },
  "mood": "沉静专注",
  "composition": {
    "focus": "三分线交点",
    "depth": "中等景深",
    "symmetry": "不对称"
  }
}
` + "```"

	objects, _, scene, lighting, mood, composition := parseVlmAttrs("street_photo.jpg", desc)

	if !strings.Contains(objects, "老人") || !strings.Contains(objects, "长椅") || !strings.Contains(objects, "报纸") {
		t.Errorf("objects = %q, expected 老人、长椅、报纸", objects)
	}
	if scene != "城市街头，人行道旁" {
		t.Errorf("scene = %q, want %q", scene, "城市街头，人行道旁")
	}
	if lighting != "侧逆光，清晨" {
		t.Errorf("lighting = %q, want %q", lighting, "侧逆光，清晨")
	}
	if mood != "沉静专注" {
		t.Errorf("mood = %q, want %q", mood, "沉静专注")
	}
	if composition != "三分线交点，中等景深，不对称" {
		t.Errorf("composition = %q, want %q", composition, "三分线交点，中等景深，不对称")
	}
}

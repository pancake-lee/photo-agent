package service

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"backend/internal/defaultService/data"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

const (
	aiStatusPending  = "pending"
	aiStatusWorking  = "processing"
	aiStatusHealthy  = "healthy"
	aiStatusFailed   = "failed"
	aiStatusReview   = "review"
	aiStatusStale    = "stale"
	aiStatusExcluded = "excluded"
)

// reviewMarkers 已证实的坏图描述措辞。VLM 对同一故障现象的说法不固定
// （故障彩条 / 故障失真 / 异常显示画面 / 花屏 / glitch / corrupted），
// 命中任一即待复核；发现新措辞时在此补充。
var reviewMarkers = []string{
	"故障画面", "故障彩条", "故障失真", "测试图",
	"异常显示画面", "显示异常", "花屏",
	"color bars", "test pattern", "glitch", "corrupted",
}

func validateVlmDescription(description string) error {
	text := strings.TrimSpace(description)
	if text == "" {
		return fmt.Errorf("VLM returned an empty description")
	}
	jsonBlock := extractJSONBlock(text)
	if jsonBlock == "" || !json.Valid([]byte(jsonBlock)) {
		return fmt.Errorf("VLM description has no valid structured JSON")
	}
	if err := validateVlmImageIntegrity(jsonBlock); err != nil {
		return err
	}
	lower := strings.ToLower(text)
	for _, marker := range reviewMarkers {
		if strings.Contains(lower, marker) {
			return fmt.Errorf("description matched review rule: %s", marker)
		}
	}
	// 颜色、条纹和色块本身都是正常摄影内容，只有组合成典型故障画面时才拦截。
	if strings.Contains(lower, "条纹组") && strings.Contains(lower, "色块") {
		return fmt.Errorf("description matched review rule: 条纹组与色块组合")
	}
	return nil
}

// validateVlmImageIntegrity 读取 VLM 的结构化完整性结论（vlm_prompt.md 的 image_integrity 字段）。
// 存量描述没有该字段，返回通过，由关键词规则兜底。
func validateVlmImageIntegrity(jsonBlock string) error {
	var payload struct {
		ImageIntegrity string `json:"image_integrity"`
	}
	if err := json.Unmarshal([]byte(jsonBlock), &payload); err != nil {
		return nil
	}
	switch strings.ToLower(strings.TrimSpace(payload.ImageIntegrity)) {
	case "corrupted", "test_pattern":
		return fmt.Errorf("description matched review rule: image_integrity=%s", payload.ImageIntegrity)
	}
	return nil
}

func recordAIHistory(photoID, taskID, stage, status, reason string) {
	ctx := papp.NewAppCtx(context.Background())
	if err := data.AddAIProcessingHistory(ctx, photoID, taskID, stage, status, reason, nowTimeString()); err != nil {
		plogger.Warnf("record AI history failed: %v", err)
	}
}

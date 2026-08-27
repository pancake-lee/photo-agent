package service

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"github.com/pancake-lee/pgo/pkg/putil"
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

func validateVlmDescription(description string) error {
	text := strings.TrimSpace(description)
	if text == "" {
		return fmt.Errorf("VLM returned an empty description")
	}
	jsonBlock := extractJSONBlock(text)
	if jsonBlock == "" || !json.Valid([]byte(jsonBlock)) {
		return fmt.Errorf("VLM description has no valid structured JSON")
	}
	lower := strings.ToLower(text)
	for _, marker := range []string{"故障画面", "故障彩条", "测试图", "color bars", "test pattern"} {
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

func updateAIState(ctx *papp.AppCtx, photoID, health, healthReason, vlmStatus, vlmReason, embeddingStatus string) error {
	// 健康结论全部在读取时实时推导，保留此函数仅兼容现有调用链。
	return nil
}

func recordAIHistory(photoID, taskID, stage, status, reason string) {
	_ = pdb.GetGormDB().Table("ai_processing_history").Create(map[string]any{
		"id":         putil.UUID(),
		"photo_id":   photoID,
		"task_id":    taskID,
		"stage":      stage,
		"status":     status,
		"reason":     reason,
		"created_at": nowTimeString(),
	}).Error
}

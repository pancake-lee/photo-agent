package service

import (
	"encoding/json"
	"fmt"
	"strings"

	"backend/internal/pkg/db"

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
	for _, marker := range []string{
		"彩条", "条纹组", "故障画面", "测试图", "纯黑", "纯白",
		"color bars", "test pattern", "vertical stripes", "horizontal stripes",
	} {
		if strings.Contains(lower, strings.ToLower(marker)) {
			return fmt.Errorf("description matched review rule: %s", marker)
		}
	}
	return nil
}

func updateAIState(ctx *papp.AppCtx, photoID, health, healthReason, vlmStatus, vlmReason, embeddingStatus string) error {
	q := db.GetQuery().Photo
	_, err := q.WithContext(ctx).Where(q.ID.Eq(photoID)).Updates(map[string]any{
		"ai_health_status": health,
		"ai_health_reason": healthReason,
		"vlm_status":       vlmStatus,
		"vlm_reason":       vlmReason,
		"embedding_status": embeddingStatus,
	})
	return err
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

package data

import (
	"fmt"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"github.com/pancake-lee/pgo/pkg/putil"
)

// AddAIProcessingHistory 记录一次 AI 处理结果，供队列和单张处理共用。
func AddAIProcessingHistory(ctx *papp.AppCtx, photoID, taskID, stage, status, reason, createdAt string) error {
	err := pdb.GetGormDB().WithContext(ctx).Table("ai_processing_history").Create(map[string]any{
		"id":         putil.UUID(),
		"photo_id":   photoID,
		"task_id":    taskID,
		"stage":      stage,
		"status":     status,
		"reason":     reason,
		"created_at": createdAt,
	}).Error
	if err != nil {
		return fmt.Errorf("add AI processing history failed: %w", err)
	}
	return nil
}

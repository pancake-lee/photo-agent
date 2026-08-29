package service

import (
	"testing"
	"time"

	"backend/internal/defaultService/data"
)

func TestDraftDO2ResponsePreservesEditingInput(t *testing.T) {
	now := time.Date(2026, 8, 29, 10, 0, 0, 0, time.UTC)
	draft := &data.DraftDO{
		ID:         "draft-1",
		PhotoIDs:   `["photo-1"]`,
		InputMode:  "draft",
		Prompt:     "记录旅途",
		DraftInput: "雨后的山路很安静",
		CreatedAt:  now,
		UpdatedAt:  now,
	}

	response := draftDO2Response(draft)
	if response.InputMode != draft.InputMode || response.Prompt != draft.Prompt || response.DraftInput != draft.DraftInput {
		t.Fatalf("editing input was not preserved: %#v", response)
	}
}

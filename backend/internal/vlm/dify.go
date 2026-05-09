package vlm

import (
	"encoding/json"
	"fmt"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"
)

// WriteToKnowledgeBase 将照片描述写入 Dify 知识库
func WriteToKnowledgeBase(photoID, description, timeline string) error {
	cfg := config.Get().Dify

	if cfg.APIKey == "" || cfg.DatasetID == "" {
		return fmt.Errorf("dify not configured")
	}

	doc := map[string]any{
		"name": fmt.Sprintf("photo_%s", photoID),
		"text": description,
		"indexing_technique": "high_quality",
		"doc_form":           "text_model",
		"doc_language":       "Chinese",
	}

	if timeline != "" {
		doc["doc_metadata"] = map[string]string{
			"timeline": timeline,
		}
	}

	url := fmt.Sprintf("%s/datasets/%s/document/create-by-text", cfg.BaseURL, cfg.DatasetID)
	req, err := putil.NewHttpRequestJson("POST", url, map[string]string{
		"Authorization": "Bearer " + cfg.APIKey,
	}, nil, doc)
	if err != nil {
		return fmt.Errorf("build request failed: %w", err)
	}

	bodyBytes, err := putil.HttpDo(req)
	if err != nil {
		return fmt.Errorf("http request failed: %w", err)
	}

	var resp difyDocResp
	if err := json.Unmarshal(bodyBytes, &resp); err != nil {
		return fmt.Errorf("unmarshal response failed: %w", err)
	}

	if resp.Document.ID == "" {
		return fmt.Errorf("dify create document failed: %s", string(bodyBytes))
	}

	plogger.Infof("Dify document created: photo_%s, doc_id=%s", photoID, resp.Document.ID)
	return nil
}

type difyDocResp struct {
	Document struct {
		ID string `json:"id"`
	} `json:"document"`
}

package api

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/pgo/pkg/putil"
)

// OpenAIEmbeddingRequest OpenAI 标准 embedding 请求
type OpenAIEmbeddingRequest struct {
	Model string      `json:"model"`
	Input interface{} `json:"input"`
}

// OpenAIEmbeddingResponse OpenAI 标准 embedding 响应
type OpenAIEmbeddingResponse struct {
	Object string                   `json:"object"`
	Data   []OpenAIEmbeddingData    `json:"data"`
	Model  string                   `json:"model"`
	Usage  OpenAIEmbeddingUsage     `json:"usage"`
}

type OpenAIEmbeddingData struct {
	Object    string    `json:"object"`
	Embedding []float32 `json:"embedding"`
	Index     int       `json:"index"`
}

type OpenAIEmbeddingUsage struct {
	PromptTokens int `json:"prompt_tokens"`
	TotalTokens  int `json:"total_tokens"`
}

// VolcEmbeddingRequest 火山引擎 multimodal embedding 请求
type VolcEmbeddingRequest struct {
	Model string                 `json:"model"`
	Input []VolcEmbeddingInput   `json:"input"`
}

type VolcEmbeddingInput struct {
	Type string `json:"type"`
	Text string `json:"text,omitempty"`
}

// VolcEmbeddingResponse 火山引擎 multimodal embedding 响应
type VolcEmbeddingResponse struct {
	Created int                    `json:"created"`
	Data    VolcEmbeddingData      `json:"data"`
	ID      string                 `json:"id"`
	Model   string                 `json:"model"`
	Object  string                 `json:"object"`
	Usage   VolcEmbeddingUsage     `json:"usage"`
}

type VolcEmbeddingData struct {
	Embedding []float32 `json:"embedding"`
}

type VolcEmbeddingUsage struct {
	PromptTokens int `json:"prompt_tokens"`
	TotalTokens  int `json:"total_tokens"`
}

// EmbeddingProxy 将 OpenAI 格式的 embedding 请求代理到火山引擎 multimodal API
func EmbeddingProxy(c *gin.Context) {
	cfg := config.Get().Embedding
	if cfg.APIKey == "" {
		cfg = config.EmbeddingConfig{
			APIKey:  config.Get().VLM.APIKey,
			Model:   config.Get().VLM.Model,
			BaseURL: config.Get().VLM.BaseURL,
		}
	}

	var req OpenAIEmbeddingRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}

	// 提取所有文本输入
	var texts []string
	switch v := req.Input.(type) {
	case string:
		texts = append(texts, v)
	case []interface{}:
		for _, item := range v {
			if s, ok := item.(string); ok {
				texts = append(texts, s)
			}
		}
	}

	if len(texts) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "input must be a string or array of strings"})
		return
	}

	// 逐条请求火山引擎 multimodal API，合并结果
	model := req.Model
	if model == "" {
		model = cfg.Model
	}

	var resp OpenAIEmbeddingResponse
	resp.Object = "list"
	resp.Model = model

	for i, text := range texts {
		embedding, usage, err := callVolcengine(cfg, model, text)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		resp.Data = append(resp.Data, OpenAIEmbeddingData{
			Object:    "embedding",
			Embedding: embedding,
			Index:     i,
		})
		resp.Usage.PromptTokens += usage.PromptTokens
		resp.Usage.TotalTokens += usage.TotalTokens
	}

	c.JSON(http.StatusOK, resp)
}

func callVolcengine(cfg config.EmbeddingConfig, model, text string) ([]float32, VolcEmbeddingUsage, error) {
	var emptyUsage VolcEmbeddingUsage

	volcReq := VolcEmbeddingRequest{
		Model: model,
		Input: []VolcEmbeddingInput{
			{Type: "text", Text: text},
		},
	}

	url := cfg.BaseURL + "/embeddings/multimodal"
	headers := map[string]string{
		"Authorization": "Bearer " + cfg.APIKey,
	}

	httpReq, err := putil.NewHttpRequestJson("POST", url, headers, nil, volcReq)
	if err != nil {
		return nil, emptyUsage, fmt.Errorf("build request failed: %w", err)
	}

	body, err := putil.HttpDo(httpReq)
	if err != nil {
		return nil, emptyUsage, fmt.Errorf("request failed: %w", err)
	}

	var volcResp VolcEmbeddingResponse
	if err := json.Unmarshal(body, &volcResp); err != nil {
		return nil, emptyUsage, fmt.Errorf("unmarshal response failed: %w, body: %s", err, string(body))
	}

	return volcResp.Data.Embedding, volcResp.Usage, nil
}

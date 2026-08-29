package service

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"backend/internal/defaultService/conf"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

// --------------------------------------------------
// EmbeddingServer embedding 代理服务（OpenAI 格式 → 火山引擎 multimodal）
// 纯 HTTP 反向代理，不纳入 proto 生成体系，保持独立注册。
// --------------------------------------------------

// EmbeddingServer embedding 代理服务
type EmbeddingServer struct{}

const embeddingRequestTimeout = 15 * time.Second

var embeddingHTTPClient = &http.Client{Timeout: embeddingRequestTimeout}

// Reg 向 Kratos HTTP 服务器注册 embedding 代理路由。
func (s *EmbeddingServer) Reg(_ *grpc.Server, httpSrv *khttp.Server) {
	if httpSrv != nil {
		r := httpSrv.Route("/")
		r.POST("/v1/embeddings", s.handleEmbedding)
		r.GET("/v1/embeddings/health", s.handleEmbeddingHealth)
	}
}

// --------------------------------------------------
// 请求/响应类型（OpenAI 兼容格式）

type embeddingReq struct {
	Model string `json:"model"`
	Input any    `json:"input"`
}

type embeddingData struct {
	Object    string    `json:"object"`
	Embedding []float32 `json:"embedding"`
	Index     int       `json:"index"`
}

type embeddingUsage struct {
	PromptTokens int `json:"prompt_tokens"`
	TotalTokens  int `json:"total_tokens"`
}

type embeddingResp struct {
	Object string          `json:"object"`
	Data   []embeddingData `json:"data"`
	Model  string          `json:"model"`
	Usage  embeddingUsage  `json:"usage"`
}

// volcEmbeddingReq 火山引擎 multimodal embedding 请求
type volcEmbeddingReq struct {
	Model string             `json:"model"`
	Input []volcEmbeddingInp `json:"input"`
}

type volcEmbeddingInp struct {
	Type string `json:"type"`
	Text string `json:"text,omitempty"`
}

// volcEmbeddingResp 火山引擎 multimodal embedding 响应
type volcEmbeddingResp struct {
	Data  volcEmbeddingData  `json:"data"`
	Usage volcEmbeddingUsage `json:"usage"`
}

type volcEmbeddingData struct {
	Embedding []float32 `json:"embedding"`
}

type volcEmbeddingUsage struct {
	PromptTokens int `json:"prompt_tokens"`
	TotalTokens  int `json:"total_tokens"`
}

// --------------------------------------------------

// handleEmbedding 处理 POST /v1/embeddings
func (s *EmbeddingServer) handleEmbedding(ctx khttp.Context) error {
	var req embeddingReq
	if err := ctx.Bind(&req); err != nil {
		_ = ctx.Result(400, map[string]string{"error": "invalid request body"})
		return nil
	}

	texts, err := extractTexts(req.Input)
	if err != nil {
		_ = ctx.Result(400, map[string]string{"error": err.Error()})
		return nil
	}

	cfg := getEmbeddingConfig()
	if cfg.BaseURL == "" {
		_ = ctx.Result(500, map[string]string{"error": "embedding not configured: BaseURL is empty"})
		return nil
	}

	requestCtx, cancel := context.WithTimeout(ctx.Request().Context(), embeddingRequestTimeout)
	defer cancel()
	resp, err := generateEmbeddingResponse(requestCtx, cfg, req.Model, texts)
	if err != nil {
		_ = ctx.Result(500, map[string]string{"error": err.Error()})
		return nil
	}

	return ctx.Result(200, resp)
}

type embedConfig struct {
	APIKey  string
	Model   string
	BaseURL string
}

// getEmbeddingConfig 获取 embedding 配置，APIKey 为空时回退到 VLM 配置。
func getEmbeddingConfig() embedConfig {
	ec := conf.C.Embedding
	if ec.APIKey != "" {
		return embedConfig{
			APIKey:  ec.APIKey,
			Model:   ec.Model,
			BaseURL: ec.BaseURL,
		}
	}
	// 回退到 VLM 配置
	return embedConfig{
		APIKey:  conf.C.VLM.APIKey,
		Model:   conf.C.VLM.Model,
		BaseURL: conf.C.VLM.BaseURL,
	}
}

// handleEmbeddingHealth 处理 GET /v1/embeddings/health，检查 embedding 服务配置可用性。
func (s *EmbeddingServer) handleEmbeddingHealth(ctx khttp.Context) error {
	cfg := getEmbeddingConfig()
	if cfg.BaseURL == "" {
		return ctx.Result(200, map[string]string{
			"status": "unconfigured",
			"reason": "BaseURL is empty",
		})
	}
	return ctx.Result(200, map[string]string{
		"status": "ok",
		"model":  cfg.Model,
	})
}

// extractTexts 从 OpenAI 格式的 input 字段提取文本列表。
// input 可以是单个字符串或字符串数组。
func extractTexts(input any) ([]string, error) {
	var texts []string
	switch v := input.(type) {
	case string:
		texts = append(texts, v)
	case []any:
		for _, item := range v {
			if s, ok := item.(string); ok {
				texts = append(texts, s)
			}
		}
	}
	if len(texts) == 0 {
		return nil, fmt.Errorf("input must be a string or array of strings")
	}
	return texts, nil
}

// embedResult 单条 embedding 结果
type embedResult struct {
	embedding []float32
	usage     volcEmbeddingUsage
}

// generateEmbeddingResponse 按输入顺序逐条生成 embedding，并在任一次失败后立即停止。
func generateEmbeddingResponse(ctx context.Context, cfg embedConfig, model string, texts []string) (*embeddingResp, error) {
	resp := &embeddingResp{Object: "list", Model: model}
	for i, text := range texts {
		result, err := callVolcengineEmbedding(ctx, cfg, model, text)
		if err != nil {
			return nil, err
		}
		resp.Data = append(resp.Data, embeddingData{
			Object: "embedding", Embedding: result.embedding, Index: i,
		})
		resp.Usage.PromptTokens += result.usage.PromptTokens
		resp.Usage.TotalTokens += result.usage.TotalTokens
	}
	return resp, nil
}

// callVolcengineEmbedding 调用火山引擎 API 为单条文本生成 embedding。
func callVolcengineEmbedding(ctx context.Context, cfg embedConfig, model, text string) (*embedResult, error) {
	if model == "" {
		model = cfg.Model
	}

	volcReq := volcEmbeddingReq{
		Model: model,
		Input: []volcEmbeddingInp{
			{Type: "text", Text: text},
		},
	}

	body, err := json.Marshal(volcReq)
	if err != nil {
		return nil, fmt.Errorf("build request failed: %w", err)
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, cfg.BaseURL+"/embeddings/multimodal", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build request failed: %w", err)
	}
	httpReq.Header.Set("Authorization", "Bearer "+cfg.APIKey)
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := embeddingHTTPClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	responseBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response body failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("request failed: status code %d, body: %s", resp.StatusCode, string(responseBody))
	}

	var volcResp volcEmbeddingResp
	if err := json.Unmarshal(responseBody, &volcResp); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %w, body: %s", err, string(responseBody))
	}

	return &embedResult{
		embedding: volcResp.Data.Embedding,
		usage:     volcResp.Usage,
	}, nil
}

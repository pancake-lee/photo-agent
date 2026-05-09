package vlm

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"
)

const defaultVlmPrompt = `请详细描述这张照片的内容。包括：
- 主体内容（人/物/风景）
- 场景环境（室内/室外、自然/城市）
- 光线氛围（明亮/昏暗、自然光/人工光）
- 色彩风格（鲜艳/柔和、冷暖倾向）
- 构图特点（前景/背景、对称/非对称）`

// DescribeImage 对单张图片进行 VLM 描述
func DescribeImage(imagePath string) (string, string, error) {
	cfg := config.Get().VLM

	imagePath, cleanup, err := maybeCompressImage(imagePath, cfg.MaxImageSizeMB)
	if err != nil {
		return "", "", fmt.Errorf("compress image failed: %w", err)
	}
	if cleanup != nil {
		defer cleanup()
	}

	prompt := cfg.Prompt
	if prompt == "" {
		prompt = defaultVlmPrompt
	}

	switch cfg.Provider {
	case "volcengine":
		return describeWithArk(imagePath, cfg, prompt)
	default:
		return describeWithHTTP(imagePath, cfg, prompt)
	}
}

// describeWithArk 使用火山方舟 Responses HTTP API 调用
func describeWithArk(imagePath string, cfg config.VLMConfig, prompt string) (string, string, error) {
	imageData, err := os.ReadFile(imagePath)
	if err != nil {
		return "", "", fmt.Errorf("read image failed: %w", err)
	}

	base64Image := base64.StdEncoding.EncodeToString(imageData)
	mimeType := getMimeType(imagePath)
	imageURL := fmt.Sprintf("data:%s;base64,%s", mimeType, base64Image)

	baseURL := cfg.BaseURL
	if baseURL == "" {
		baseURL = "https://ark.cn-beijing.volces.com/api/v3"
	}

	reqBody := map[string]any{
		"model": cfg.Model,
		"input": []map[string]any{
			{
				"role": "user",
				"content": []map[string]any{
					{"type": "input_image", "image_url": imageURL},
					{"type": "input_text", "text": prompt},
				},
			},
		},
	}

	req, err := putil.NewHttpRequestJson("POST", baseURL+"/responses", map[string]string{
		"Authorization": "Bearer " + cfg.APIKey,
	}, nil, reqBody)
	if err != nil {
		return "", "", fmt.Errorf("build request failed: %w", err)
	}

	bodyBytes, err := putil.HttpDo(req)
	if err != nil {
		return "", "", fmt.Errorf("http request failed: %w", err)
	}

	var resp responsesResp
	if err := json.Unmarshal(bodyBytes, &resp); err != nil {
		return "", "", fmt.Errorf("unmarshal response failed: %w", err)
	}

	description := ""
	for _, out := range resp.Output {
		if out.Type == "message" {
			for _, c := range out.Content {
				if c.Type == "output_text" && c.Text != "" {
					description = c.Text
					break
				}
			}
		}
		if description != "" {
			break
		}
	}

	if description == "" {
		return "", "", fmt.Errorf("empty response: %s", string(bodyBytes))
	}

	modelUsed := resp.Model
	if modelUsed == "" {
		modelUsed = cfg.Model
	}

	plogger.Infof("VLM described %s, model=%s, len=%d", imagePath, modelUsed, len(description))
	return description, modelUsed, nil
}

// describeWithHTTP 使用 OpenAI 兼容 HTTP 调用
func describeWithHTTP(imagePath string, cfg config.VLMConfig, prompt string) (string, string, error) {
	imageData, err := os.ReadFile(imagePath)
	if err != nil {
		return "", "", fmt.Errorf("read image failed: %w", err)
	}

	base64Image := base64.StdEncoding.EncodeToString(imageData)
	mimeType := getMimeType(imagePath)

	reqBody := map[string]any{
		"model": cfg.Model,
		"messages": []map[string]any{
			{
				"role": "user",
				"content": []map[string]any{
					{"type": "text", "text": prompt},
					{"type": "image_url", "image_url": map[string]string{
						"url": fmt.Sprintf("data:%s;base64,%s", mimeType, base64Image),
					}},
				},
			},
		},
		"max_tokens": 500,
	}

	req, err := putil.NewHttpRequestJson("POST", cfg.BaseURL+"/chat/completions", map[string]string{
		"Authorization": "Bearer " + cfg.APIKey,
	}, nil, reqBody)
	if err != nil {
		return "", "", fmt.Errorf("build request failed: %w", err)
	}

	bodyBytes, err := putil.HttpDo(req)
	if err != nil {
		return "", "", fmt.Errorf("http request failed: %w", err)
	}

	var resp openAIChatResp
	if err := json.Unmarshal(bodyBytes, &resp); err != nil {
		return "", "", fmt.Errorf("unmarshal response failed: %w", err)
	}

	if len(resp.Choices) == 0 {
		return "", "", fmt.Errorf("no choices in response")
	}

	description := resp.Choices[0].Message.Content
	modelUsed := resp.Model
	if modelUsed == "" {
		modelUsed = cfg.Model
	}

	plogger.Infof("VLM described %s, model=%s, len=%d", imagePath, modelUsed, len(description))
	return description, modelUsed, nil
}

// responsesResp 火山方舟 Responses API 响应结构
type responsesResp struct {
	Model  string `json:"model"`
	Output []struct {
		Type    string `json:"type"`
		Role    string `json:"role"`
		Content []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
		Summary []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"summary"`
	} `json:"output"`
}

// openAIChatResp OpenAI 兼容格式的响应结构
type openAIChatResp struct {
	Model   string `json:"model"`
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
}



package vlm

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"

	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"
	"github.com/pancake-lee/photo-agent/internal/config"
)

// ErrQuotaExceeded 表示 VLM API 额度已耗尽，重试无意义，应停止程序
var ErrQuotaExceeded = errors.New("VLM API quota exceeded")

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

	if cfg.Prompt == "" {
		return "", "", fmt.Errorf("VLM prompt file path not configured (vlm.prompt in config.yaml)")
	}

	promptPath := config.Get().ResolvePath(cfg.Prompt)
	promptBytes, err := os.ReadFile(promptPath)
	if err != nil {
		return "", "", fmt.Errorf("read VLM prompt file %q failed: %w", promptPath, err)
	}

	prompt := string(promptBytes)
	if prompt == "" {
		return "", "", fmt.Errorf("VLM prompt file %q is empty", promptPath)
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
		return "", "", wrapAPIError(bodyBytes)
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
		return "", "", wrapAPIError(bodyBytes)
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

// apiError 通用 API 错误结构
type apiError struct {
	Error struct {
		Code    string `json:"code"`
		Message string `json:"message"`
		Type    string `json:"type"`
	} `json:"error"`
}

// wrapAPIError 解析 API 错误响应，识别额度耗尽等不可恢复错误
func wrapAPIError(bodyBytes []byte) error {
	var apiErr apiError
	if err := json.Unmarshal(bodyBytes, &apiErr); err != nil || apiErr.Error.Code == "" {
		return fmt.Errorf("empty response: %s", string(bodyBytes))
	}

	switch apiErr.Error.Code {
	case "SetLimitExceeded", "InsufficientQuota", "RateLimitExceeded":
		return fmt.Errorf("%w: code=%s type=%s msg=%s", ErrQuotaExceeded, apiErr.Error.Code, apiErr.Error.Type, apiErr.Error.Message)
	default:
		return fmt.Errorf("api error: code=%s type=%s msg=%s", apiErr.Error.Code, apiErr.Error.Type, apiErr.Error.Message)
	}
}

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

const vlmPrompt = `请详细描述这张照片的内容。包括：
- 主体内容（人/物/风景）
- 场景环境（室内/室外、自然/城市）
- 光线氛围（明亮/昏暗、自然光/人工光）
- 色彩风格（鲜艳/柔和、冷暖倾向）
- 构图特点（前景/背景、对称/非对称）`

// DescribeImage 对单张图片进行 VLM 描述
func DescribeImage(imagePath string) (string, string, error) {
	cfg := config.Get().VLM

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
					{"type": "text", "text": vlmPrompt},
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

// openAIChatResp OpenAI 兼容格式的响应结构
type openAIChatResp struct {
	Model   string `json:"model"`
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
}

func getMimeType(path string) string {
	ext := ""
	for i := len(path) - 1; i >= 0; i-- {
		if path[i] == '.' {
			ext = path[i+1:]
			break
		}
	}
	switch ext {
	case "png":
		return "image/png"
	case "jpg", "jpeg":
		return "image/jpeg"
	case "webp":
		return "image/webp"
	default:
		return "image/jpeg"
	}
}

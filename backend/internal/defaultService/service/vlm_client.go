package service

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"backend/internal/defaultService/conf"

	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"
)

var errQuotaExceeded = errors.New("VLM API quota exceeded")

func describeImage(imagePath string) (string, string, error) {
	cfg := conf.C.VLM

	compressedPath, cleanup, err := maybeCompressImage(imagePath, cfg.MaxImageSizeMB)
	if err != nil {
		return "", "", fmt.Errorf("compress image failed: %w", err)
	}
	if cleanup != nil {
		defer cleanup()
	}

	if cfg.Prompt == "" {
		return "", "", fmt.Errorf("VLM prompt not configured (vlm.prompt in config)")
	}

	promptBytes, err := os.ReadFile(cfg.Prompt)
	if err != nil {
		return "", "", fmt.Errorf("read VLM prompt file %q failed: %w", cfg.Prompt, err)
	}
	prompt := string(promptBytes)
	if prompt == "" {
		return "", "", fmt.Errorf("VLM prompt file %q is empty", cfg.Prompt)
	}

	imageData, err := os.ReadFile(compressedPath)
	if err != nil {
		return "", "", fmt.Errorf("read image failed: %w", err)
	}

	base64Image := base64.StdEncoding.EncodeToString(imageData)
	mimeType := getMimeType(compressedPath)
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

	httpReq, err := putil.NewHttpRequestJson("POST", baseURL+"/responses", map[string]string{
		"Authorization": "Bearer " + cfg.APIKey,
	}, nil, reqBody)
	if err != nil {
		return "", "", fmt.Errorf("build request failed: %w", err)
	}

	resp, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		return "", "", fmt.Errorf("http request failed: %w", err)
	}
	defer resp.Body.Close()

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", "", fmt.Errorf("read response failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return "", "", wrapAPIError(bodyBytes)
	}

	var arkResp responsesResp
	if err := json.Unmarshal(bodyBytes, &arkResp); err != nil {
		return "", "", fmt.Errorf("unmarshal response failed: %w", err)
	}

	description := ""
	for _, out := range arkResp.Output {
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

	modelUsed := arkResp.Model
	if modelUsed == "" {
		modelUsed = cfg.Model
	}

	plogger.Infof("VLM described %s, model=%s, len=%d", imagePath, modelUsed, len(description))
	return description, modelUsed, nil
}

type responsesResp struct {
	Model  string `json:"model"`
	Output []struct {
		Type    string `json:"type"`
		Role    string `json:"role"`
		Content []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
	} `json:"output"`
}

type apiError struct {
	Error struct {
		Code    string `json:"code"`
		Message string `json:"message"`
		Type    string `json:"type"`
	} `json:"error"`
}

func wrapAPIError(bodyBytes []byte) error {
	var apiErr apiError
	if err := json.Unmarshal(bodyBytes, &apiErr); err != nil || apiErr.Error.Code == "" {
		return fmt.Errorf("empty response: %s", string(bodyBytes))
	}
	switch apiErr.Error.Code {
	case "SetLimitExceeded", "InsufficientQuota", "RateLimitExceeded":
		return fmt.Errorf("%w: code=%s type=%s msg=%s", errQuotaExceeded, apiErr.Error.Code, apiErr.Error.Type, apiErr.Error.Message)
	default:
		return fmt.Errorf("api error: code=%s type=%s msg=%s", apiErr.Error.Code, apiErr.Error.Type, apiErr.Error.Message)
	}
}

func getMimeType(path string) string {
	ext := filepath.Ext(path)
	switch ext {
	case ".png":
		return "image/png"
	case ".jpg", ".jpeg":
		return "image/jpeg"
	case ".webp":
		return "image/webp"
	default:
		return "image/jpeg"
	}
}

func nowTimeString() string {
	return time.Now().Format("2006-01-02 15:04:05")
}

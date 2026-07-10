package service

import (
	"encoding/json"
	"os"
	"path/filepath"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"gopkg.in/yaml.v3"
)

// OpenAPIServer 运行时 OpenAPI 文档服务。
// 读取构建时生成的 openapi.yaml，以 JSON 格式提供给 agent 的 OpenAPIClient 解析。
// 与 EmbeddingServer 一样，不纳入 proto 体系，直接注册原始 HTTP 路由。
type OpenAPIServer struct {
	openapiPath string
}

// NewOpenAPIServer 创建 OpenAPI 服务。
// openapiPath 为 openapi.yaml 的文件路径（相对于工作目录或绝对路径）。
func NewOpenAPIServer(openapiPath string) *OpenAPIServer {
	return &OpenAPIServer{openapiPath: openapiPath}
}

// Reg 向 Kratos HTTP 服务器注册 openapi.json 路由。
func (s *OpenAPIServer) Reg(_ *grpc.Server, httpSrv *khttp.Server) {
	if httpSrv != nil {
		r := httpSrv.Route("/")
		r.GET("/v1/openapi.json", s.handleOpenAPI)
		plogger.Infof("OpenAPI endpoint registered: GET /v1/openapi.json (source: %s)", s.openapiPath)
	}
}

// handleOpenAPI 读取 openapi.yaml，转换为 JSON 并返回。
func (s *OpenAPIServer) handleOpenAPI(ctx khttp.Context) error {
	// 支持相对路径（相对于可执行文件所在目录）
	path := s.openapiPath
	if !filepath.IsAbs(path) {
		if wd, err := os.Getwd(); err == nil {
			path = filepath.Join(wd, path)
		}
	}

	data, err := os.ReadFile(path)
	if err != nil {
		plogger.Warnf("Failed to read openapi.yaml at %s: %v", path, err)
		_ = ctx.Result(500, map[string]string{
			"error": "openapi.yaml not found, run 'make api' to generate",
		})
		return nil
	}

	// yaml → map → json
	var doc map[string]any
	if err := yaml.Unmarshal(data, &doc); err != nil {
		plogger.Warnf("Failed to parse openapi.yaml: %v", err)
		_ = ctx.Result(500, map[string]string{"error": "failed to parse openapi.yaml"})
		return nil
	}

	// 修正 servers 字段：yaml 解析后可能是深层嵌套的 map 结构

	jsonData, err := json.Marshal(doc)
	if err != nil {
		plogger.Warnf("Failed to marshal openapi doc to JSON: %v", err)
		_ = ctx.Result(500, map[string]string{"error": "failed to marshal openapi doc"})
		return nil
	}

	ctx.Response().Header().Set("Content-Type", "application/json")
	_, _ = ctx.Response().Write(jsonData)
	return nil
}

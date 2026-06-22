package config

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/pancake-lee/pgo/pkg/pconfig"
	"github.com/pancake-lee/pgo/pkg/putil"
)

// ServerConfig 服务器配置
type ServerConfig struct {
	Addr string `json:"addr" toml:"addr" default:":8080"`
}

// DBConfig 数据库配置
type DBConfig struct {
	SqlitePath string `json:"sqlite_path" toml:"sqlite_path" default:"./data/sqlite/photo_agent.db"`
}

// StorageConfig 存储配置
type StorageConfig struct {
	ProjectRoot      string `json:"project_root" toml:"project_root" default:"."`
	PhotoPath        string `json:"photo_path" toml:"photo_path" default:"./data/photos"`
	PhotoSrc         string `json:"photo_src" toml:"photo_src"` // 原始照片源目录（batch_vlm 默认输入）
	DescriptionsPath string `json:"descriptions_path" toml:"descriptions_path" default:"./data/descriptions.json"`
	TimelinePath     string `json:"timeline_path" toml:"timeline_path"`
}

// VLMConfig VLM 配置
type VLMConfig struct {
	Provider       string `json:"provider" toml:"provider" default:"openai"`
	APIKey         string `json:"api_key" toml:"api_key"`
	Model          string `json:"model" toml:"model" default:"gpt-4o-mini"`
	BaseURL        string `json:"base_url" toml:"base_url" default:"https://api.openai.com/v1"`
	Concurrency    int    `json:"concurrency" toml:"concurrency" default:"3"`
	Retry          int    `json:"retry" toml:"retry" default:"3"`
	MaxImageSizeMB float64 `json:"max_image_size_mb" toml:"max_image_size_mb" default:"1"`
	Prompt         string `json:"prompt" toml:"prompt"`
}

// EmbeddingConfig Embedding 代理配置
type EmbeddingConfig struct {
	APIKey  string `json:"api_key" toml:"api_key"`
	Model   string `json:"model" toml:"model" default:"doubao-embedding-vision-251215"`
	BaseURL string `json:"base_url" toml:"base_url" default:"https://ark.cn-beijing.volces.com/api/v3"`
}

// DifyConfig Dify 配置
type DifyConfig struct {
	APIKey      string `json:"api_key" toml:"api_key"`
	BaseURL     string `json:"base_url" toml:"base_url" default:"http://localhost/v1"`
	DatasetID   string `json:"dataset_id" toml:"dataset_id"`
	Email       string `json:"email" toml:"email"`
	Password    string `json:"password" toml:"password"`
	DatasetName string `json:"dataset_name" toml:"dataset_name" default:"照片描述库"`
	DBPath      string `json:"db_path" toml:"db_path"`
}

// Config 全局配置
type Config struct {
	Server    ServerConfig
	DB        DBConfig
	Storage   StorageConfig
	VLM       VLMConfig
	Embedding EmbeddingConfig
	Dify      DifyConfig
}

var globalConfig Config

// Init 初始化配置，加载配置文件
func Init(paths ...string) error {
	if len(paths) == 0 {
		paths = append(paths, filepath.Join(putil.GetExecFolder(), "configs"))
	}

	if err := pconfig.InitConfig(paths...); err != nil {
		fmt.Println("config load warning:", err)
	}

	if err := pconfig.Scan(&globalConfig); err != nil {
		return fmt.Errorf("scan config failed: %w", err)
	}

	// 将 project_root 解析为绝对路径（对齐 Python 端 pathlib.Path.resolve() 行为）
	if globalConfig.Storage.ProjectRoot != "" && !filepath.IsAbs(globalConfig.Storage.ProjectRoot) {
		if absRoot, err := filepath.Abs(globalConfig.Storage.ProjectRoot); err == nil {
			globalConfig.Storage.ProjectRoot = absRoot
		}
	}

	// 确保数据目录存在
	ensureDir(globalConfig.ResolvePath(globalConfig.DB.SqlitePath))
	ensureDir(globalConfig.ResolvePath(globalConfig.Storage.PhotoPath))

	return nil
}

// Get 获取全局配置
func Get() *Config {
	return &globalConfig
}

// ResolvePath 将相对路径基于 project_root 解析为绝对路径。
// 如果路径已是绝对路径，直接返回原值。
func (c *Config) ResolvePath(relPath string) string {
	if relPath == "" {
		return relPath
	}
	if filepath.IsAbs(relPath) {
		return relPath
	}
	return filepath.Join(c.Storage.ProjectRoot, relPath)
}

func ensureDir(path string) {
	dir := filepath.Dir(path)
	if dir != "" && dir != "." {
		_ = os.MkdirAll(dir, 0755)
	}
}

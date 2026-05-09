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
	Addr string `default:":8080"`
}

// DBConfig 数据库配置
type DBConfig struct {
	SqlitePath string `toml:"sqlite_path" default:"./data/sqlite/photo_agent.db"`
}

// StorageConfig 存储配置
type StorageConfig struct {
	PhotoPath         string `toml:"photo_path" default:"./data/photos"`
	DescriptionsPath  string `toml:"descriptions_path" default:"./data/descriptions.json"`
}

// VLMConfig VLM 配置
type VLMConfig struct {
	Provider    string `default:"openai"`
	APIKey      string `toml:"api_key"`
	Model       string `default:"gpt-4o-mini"`
	BaseURL     string `toml:"base_url" default:"https://api.openai.com/v1"`
	Concurrency int    `default:"3"`
	Retry       int    `default:"3"`
}

// DifyConfig Dify 配置
type DifyConfig struct {
	APIKey    string `toml:"api_key"`
	BaseURL   string `toml:"base_url" default:"http://localhost/v1"`
	DatasetID string `toml:"dataset_id"`
}

// Config 全局配置
type Config struct {
	Server  ServerConfig
	DB      DBConfig
	Storage StorageConfig
	VLM     VLMConfig
	Dify    DifyConfig
}

var globalConfig Config

// Init 初始化配置，加载配置文件和环境变量
func Init(paths ...string) error {
	if len(paths) == 0 {
		paths = append(paths, filepath.Join(putil.GetExecFolder(), "configs"))
	}

	if err := pconfig.InitConfig(paths...); err != nil {
		// 配置文件不存在时仅记录日志，不报错（环境变量优先）
		fmt.Println("config load warning:", err)
	}

	if err := pconfig.Scan(&globalConfig); err != nil {
		return fmt.Errorf("scan config failed: %w", err)
	}

	// 环境变量覆盖：支持 PHOTO_AGENT_ 前缀
	overrideFromEnv(&globalConfig)

	// 确保数据目录存在
	ensureDir(globalConfig.DB.SqlitePath)
	ensureDir(globalConfig.Storage.PhotoPath)

	return nil
}

// Get 获取全局配置
func Get() *Config {
	return &globalConfig
}

// overrideFromEnv 用环境变量覆盖配置
func overrideFromEnv(cfg *Config) {
	if v := os.Getenv("PHOTO_AGENT_PORT"); v != "" {
		cfg.Server.Addr = ":" + v
	}
	if v := os.Getenv("PHOTO_AGENT_DB_PATH"); v != "" {
		cfg.DB.SqlitePath = v
	}
	if v := os.Getenv("PHOTO_AGENT_PHOTO_PATH"); v != "" {
		cfg.Storage.PhotoPath = v
	}
	if v := os.Getenv("PHOTO_AGENT_VLM_PROVIDER"); v != "" {
		cfg.VLM.Provider = v
	}
	if v := os.Getenv("PHOTO_AGENT_VLM_API_KEY"); v != "" {
		cfg.VLM.APIKey = v
	}
	if v := os.Getenv("PHOTO_AGENT_VLM_MODEL"); v != "" {
		cfg.VLM.Model = v
	}
	if v := os.Getenv("PHOTO_AGENT_VLM_BASE_URL"); v != "" {
		cfg.VLM.BaseURL = v
	}
	if v := os.Getenv("PHOTO_AGENT_DIFY_API_KEY"); v != "" {
		cfg.Dify.APIKey = v
	}
	if v := os.Getenv("PHOTO_AGENT_DIFY_BASE_URL"); v != "" {
		cfg.Dify.BaseURL = v
	}
	if v := os.Getenv("PHOTO_AGENT_DIFY_DATASET_ID"); v != "" {
		cfg.Dify.DatasetID = v
	}
}

func ensureDir(path string) {
	dir := filepath.Dir(path)
	if dir != "" && dir != "." {
		_ = os.MkdirAll(dir, 0755)
	}
}

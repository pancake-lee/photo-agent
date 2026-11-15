package conf

// Config 服务配置，包含整个服务所有需要的配置字段
type Config struct {
	Storage struct {
		ProjectRoot        string
		PhotoPath          string `default:"./data/photos"`
		PhotoSrc           string `default:"./data/photos_src"`
		TimelineWindowDays int    `default:"7"`
	}
	VLM struct {
		MaxImageSizeMB float64 `default:"1"`
		APIKey         string
		Model          string
		BaseURL        string
		Prompt         string
	}
	Embedding struct {
		APIKey  string
		Model   string `default:"doubao-embedding-vision-251215"`
		BaseURL string `default:"https://ark.cn-beijing.volces.com/api/v3"`
	}
}

// C 全局服务配置，在 main 中通过 pconfig.Scan 填充
var C Config

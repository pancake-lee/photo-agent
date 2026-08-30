package conf

// Config 服务配置，包含整个服务所有需要的配置字段
type Config struct {
	Storage struct {
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
	// Burst 连拍分组阈值分精细/模糊两档，此处为初始默认值。
	// 运行期实际生效值以 app_settings 表为准（网页设置页编辑），DB 无记录时回退这里的默认值。
	Burst struct {
		Fine struct {
			TimeWindowSec int     `default:"5"`    // 相邻两张拍摄间隔阈值
			HashThreshold int     `default:"10"`   // dHash 汉明距离阈值（64bit，0-64）
			SsimThreshold float64 `default:"0.85"` // 灰区二次验证阈值
			SsimGrayMin   int     `default:"8"`    // 触发 SSIM 验证的哈希距离下界
			SsimGrayMax   int     `default:"12"`   // 触发 SSIM 验证的哈希距离上界
		}
		Coarse struct {
			TimeWindowSec int     `default:"30"`  // 模糊档：更大时间窗，同场景多次快门归一组
			HashThreshold int     `default:"18"`  // 更宽松的相似度判定
			SsimThreshold float64 `default:"0.6"` // 更宽松的灰区验证
			SsimGrayMin   int     `default:"12"`
			SsimGrayMax   int     `default:"24"`
		}
	}
}

// C 全局服务配置，在 main 中通过 pconfig.Scan 填充
var C Config

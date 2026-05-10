package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/pancake-lee/photo-agent/internal/config"
	"github.com/pancake-lee/photo-agent/internal/model"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"

	"github.com/glebarez/sqlite"
	"gorm.io/gorm"
)

// DifyClient Dify API 客户端
type DifyClient struct {
	BaseURL     string
	Email       string
	Password    string
	AuthToken   string
	DatasetID   string
	DatasetKey  string
}

// LoginResponse 登录响应
type LoginResponse struct {
	Data struct {
		AccessToken string `json:"access_token"`
	} `json:"data"`
}

// Dataset 数据集信息
type Dataset struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// DatasetListResponse 数据集列表响应
type DatasetListResponse struct {
	Data []Dataset `json:"data"`
}

// CreateDatasetResponse 创建数据集响应
type CreateDatasetResponse struct {
	Data Dataset `json:"data"`
}

// DocumentResponse 文档响应
type DocumentResponse struct {
	Data struct {
		ID            string `json:"id"`
		IndexingStatus string `json:"indexing_status"`
	} `json:"data"`
}

// IndexingStatusResponse 索引状态响应
type IndexingStatusResponse struct {
	Data struct {
		IndexingStatus string `json:"indexing_status"`
	} `json:"data"`
}

var (
	flagConfigFile = flag.String("config", "", "配置文件路径")
	flagDifyURL    = flag.String("dify-url", "http://localhost", "Dify 地址")
	flagEmail      = flag.String("email", "", "Dify 管理员邮箱")
	flagPassword   = flag.String("password", "", "Dify 管理员密码")
	flagDatasetName = flag.String("dataset-name", "照片描述库", "知识库名称")
	flagDBPath     = flag.String("db-path", "", "SQLite 数据库路径（覆盖配置）")
)

func main() {
	flag.Parse()

	// 加载配置
	cfgPaths := []string{}
	if *flagConfigFile != "" {
		cfgPaths = append(cfgPaths, *flagConfigFile)
	}
	if err := config.Init(cfgPaths...); err != nil {
		plogger.Fatalf("加载配置失败: %v", err)
	}

	// 检查必要参数
	if *flagEmail == "" || *flagPassword == "" {
		fmt.Println("用法: init_dify --email <邮箱> --password <密码> [选项]")
		fmt.Println()
		fmt.Println("必选参数:")
		fmt.Println("  --email     Dify 管理员邮箱")
		fmt.Println("  --password  Dify 管理员密码")
		fmt.Println()
		fmt.Println("可选参数:")
		fmt.Println("  --config        配置文件路径")
		fmt.Println("  --dify-url      Dify 地址 (默认: http://localhost)")
		fmt.Println("  --dataset-name  知识库名称 (默认: 照片描述库)")
		fmt.Println("  --db-path       SQLite 数据库路径")
		os.Exit(1)
	}

	client := &DifyClient{
		BaseURL:  strings.TrimSuffix(*flagDifyURL, "/"),
		Email:    *flagEmail,
		Password: *flagPassword,
	}

	// 1. 登录获取 token
	plogger.Info("正在登录 Dify...")
	if err := client.login(); err != nil {
		plogger.Fatalf("登录失败: %v", err)
	}
	plogger.Info("登录成功")

	// 2. 查找或创建数据集
	plogger.Infof("查找知识库: %s", *flagDatasetName)
	dataset, err := client.findOrCreateDataset(*flagDatasetName)
	if err != nil {
		plogger.Fatalf("创建知识库失败: %v", err)
	}
	client.DatasetID = dataset.ID
	plogger.Infof("知识库 ID: %s", client.DatasetID)

	// 3. 获取数据集的 API key
	plogger.Info("获取知识库 API key...")
	if err := client.fetchDatasetAPIKey(); err != nil {
		plogger.Warnf("获取知识库 API key 失败: %v", err)
		plogger.Warn("请手动在 Dify UI 中进入知识库 → API 页面，获取 API Key 后设置到配置中")
	}

	// 4. 读取 SQLite 照片数据
	dbPath := *flagDBPath
	if dbPath == "" {
		dbPath = config.Get().DB.SqlitePath
	}
	photos, err := loadPhotosFromDB(dbPath)
	if err != nil {
		plogger.Fatalf("读取照片数据失败: %v", err)
	}
	if len(photos) == 0 {
		plogger.Info("数据库中没有照片记录，无需上传")
		os.Exit(0)
	}
	plogger.Infof("从数据库读取 %d 张照片", len(photos))

	// 5. 批量上传照片描述到知识库
	plogger.Info("开始上传照片描述到知识库...")
	docIDs, err := client.uploadPhotos(photos)
	if err != nil {
		plogger.Fatalf("上传文档失败: %v", err)
	}
	plogger.Infof("已上传 %d 篇文档", len(docIDs))

	// 6. 轮询索引状态
	if len(docIDs) > 0 {
		plogger.Info("等待文档索引完成...")
		if err := client.waitForIndexing(docIDs); err != nil {
			plogger.Warnf("索引等待出错: %v", err)
		}
	}

	// 7. 输出配置摘要
	fmt.Println()
	fmt.Println("=== Dify 初始化完成 ===")
	fmt.Printf("知识库名称: %s\n", *flagDatasetName)
	fmt.Printf("知识库 ID:   %s\n", client.DatasetID)
	fmt.Printf("上传文档数:  %d\n", len(docIDs))
	fmt.Println()
	fmt.Println("下一步：")
	fmt.Println("1. 在 Dify UI 中创建 Agent 应用")
	fmt.Println("2. 绑定知识库（Dataset ID 见上）")
	fmt.Println("3. 导入自定义工具（使用 docs/dify_tools_openapi.yaml）")
	fmt.Println("4. 配置系统提示词并发布")
}

// login 登录获取 auth token
func (c *DifyClient) login() error {
	body := map[string]string{
		"email":    c.Email,
		"password": c.Password,
	}

	req, err := putil.NewHttpRequestJson("POST", c.BaseURL+"/console/api/login", nil, nil, body)
	if err != nil {
		return fmt.Errorf("构建请求失败: %w", err)
	}

	respBody, err := putil.HttpDo(req)
	if err != nil {
		return fmt.Errorf("请求失败: %w", err)
	}

	var result LoginResponse
	if err := json.Unmarshal(respBody, &result); err != nil {
		return fmt.Errorf("解析响应失败: %w", err)
	}

	if result.Data.AccessToken == "" {
		return fmt.Errorf("登录响应中未找到 access_token")
	}

	c.AuthToken = result.Data.AccessToken
	return nil
}

// findOrCreateDataset 查找或创建数据集
func (c *DifyClient) findOrCreateDataset(name string) (*Dataset, error) {
	// 先列出已有数据集
	req, err := putil.NewHttpRequest("GET", c.BaseURL+"/console/api/datasets?page=1&limit=100", map[string]string{
		"Authorization": "Bearer " + c.AuthToken,
	}, nil, "")
	if err != nil {
		return nil, err
	}

	respBody, err := putil.HttpDo(req)
	if err != nil {
		return nil, fmt.Errorf("列出数据集失败: %w", err)
	}

	var list DatasetListResponse
	if err := json.Unmarshal(respBody, &list); err == nil {
		for _, d := range list.Data {
			if d.Name == name {
				plogger.Infof("找到已有知识库: %s", d.ID)
				return &d, nil
			}
		}
	}

	// 创建新数据集
	body := map[string]any{
		"name":               name,
		"permission":         "only_me",
		"indexing_technique": "high_quality",
	}

	req, err = putil.NewHttpRequestJson("POST", c.BaseURL+"/console/api/datasets", map[string]string{
		"Authorization": "Bearer " + c.AuthToken,
	}, nil, body)
	if err != nil {
		return nil, err
	}

	respBody, err = putil.HttpDo(req)
	if err != nil {
		return nil, fmt.Errorf("创建数据集失败: %w", err)
	}

	var result CreateDatasetResponse
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("解析创建响应失败: %w, body=%s", err, string(respBody))
	}

	if result.Data.ID == "" {
		return nil, fmt.Errorf("创建数据集响应中未找到 ID, body=%s", string(respBody))
	}

	plogger.Infof("创建新知识库: %s", result.Data.ID)
	return &result.Data, nil
}

// fetchDatasetAPIKey 获取数据集的 Service API key
func (c *DifyClient) fetchDatasetAPIKey() error {
	req, err := putil.NewHttpRequest("GET", c.BaseURL+"/console/api/datasets/"+c.DatasetID+"/api-keys", map[string]string{
		"Authorization": "Bearer " + c.AuthToken,
	}, nil, "")
	if err != nil {
		return err
	}

	respBody, err := putil.HttpDo(req)
	if err != nil {
		return err
	}

	var result struct {
		Data []struct {
			Token string `json:"token"`
		} `json:"data"`
	}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return fmt.Errorf("解析 API key 响应失败: %w", err)
	}

	if len(result.Data) > 0 {
		c.DatasetKey = result.Data[0].Token
		return nil
	}

	// 没有现有 key，创建一个
	req, err = putil.NewHttpRequestJson("POST", c.BaseURL+"/console/api/datasets/"+c.DatasetID+"/api-keys", map[string]string{
		"Authorization": "Bearer " + c.AuthToken,
	}, nil, map[string]any{})
	if err != nil {
		return err
	}

	respBody, err = putil.HttpDo(req)
	if err != nil {
		return err
	}

	var createResult struct {
		Data struct {
			Token string `json:"token"`
		} `json:"data"`
	}
	if err := json.Unmarshal(respBody, &createResult); err != nil {
		return fmt.Errorf("解析创建 API key 响应失败: %w", err)
	}

	c.DatasetKey = createResult.Data.Token
	return nil
}

// uploadPhotos 批量上传照片描述到知识库
func (c *DifyClient) uploadPhotos(photos []model.Photo) ([]string, error) {
	var docIDs []string

	for i, photo := range photos {
		// 构建文档内容
		content := photo.Description
		if content == "" {
			content = "暂无描述"
		}

		// 元数据
		metaData := map[string]string{}
		if photo.Timeline != "" {
			metaData["timeline"] = photo.Timeline
		}
		if photo.Tags != "" {
			metaData["tags"] = photo.Tags
		}

		body := map[string]any{
			"name":    fmt.Sprintf("照片 %s", photo.ID),
			"text":    content,
			"indexing_technique": "high_quality",
			"process_rule": map[string]any{
				"mode": "automatic",
			},
		}

		// 如果有元数据，添加到 body
		if len(metaData) > 0 {
			body["doc_metadata"] = metaData
		}

		// 上传文档（优先使用 Dataset API key）
		var headers map[string]string
		if c.DatasetKey != "" {
			headers = map[string]string{
				"Authorization": "Bearer " + c.DatasetKey,
			}
		} else {
			headers = map[string]string{
				"Authorization": "Bearer " + c.AuthToken,
			}
		}

		req, err := putil.NewHttpRequestJson("POST", c.BaseURL+"/v1/datasets/"+c.DatasetID+"/document/create_by_text", headers, nil, body)
		if err != nil {
			plogger.Warnf("[%d/%d] 构建请求失败 %s: %v", i+1, len(photos), photo.ID, err)
			continue
		}

		respBody, err := putil.HttpDo(req)
		if err != nil {
			plogger.Warnf("[%d/%d] 上传失败 %s: %v", i+1, len(photos), photo.ID, err)
			continue
		}

		var result DocumentResponse
		if err := json.Unmarshal(respBody, &result); err != nil {
			plogger.Warnf("[%d/%d] 解析响应失败 %s: %v", i+1, len(photos), photo.ID, err)
			continue
		}

		if result.Data.ID != "" {
			docIDs = append(docIDs, result.Data.ID)
			if (i+1)%10 == 0 || i == len(photos)-1 {
				plogger.Infof("[%d/%d] 已上传 %d 篇文档", i+1, len(photos), len(docIDs))
			}
		} else {
			plogger.Warnf("[%d/%d] 上传返回空文档 ID %s", i+1, len(photos), photo.ID)
		}

		// 短暂间隔，避免触发速率限制
		time.Sleep(100 * time.Millisecond)
	}

	return docIDs, nil
}

// waitForIndexing 轮询等待文档索引完成
func (c *DifyClient) waitForIndexing(docIDs []string) error {
	maxWait := 300 // 最多等待 300 秒
	interval := 5

	for sec := 0; sec < maxWait; sec += interval {
		time.Sleep(time.Duration(interval) * time.Second)

		completed := 0
		for _, docID := range docIDs {
			req, err := putil.NewHttpRequest("GET", c.BaseURL+"/v1/datasets/"+c.DatasetID+"/documents/"+docID+"/indexing-status", map[string]string{
				"Authorization": "Bearer " + c.DatasetKey,
			}, nil, "")
			if err != nil {
				continue
			}

			respBody, err := putil.HttpDo(req)
			if err != nil {
				continue
			}

			var result IndexingStatusResponse
			if err := json.Unmarshal(respBody, &result); err != nil {
				continue
			}

			if result.Data.IndexingStatus == "completed" {
				completed++
			}
		}

		plogger.Infof("索引进度: %d/%d 完成", completed, len(docIDs))

		if completed == len(docIDs) {
			plogger.Info("所有文档索引完成")
			return nil
		}
	}

	return fmt.Errorf("等待索引超时（%d 秒）", maxWait)
}

// loadPhotosFromDB 从 SQLite 加载照片数据
func loadPhotosFromDB(dbPath string) ([]model.Photo, error) {
	db, err := gorm.Open(sqlite.Open(dbPath), &gorm.Config{})
	if err != nil {
		return nil, fmt.Errorf("打开数据库失败: %w", err)
	}

	var photos []model.Photo
	if err := db.Find(&photos).Error; err != nil {
		return nil, fmt.Errorf("查询照片失败: %w", err)
	}

	return photos, nil
}

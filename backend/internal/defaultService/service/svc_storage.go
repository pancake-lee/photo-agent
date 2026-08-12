package service

import (
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/pkg/db/model"

	"github.com/pancake-lee/pgo/pkg/pdb"
	"github.com/pancake-lee/pgo/pkg/plogger"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

// StorageServer 存储状态查询服务。
type StorageServer struct{}

// Reg 向 Kratos HTTP 服务器注册存储状态路由。
func (s *StorageServer) Reg(_ *grpc.Server, httpSrv *khttp.Server) {
	if httpSrv != nil {
		r := httpSrv.Route("/")
		r.GET("/api/v1/storage/info", s.handleStorageInfo)
	}
}

var monthDirRe = regexp.MustCompile(`^\d{6}$`)
var activityDirRe = regexp.MustCompile(`^\d{6}_.+`)

// storageInfoResp storage/info 响应体。
type storageInfoResp struct {
	Root       string   `json:"root"`
	JpgCount   int64    `json:"jpg_count"`
	NefCount   int64    `json:"nef_count"`
	Months     []string `json:"months"`
	Activities []string `json:"activities"`
	LastSync   string   `json:"last_sync"`
	Warning    string   `json:"warning,omitempty"`
}

// handleStorageInfo 返回存储根目录的状态信息。
func (s *StorageServer) handleStorageInfo(kctx khttp.Context) error {
	root := conf.C.Storage.StorageRoot
	resp := storageInfoResp{
		Root:       root,
		Months:     []string{},
		Activities: []string{},
	}

	// 扫描目录
	entries, err := os.ReadDir(root)
	if err != nil {
		resp.Warning = "storage root not accessible: " + err.Error()
		resp.LastSync = s.queryLastSync()
		return kctx.Result(200, resp)
	}

	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		name := entry.Name()
		switch {
		case monthDirRe.MatchString(name):
			resp.Months = append(resp.Months, name)
		case activityDirRe.MatchString(name):
			resp.Activities = append(resp.Activities, name)
		}
	}

	// 递归统计文件数
	resp.JpgCount, resp.NefCount = countFiles(root)
	resp.LastSync = s.queryLastSync()

	return kctx.Result(200, resp)
}

// queryLastSync 查询照片表中最新的导入时间。
func (s *StorageServer) queryLastSync() string {
	var maxTime time.Time
	g := pdb.GetGormDB()
	if err := g.Model(&model.Photo{}).Select("MAX(imported_at)").Scan(&maxTime).Error; err != nil {
		plogger.Warnf("storage/info query last_sync failed: %v", err)
		return ""
	}
	if maxTime.IsZero() {
		return ""
	}
	return maxTime.UTC().Format(time.RFC3339)
}

// countFiles 递归统计目录下 JPG 和 NEF 文件数。
func countFiles(root string) (jpg, nef int64) {
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			return nil
		}
		ext := strings.ToLower(filepath.Ext(d.Name()))
		switch ext {
		case ".jpg", ".jpeg", ".png", ".webp":
			jpg++
		case ".nef":
			nef++
		}
		return nil
	})
	return
}

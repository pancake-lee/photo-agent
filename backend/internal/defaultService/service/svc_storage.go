package service

import (
	"context"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"

	"github.com/pancake-lee/pgo/pkg/papp"
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
		r.POST("/api/v1/storage/conflicts", s.handleStorageConflicts)
	}
}

var monthDirRe = regexp.MustCompile(`^\d{6}$`)
var activityDirRe = regexp.MustCompile(`^\d{6}-.+`)

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
	plogger.Infof("storage/info request: %s %s", kctx.Request().Method, kctx.Request().URL.Path)
	// 扫描上传落盘使用的 PhotoSrc 作为源文件根目录，使「总文件数/月份/活动目录」统计与上传落盘位置一致。
	root := conf.C.Storage.PhotoSrc
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

// storageConflictsReq 客户端待上传文件名列表。
type storageConflictsReq struct {
	Names []string `json:"names"`
}

// storageConflictsResp 重名文件检查结果。
type storageConflictsResp struct {
	Total    int      `json:"total"`
	Existing []string `json:"existing"`
	New      []string `json:"new"`
}

// handleStorageConflicts 接收客户端待上传文件名列表，返回其中已存在于服务端的重名文件。
// 判重规则与上传时一致：按 sanitizeFilename 清洗后与 photos.filename 精确匹配。
func (s *StorageServer) handleStorageConflicts(kctx khttp.Context) error {
	var req storageConflictsReq
	if err := kctx.Bind(&req); err != nil {
		plogger.Warnf("storage/conflicts bind failed: %v", err)
		return kctx.Result(400, map[string]string{"error": "invalid request body"})
	}
	plogger.Infof("storage/conflicts: %d names", len(req.Names))

	// 先按上传时的 targetFilename 规则清洗并去重，得到需要查重的目标名集合。
	targets := make([]string, 0, len(req.Names))
	seen := make(map[string]struct{}, len(req.Names))
	for _, name := range req.Names {
		ext := strings.ToLower(filepath.Ext(name))
		target := sanitizeFilename(name, ext)
		if _, ok := seen[target]; !ok {
			seen[target] = struct{}{}
			targets = append(targets, target)
		}
	}

	ctx := papp.NewAppCtx(kctx.Request().Context())
	existingSet, err := data.PhotoDAO.GetExistingFilenames(ctx, targets)
	if err != nil {
		return kctx.Result(500, map[string]string{"error": err.Error()})
	}

	resp := storageConflictsResp{Total: len(req.Names), Existing: []string{}, New: []string{}}
	for _, name := range req.Names {
		ext := strings.ToLower(filepath.Ext(name))
		target := sanitizeFilename(name, ext)
		if existingSet[target] {
			resp.Existing = append(resp.Existing, name)
		} else {
			resp.New = append(resp.New, name)
		}
	}
	return kctx.Result(200, resp)
}

// queryLastSync 查询照片表中最新的导入时间。
func (s *StorageServer) queryLastSync() string {
	importedAt, err := data.PhotoDAO.GetLatestPhotoImportTime(papp.NewAppCtx(context.Background()))
	if err != nil {
		plogger.Warnf("storage/info query last_sync failed: %v", err)
		return ""
	}
	if importedAt.IsZero() {
		return ""
	}
	return importedAt.UTC().Format(time.RFC3339)
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

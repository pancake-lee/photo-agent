package service

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"
	"backend/internal/pkg/perr"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

type PhotoServer struct {
	api.UnimplementedPhotoServiceServer
}

// AIAuditHandler 返回批量修复前的只读候选摘要，不修改照片或原始文件。
func (s *PhotoServer) AIAuditHandler(ctx khttp.Context) error {
	photos, err := data.PhotoDAO.GetPhotosForVlmAudit(papp.NewAppCtx(ctx.Request().Context()))
	if err != nil {
		return ctx.Result(500, map[string]string{"error": err.Error()})
	}
	counts := map[string]int{"vlm_missing": 0, "vlm_review": 0, "embedding_missing": 0}
	items := map[string][]map[string]any{"vlm_missing": {}, "vlm_review": {}, "embedding_missing": {}}
	for _, photo := range photos {
		if strings.TrimSpace(photo.Description) == "" {
			counts["vlm_missing"]++
			items["vlm_missing"] = append(items["vlm_missing"], auditPhotoItem(photo, "没有 AI 描述"))
		} else if validationErr := validateVlmDescription(photo.Description); validationErr != nil {
			counts["vlm_review"]++
			items["vlm_review"] = append(items["vlm_review"], auditPhotoItem(photo, validationErr.Error()))
		}
	}
	return ctx.Result(200, map[string]any{
		"total": len(photos), "counts": counts, "items": items, "read_only": true,
		"message": "本地审查未调用 VLM，确认后才会处理候选照片",
	})
}

// ValidateAIHandler 重新执行当前描述的本地质量校验，不调用 VLM，也不写入派生质量结论。
func (s *PhotoServer) ValidateAIHandler(ctx khttp.Context) error {
	id := ctx.Vars().Get("id")
	photo, err := data.PhotoDAO.GetByID(papp.NewAppCtx(ctx.Request().Context()), id)
	if err != nil {
		return ctx.Result(404, map[string]string{"error": "照片不存在"})
	}
	if strings.TrimSpace(photo.Description) == "" {
		return ctx.Result(400, map[string]string{"error": "当前没有可校验的 AI 描述"})
	}
	health, healthReason, vlmStatus, vlmReason, embeddingStatus, _ := derivePhotoAIState(photo)
	return ctx.Result(200, map[string]any{
		"status": health, "reason": healthReason,
		"vlm_status": vlmStatus, "vlm_reason": vlmReason,
		"embedding_status": embeddingStatus,
	})
}

func auditPhotoItem(photo *data.PhotoDO, reason string) map[string]any {
	return map[string]any{
		"id": photo.ID, "filename": photo.Filename,
		"thumbnail_url": fmt.Sprintf("/api/v1/photos/%s/image", photo.ID),
		"reason":        reason,
	}
}

// Reg 向 Kratos gRPC/HTTP 服务器注册本服务。
// HTTP 路由在生成的 RegisterPhotoServiceHTTPServer 基础上，额外注册文件上传和图片 serving。
func (s *PhotoServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if grpcSrv != nil {
		api.RegisterPhotoServiceServer(grpcSrv, s)
	}
	if httpSrv != nil {
		// 额外注册非 proto 映射的原始 HTTP 路由
		r := httpSrv.Route("/")
		// 静态路由必须在生成的 /photos/{id} 之前注册，否则会被当成照片 ID。
		r.GET("/api/v1/photos/ai-audit", s.AIAuditHandler)
		// 手动注册的上传/图片路由
		r.GET("/api/v1/photos/{id}/image", s.GetPhotoImageHandler)
		r.POST("/api/v1/photos/upload", s.UploadPhotoHandler)
		r.POST("/api/v1/photos/{id}/ai-health", s.UpdateAIHealthHandler)
		r.POST("/api/v1/photos/{id}/ai-validate", s.ValidateAIHandler)

		api.RegisterPhotoServiceHTTPServer(httpSrv, s)
	}
}

// ================================================================
// PhotoService proto 接口实现
// ================================================================

// SearchPhotos 复杂条件分页查询
func (s *PhotoServer) SearchPhotos(
	_ctx context.Context, req *api.SearchPhotosRequest,
) (*api.SearchPhotosResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	params := data.GetPhotoListParams{
		Page:         int(req.Page),
		PageSize:     int(req.PageSize),
		Timeline:     req.Timeline,
		Tag:          req.Tag,
		Keyword:      req.Keyword,
		Brand:        req.Brand,
		Lens:         req.Lens,
		FocalMin:     req.FocalMin,
		FocalMax:     req.FocalMax,
		ISOMin:       req.IsoMin,
		ISOMax:       req.IsoMax,
		ShotAtStart:  req.ShotAtStart,
		ShotAtEnd:    req.ShotAtEnd,
		SortBy:       req.SortBy,
		SortOrder:    req.SortOrder,
		BurstGroupID: req.BurstGroupId,
		BurstProfile: req.BurstProfile,
	}

	photos, total, err := data.PhotoDAO.GetPhotoList(ctx, params)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 规范化 page_size（与 DAO 层截断一致），确保 totalPages 计算正确
	if params.PageSize < 1 {
		params.PageSize = 20
	}
	if params.PageSize > 100 {
		params.PageSize = 100
	}

	// NEF 只是与 JPG 同目录的原始附件，不建照片记录。列表按当前原图目录
	// 动态检测同名 .nef（扩展名不区分大小写），只用于图片管理卡片角标。
	nefSet := adjacentNefSet(photos)

	// 连拍组信息，用于拼装 burst_cover/burst_count。查询失败时映射为空，仅不显示角标。
	// burst 字段按本次请求的档位取对应分组列（缺省精细档）。
	groupMap, _ := data.PhotoGroupDAO.GetByIDList(ctx, burstGroupIDsOf(photos, req.BurstProfile))

	items := make([]*api.PhotoItem, len(photos))
	for i, p := range photos {
		items[i] = photoDO2Item(p)
		items[i].HasNef = nefSet[photoBasePath(p.FilePath)]
		groupID := p.BurstGroupID
		if req.BurstProfile == "coarse" {
			groupID = p.BurstGroupCoarseID
		}
		if g := groupMap[groupID]; g != nil {
			items[i].BurstGroupId = groupID
			items[i].BurstCover = g.CoverPhotoID == p.ID
			items[i].BurstCount = g.PhotoCount
		}
	}

	totalPages := int32(0)
	if params.PageSize > 0 {
		totalPages = int32((int(total) + params.PageSize - 1) / params.PageSize)
	}

	return &api.SearchPhotosResponse{
		Items:      items,
		Total:      total,
		Page:       int32(params.Page),
		PageSize:   int32(params.PageSize),
		TotalPages: totalPages,
	}, nil
}

// ListPhotoSegments 分段导航：返回当前筛选 + 排序下每个分段的 key/label/count/offset。
func (s *PhotoServer) ListPhotoSegments(
	_ctx context.Context, req *api.ListPhotoSegmentsRequest,
) (*api.ListPhotoSegmentsResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	params := data.GetPhotoListParams{
		Timeline:     req.Timeline,
		Tag:          req.Tag,
		Keyword:      req.Keyword,
		Brand:        req.Brand,
		Lens:         req.Lens,
		FocalMin:     req.FocalMin,
		FocalMax:     req.FocalMax,
		ISOMin:       req.IsoMin,
		ISOMax:       req.IsoMax,
		ShotAtStart:  req.ShotAtStart,
		ShotAtEnd:    req.ShotAtEnd,
		SortBy:       req.SortBy,
		SortOrder:    req.SortOrder,
		BurstGroupID: req.BurstGroupId,
		BurstProfile: req.BurstProfile,
	}

	mode := data.SegmentMode(req.SegmentMode)
	if mode != data.SegmentModeActivity {
		mode = data.SegmentModeMonth
	}

	segments, total, err := data.PhotoDAO.ListPhotoSegments(ctx, params, mode)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	resp := &api.ListPhotoSegmentsResponse{Total: total}
	for _, seg := range segments {
		resp.Segments = append(resp.Segments, &api.PhotoSegment{
			Key:    seg.Key,
			Label:  seg.Label,
			Count:  seg.Count,
			Offset: seg.Offset,
		})
	}
	return resp, nil
}

// GetPhotoStats 综合统计
func (s *PhotoServer) GetPhotoStats(
	_ctx context.Context, _ *api.Empty,
) (*api.GetPhotoStatsResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	stats, err := data.PhotoDAO.GetPhotoStats(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	resp := &api.GetPhotoStatsResponse{
		Total:              stats.Total,
		WithDescription:    stats.WithDescription,
		WithoutDescription: stats.WithoutDescription,
		Gps: &api.GPSStat{
			WithGps:    stats.GPS.WithGPS,
			WithoutGps: stats.GPS.WithoutGPS,
		},
	}

	for _, b := range stats.Brands {
		resp.Brands = append(resp.Brands, &api.StatItem{Name: b.Name, Count: b.Count})
	}
	for _, l := range stats.Lens {
		resp.Lens = append(resp.Lens, &api.StatItem{Name: l.Name, Count: l.Count})
	}
	for _, f := range stats.FocalRanges {
		resp.FocalRanges = append(resp.FocalRanges, &api.FocalRangeStat{
			Range: f.Range, Label: f.Label, Count: f.Count,
		})
	}
	for _, m := range stats.Monthly {
		resp.Monthly = append(resp.Monthly, &api.MonthlyStat{Month: m.Month, Count: m.Count})
	}
	for _, h := range stats.Hourly {
		resp.Hourly = append(resp.Hourly, &api.HourlyStat{Hour: h.Hour, Count: h.Count})
	}

	return resp, nil
}

// GetPhotoDetail 单张照片详情
func (s *PhotoServer) GetPhotoDetail(
	_ctx context.Context, req *api.GetPhotoDetailRequest,
) (*api.GetPhotoDetailResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	photo, err := data.PhotoDAO.GetByID(ctx, req.Id)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	item := photoDO2Item(photo)

	return &api.GetPhotoDetailResponse{
		Photo:            item,
		ImageUrl:         fmt.Sprintf("/api/v1/photos/%s/image", photo.ID),
		DescriptionModel: photo.DescriptionModel,
		DescriptionTime:  photo.DescriptionTime,
	}, nil
}

// UpdateAIHealthHandler 由 Embedding 服务回写照片的向量处理结论。
func (s *PhotoServer) UpdateAIHealthHandler(ctx khttp.Context) error {
	var req struct {
		Status          string `json:"status"`
		Reason          string `json:"reason"`
		DescriptionTime string `json:"description_time"`
	}
	if err := ctx.Bind(&req); err != nil {
		return ctx.Result(400, map[string]string{"error": "invalid request body"})
	}
	if req.Status != aiStatusHealthy && req.Status != aiStatusFailed && req.Status != aiStatusStale {
		return ctx.Result(400, map[string]string{"error": "invalid AI health status"})
	}
	return ctx.Result(410, map[string]string{"error": "AI 状态已改为实时计算，不再接受状态回写"})
}

// UpdatePhotoTags 更新照片标签
func (s *PhotoServer) UpdatePhotoTags(
	_ctx context.Context, req *api.UpdatePhotoTagsRequest,
) (*api.Empty, error) {
	ctx := papp.NewAppCtx(_ctx)

	if err := data.PhotoDAO.UpdateTags(ctx, req.Id, req.Tags); err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	return &api.Empty{}, nil
}

// UpdatePhotoShotAt 修改照片拍摄时间：写 DB + 写 EXIF（源文件）。
func (s *PhotoServer) UpdatePhotoShotAt(
	_ctx context.Context, req *api.UpdatePhotoShotAtRequest,
) (*api.Empty, error) {
	ctx := papp.NewAppCtx(_ctx)

	if req.Id == "" || req.ShotAt <= 0 {
		return nil, ctx.Log.LogErr(perr.ErrParamInvalid)
	}

	shotAt := time.Unix(req.ShotAt, 0)

	photo, err := data.PhotoDAO.GetByID(ctx, req.Id)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 非 NEF 才写回文件 EXIF（NEF 不写回，仅更新 DB）
	if photo.FileType != "nef" {
		if err := writeShotAtToExif(photo.FilePath, shotAt); err != nil {
			plogger.Warnf("UpdatePhotoShotAt: write exif failed %s: %v", photo.FilePath, err)
		}
	}

	if err := data.PhotoDAO.UpdateShotAt(ctx, req.Id, shotAt); err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	return &api.Empty{}, nil
}

// DeletePhoto 删除照片（含文件清理）
func (s *PhotoServer) DeletePhoto(
	_ctx context.Context, req *api.DeletePhotoRequest,
) (*api.DeletePhotoResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	photo, err := data.PhotoDAO.GetByID(ctx, req.Id)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	if err := data.PhotoDAO.DelByID(ctx, req.Id); err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 删除源文件（PhotoSrc）和缩略图（PhotoPath）
	srcPath := filepath.Join(conf.C.Storage.PhotoSrc, photo.FilePath)
	if err := os.Remove(srcPath); err != nil && !os.IsNotExist(err) {
		plogger.Warnf("Failed to delete source file %s: %v", srcPath, err)
	}
	if photo.FileType != "nef" {
		thumbPath := filepath.Join(conf.C.Storage.PhotoPath, photo.FilePath)
		if err := os.Remove(thumbPath); err != nil && !os.IsNotExist(err) {
			plogger.Warnf("Failed to delete thumbnail %s: %v", thumbPath, err)
		}
	}

	return &api.DeletePhotoResponse{
		Status: "deleted",
		Id:     req.Id,
	}, nil
}

// ================================================================
// 原始 HTTP 路由 handler（非 proto 映射）
// ================================================================

// GetPhotoImageHandler 返回图片文件，默认返回缩略图，size=original 时返回源文件。
func (s *PhotoServer) GetPhotoImageHandler(kctx khttp.Context) error {
	id := kctx.Vars().Get("id")

	_ctx := kctx.Request().Context()
	ctx := papp.NewAppCtx(_ctx)

	photo, err := data.PhotoDAO.GetByID(ctx, id)
	if err != nil {
		return err
	}

	original := kctx.Request().URL.Query().Get("size") == "original"
	if photo.FileType == "nef" && !original {
		return kctx.Result(415, map[string]string{"error": "NEF raw files cannot be displayed in browser"})
	}

	basePath := conf.C.Storage.PhotoPath
	if original {
		basePath = conf.C.Storage.PhotoSrc
		if kctx.Request().URL.Query().Get("download") == "1" {
			kctx.Response().Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=\"%s\"", filepath.Base(photo.FilePath)))
		}
	}
	fullPath := filepath.Join(basePath, photo.FilePath)
	http.ServeFile(kctx.Response(), kctx.Request(), fullPath)
	return nil
}

// UploadPhotoHandler 上传图片。
// JPG 流程：保存到 photo_src → 压缩到 photo_path → 读 EXIF → 匹配时间线 → 入库。
// NEF 流程：仅保存到 photo_src，作为同名 JPG 的原始附件。
func (s *PhotoServer) UploadPhotoHandler(kctx khttp.Context) error {
	req := kctx.Request()
	plogger.Infof("upload request: %s %s", req.Method, req.URL.Path)

	if err := req.ParseMultipartForm(32 << 20); err != nil {
		plogger.Warnf("upload parse multipart form failed: %v", err)
		return fmt.Errorf("parse multipart form failed: %w", err)
	}

	originalName := req.FormValue("original_name")
	originalShotAt := req.FormValue("original_shot_at")
	modTimeStr := req.FormValue("mod_time")
	conflictResolution := req.FormValue("conflict_resolution")
	folder := req.FormValue("folder")
	plogger.Infof("upload: name=%s folder=%s", originalName, folder)

	file, header, err := req.FormFile("file")
	if err != nil {
		return fmt.Errorf("missing file field: %w", err)
	}
	defer file.Close()

	ext := strings.ToLower(filepath.Ext(header.Filename))
	if ext == "" {
		ext = ".jpg"
	}
	targetFilename := sanitizeFilename(originalName, ext)
	newShotAt := parseTime(originalShotAt)
	modTime := parseTime(modTimeStr)

	// 回写文件的修改时间：忠实保留客户端文件的原始修改时间，不用拍摄时间覆盖。
	fileMtime := modTime

	_ctx := req.Context()
	ctx := papp.NewAppCtx(_ctx)

	isNEF := ext == ".nef"
	if isNEF {
		status, err := s.storeNefUpload(file, targetFilename, folder, conflictResolution, fileMtime)
		if err != nil {
			return fmt.Errorf("store NEF file failed: %w", err)
		}
		result := map[string]any{"status": status, "photo_id": ""}
		if status == "conflict" {
			result["conflict"] = nefConflictInfo(targetFilename, newShotAt)
		}
		return kctx.Result(200, result)
	}

	// 检查冲突
	existingPhoto, _ := data.PhotoDAO.GetByFilename(ctx, targetFilename)
	if existingPhoto != nil {
		return s.handleConflict(kctx, ctx, file, targetFilename, existingPhoto, newShotAt, conflictResolution, folder, fileMtime)
	}

	// 无冲突：保存 → 入库
	var photoID string
	photoID, err = s.doUpload(ctx, file, targetFilename, folder, newShotAt, fileMtime)
	if err != nil {
		return fmt.Errorf("store photo failed: %w", err)
	}
	plogger.Infof("Photo uploaded: %s -> id=%s", targetFilename, photoID)
	return kctx.Result(200, map[string]any{
		"status":   "stored",
		"photo_id": photoID,
	})
}

// handleConflict 处理上传冲突
func (s *PhotoServer) handleConflict(
	kctx khttp.Context, ctx *papp.AppCtx,
	file interface{ io.Reader }, targetFilename string,
	existingPhoto *data.PhotoDO, newShotAt *time.Time,
	resolution string, folder string, fileMtime *time.Time,
) error {
	if resolution == "" {
		return kctx.Result(200, map[string]any{
			"status":   "conflict",
			"photo_id": "",
			"conflict": buildConflictInfo(existingPhoto, newShotAt),
		})
	}

	switch resolution {
	case "overwrite":
		destDir := conf.C.Storage.PhotoSrc
		if folder != "" {
			destDir = filepath.Join(destDir, folder)
		}
		if err := saveUploadedFile(file, targetFilename, destDir, fileMtime); err != nil {
			return err
		}
		srcPath := filepath.Join(destDir, targetFilename)
		maxBytes := int64(conf.C.VLM.MaxImageSizeMB * 1024 * 1024)
		thumbDir := conf.C.Storage.PhotoPath
		if folder != "" {
			thumbDir = filepath.Join(thumbDir, folder)
		}
		if err := processToPhotoPath(srcPath, targetFilename, thumbDir, maxBytes, fileMtime); err != nil {
			return err
		}
		// 删除旧缩略图
		oldPath := filepath.Join(conf.C.Storage.PhotoPath, existingPhoto.FilePath)
		newThumbPath := filepath.Join(thumbDir, targetFilename)
		if oldPath != newThumbPath {
			_ = os.Remove(oldPath)
		}
		if err := overwritePhoto(ctx, existingPhoto.ID, targetFilename, folder, newShotAt); err != nil {
			return fmt.Errorf("update overwritten photo failed: %w", err)
		}
		return kctx.Result(200, map[string]any{
			"status":   "stored",
			"photo_id": existingPhoto.ID,
		})

	case "skip":
		return kctx.Result(200, map[string]any{
			"status":   "skipped",
			"photo_id": existingPhoto.ID,
		})

	case "keep_both":
		newFilename := addSuffix(targetFilename)
		var photoID string
		var err error
		photoID, err = s.doUpload(ctx, file, newFilename, folder, newShotAt, fileMtime)
		if err != nil {
			return fmt.Errorf("store photo failed: %w", err)
		}
		return kctx.Result(200, map[string]any{
			"status":   "stored",
			"photo_id": photoID,
		})

	default:
		return kctx.Result(400, map[string]any{"error": "invalid conflict_resolution"})
	}
}

// doUpload 执行 JPG 上传流程（保存源文件 + 压缩缩略图 + EXIF + 入库）
func (s *PhotoServer) doUpload(
	ctx *papp.AppCtx, file io.Reader, filename string,
	folder string, shotAt *time.Time, fileMtime *time.Time,
) (string, error) {
	srcDir := conf.C.Storage.PhotoSrc
	thumbDir := conf.C.Storage.PhotoPath
	if folder != "" {
		srcDir = filepath.Join(srcDir, folder)
		thumbDir = filepath.Join(thumbDir, folder)
	}
	if err := saveUploadedFile(file, filename, srcDir, fileMtime); err != nil {
		return "", err
	}

	srcPath := filepath.Join(srcDir, filename)
	thumbPath := filepath.Join(thumbDir, filename)
	maxBytes := int64(conf.C.VLM.MaxImageSizeMB * 1024 * 1024)
	if err := processToPhotoPath(srcPath, filename, thumbDir, maxBytes, fileMtime); err != nil {
		_ = os.Remove(srcPath)
		_ = os.Remove(thumbPath)
		return "", err
	}

	photoID, err := createPhotoRecord(ctx, filename, folder, "jpg", shotAt)
	if err != nil {
		_ = os.Remove(srcPath)
		_ = os.Remove(thumbPath)
		return "", err
	}
	return photoID, nil
}

// storeNefUpload 将 NEF 原始文件保存到与 JPG 相同的源目录，不创建照片记录。
func (s *PhotoServer) storeNefUpload(
	file io.Reader, filename string, folder string, resolution string, fileMtime *time.Time,
) (string, error) {
	srcDir := conf.C.Storage.PhotoSrc
	if folder != "" {
		srcDir = filepath.Join(srcDir, folder)
	}
	existing, err := caseInsensitiveFileName(srcDir, filename)
	if err != nil {
		return "", err
	}
	if existing != "" {
		switch resolution {
		case "":
			return "conflict", nil
		case "skip":
			return "skipped", nil
		case "overwrite":
			filename = existing
		case "keep_both":
			for candidate := addSuffix(filename); ; candidate = addSuffix(candidate) {
				found, lookupErr := caseInsensitiveFileName(srcDir, candidate)
				if lookupErr != nil {
					return "", lookupErr
				}
				if found == "" {
					filename = candidate
					break
				}
			}
		default:
			return "", perr.ErrParamInvalid
		}
	}
	if err := saveUploadedFile(file, filename, srcDir, fileMtime); err != nil {
		return "", err
	}
	return "stored", nil
}

// ================================================================
// 辅助函数
// ================================================================

// burstGroupIDsOf 收集照片列表中出现的非空连拍组 id（去重），按档位取对应分组列。
func burstGroupIDsOf(photos []*data.PhotoDO, profile string) []string {
	seen := make(map[string]bool)
	idList := make([]string, 0, len(photos))
	for _, p := range photos {
		groupID := p.BurstGroupID
		if profile == "coarse" {
			groupID = p.BurstGroupCoarseID
		}
		if groupID != "" && !seen[groupID] {
			seen[groupID] = true
			idList = append(idList, groupID)
		}
	}
	return idList
}

// adjacentNefSet 扫描当前页照片所在目录，建立「相对目录 + 小写基础名」集合。
// NEF 文件本身不是数据库实体，因此角标始终以原图目录的实时状态为准。
func adjacentNefSet(photos []*data.PhotoDO) map[string]bool {
	dirs := make(map[string]bool)
	for _, photo := range photos {
		dirs[filepath.Dir(photo.FilePath)] = true
	}
	set := make(map[string]bool)
	for dir := range dirs {
		entries, err := os.ReadDir(filepath.Join(conf.C.Storage.PhotoSrc, dir))
		if err != nil {
			continue
		}
		for _, entry := range entries {
			if entry.IsDir() || !strings.EqualFold(filepath.Ext(entry.Name()), ".nef") {
				continue
			}
			set[photoBasePath(filepath.Join(dir, entry.Name()))] = true
		}
	}
	return set
}

func photoBasePath(relPath string) string {
	return filepath.ToSlash(filepath.Join(filepath.Dir(relPath), data.BaseNameOf(filepath.Base(relPath))))
}

// caseInsensitiveFileName 返回目录内与 filename 忽略大小写匹配的实际文件名。
func caseInsensitiveFileName(dir, filename string) (string, error) {
	entries, err := os.ReadDir(dir)
	if os.IsNotExist(err) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	for _, entry := range entries {
		if !entry.IsDir() && strings.EqualFold(entry.Name(), filename) {
			return entry.Name(), nil
		}
	}
	return "", nil
}

func photoDO2Item(do *data.PhotoDO) *api.PhotoItem {
	if do == nil {
		return nil
	}
	health, healthReason, vlmStatus, vlmReason, embeddingStatus, _ := derivePhotoAIState(do)
	item := &api.PhotoItem{
		Id:                       do.ID,
		Filename:                 do.Filename,
		FilePath:                 do.FilePath,
		Timeline:                 do.Timeline,
		Tags:                     do.Tags,
		Description:              do.Description,
		Objects:                  do.Objects,
		Colors:                   do.Colors,
		Scene:                    do.Scene,
		Lighting:                 do.Lighting,
		Mood:                     do.Mood,
		Composition:              do.Composition,
		Width:                    do.Width,
		Height:                   do.Height,
		Brand:                    do.Brand,
		Model:                    do.Model,
		Lens:                     do.Lens,
		FocalLength:              do.FocalLength,
		Aperture:                 do.Aperture,
		Iso:                      do.Iso,
		ExposureTime:             do.ExposureTime,
		Latitude:                 do.Latitude,
		Longitude:                do.Longitude,
		Altitude:                 do.Altitude,
		HasDescription:           do.Description != "",
		ThumbnailUrl:             fmt.Sprintf("/api/v1/photos/%s/image", do.ID),
		AiHealthStatus:           health,
		AiHealthReason:           healthReason,
		VlmStatus:                vlmStatus,
		VlmReason:                vlmReason,
		EmbeddingStatus:          embeddingStatus,
		EmbeddingDescriptionTime: do.EmbeddingDescriptionTime,
	}
	if !do.ShotAt.IsZero() {
		item.ShotAt = do.ShotAt.Unix()
	}
	if !do.ImportedAt.IsZero() {
		item.ImportedAt = do.ImportedAt.Unix()
	}
	return item
}

// derivePhotoAIState 将当前描述质量作为即时派生结论，避免历史质量状态成为准入依据。
// Embedding 处理状态和描述版本仍来自持久化记录，因为它们描述实际处理结果。
func derivePhotoAIState(photo *data.PhotoDO) (health, healthReason, vlmStatus, vlmReason, embeddingStatus, embeddingDescriptionTime string) {
	if strings.TrimSpace(photo.Description) == "" {
		return aiStatusPending, "没有 AI 描述", aiStatusPending, "", "unknown", ""
	}
	if validationErr := validateVlmDescription(photo.Description); validationErr != nil {
		return aiStatusReview, validationErr.Error(), aiStatusReview, validationErr.Error(), "unknown", ""
	}
	return aiStatusHealthy, "", aiStatusHealthy, "", "unknown", ""
}

func parseTime(s string) *time.Time {
	if s == "" {
		return nil
	}
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		return nil
	}
	return &t
}

func buildConflictInfo(existing *data.PhotoDO, newShotAt *time.Time) map[string]any {
	existingShotAt := ""
	if !existing.ShotAt.IsZero() {
		existingShotAt = existing.ShotAt.UTC().Format(time.RFC3339)
	}
	newShotAtStr := ""
	if newShotAt != nil {
		newShotAtStr = newShotAt.UTC().Format(time.RFC3339)
	}
	return map[string]any{
		"existing_photo_id":  existing.ID,
		"existing_filename":  existing.Filename,
		"existing_image_url": fmt.Sprintf("/api/v1/photos/%s/image", existing.ID),
		"existing_shot_at":   existingShotAt,
		"new_shot_at":        newShotAtStr,
	}
}

func nefConflictInfo(filename string, newShotAt *time.Time) map[string]any {
	newShotAtStr := ""
	if newShotAt != nil {
		newShotAtStr = newShotAt.UTC().Format(time.RFC3339)
	}
	return map[string]any{
		"existing_photo_id":  "",
		"existing_filename":  filename,
		"existing_image_url": "",
		"existing_shot_at":   "",
		"new_shot_at":        newShotAtStr,
	}
}

func createPhotoRecord(ctx *papp.AppCtx, filename string, folder string, fileType string, shotAt *time.Time) (string, error) {
	relPath := filename
	if folder != "" {
		relPath = filepath.Join(folder, filename)
	}

	// 尺寸与 EXIF 统一从源文件（原图）读取，避免读缩略图（PhotoPath）得到压缩后尺寸。
	srcPath := filepath.Join(conf.C.Storage.PhotoSrc, relPath)

	ei := getExifInfo(srcPath)
	if ei == nil {
		ei = &exifInfo{}
	}
	if shotAt != nil {
		ei.ShotAt = shotAt
	}

	// 拍摄时间：EXIF 缺失时按文件修改日期兜底
	resolvedShotAt := resolveShotAt(ei, srcPath)

	timeline := ""
	if resolvedShotAt != nil {
		entries, _ := loadTimeline(ctx)
		timeline = findEventByTime(*resolvedShotAt, entries, conf.C.Storage.TimelineWindowDays)
	}

	width, height := 0, 0
	if fileType != "nef" {
		width, height = getImageSize(srcPath)
	}

	photoDO := &data.PhotoDO{
		ID:           putil.UUID(),
		Filename:     filename,
		FilePath:     relPath,
		FileType:     fileType,
		Timeline:     timeline,
		Width:        int32(width),
		Height:       int32(height),
		Brand:        ei.Brand,
		Model:        ei.Model,
		Lens:         ei.Lens,
		FocalLength:  ei.FocalLength,
		Aperture:     ei.Aperture,
		Iso:          int32(ei.ISO),
		ExposureTime: ei.ExposureTime,
		ImportedAt:   time.Now(),
	}
	if resolvedShotAt != nil {
		photoDO.ShotAt = *resolvedShotAt
	}
	if ei.Latitude != nil {
		photoDO.Latitude = *ei.Latitude
	}
	if ei.Longitude != nil {
		photoDO.Longitude = *ei.Longitude
	}
	if ei.Altitude != nil {
		photoDO.Altitude = *ei.Altitude
	}

	if err := data.PhotoDAO.Add(ctx, photoDO); err != nil {
		return "", fmt.Errorf("create photo record failed: %w", err)
	}

	return photoDO.ID, nil
}

func overwritePhoto(ctx *papp.AppCtx, photoID, filename string, folder string, shotAt *time.Time) error {
	relPath := filename
	if folder != "" {
		relPath = filepath.Join(folder, filename)
	}

	// 尺寸与 EXIF 统一从源文件（原图）读取，避免读缩略图（PhotoPath）得到压缩后尺寸。
	srcPath := filepath.Join(conf.C.Storage.PhotoSrc, relPath)

	ei := getExifInfo(srcPath)
	if ei == nil {
		ei = &exifInfo{}
	}
	if shotAt != nil {
		ei.ShotAt = shotAt
	}

	// 拍摄时间：EXIF 缺失时按文件修改日期兜底
	resolvedShotAt := resolveShotAt(ei, srcPath)

	timeline := ""
	if resolvedShotAt != nil {
		entries, _ := loadTimeline(ctx)
		timeline = findEventByTime(*resolvedShotAt, entries, conf.C.Storage.TimelineWindowDays)
	}

	width, height := getImageSize(srcPath)

	updates := map[string]any{"description": "", "file_path": relPath}
	if timeline != "" {
		updates["timeline"] = timeline
	}
	if ei.Brand != "" {
		updates["brand"] = ei.Brand
	}
	if ei.Model != "" {
		updates["model"] = ei.Model
	}
	if ei.Lens != "" {
		updates["lens"] = ei.Lens
	}
	if ei.FocalLength != "" {
		updates["focal_length"] = ei.FocalLength
	}
	if ei.Aperture != "" {
		updates["aperture"] = ei.Aperture
	}
	if ei.ISO != 0 {
		updates["iso"] = ei.ISO
	}
	if ei.ExposureTime != "" {
		updates["exposure_time"] = ei.ExposureTime
	}
	// 覆盖同名文件时按新文件回写拍摄时间与 GPS 字段，与 createPhotoRecord 的字段口径对齐。
	if resolvedShotAt != nil {
		updates["shot_at"] = *resolvedShotAt
	}
	if ei.Latitude != nil {
		updates["latitude"] = *ei.Latitude
	}
	if ei.Longitude != nil {
		updates["longitude"] = *ei.Longitude
	}
	if ei.Altitude != nil {
		updates["altitude"] = *ei.Altitude
	}
	if width > 0 && height > 0 {
		updates["width"] = width
		updates["height"] = height
	}

	if err := data.PhotoDAO.UpdatePhotoAfterOverwrite(ctx, photoID, updates); err != nil {
		return err
	}
	return nil
}

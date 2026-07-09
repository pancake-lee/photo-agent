package service

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"backend-new/internal/defaultService/conf"
	"backend-new/internal/defaultService/data"
	"backend-new/internal/pkg/api"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/pdb"
	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/pancake-lee/pgo/pkg/putil"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

type PhotoServer struct {
	api.UnimplementedPhotoServiceServer
}

// Reg 向 Kratos gRPC/HTTP 服务器注册本服务。
// HTTP 路由在生成的 RegisterPhotoServiceHTTPServer 基础上，额外注册文件上传和图片 serving。
func (s *PhotoServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if grpcSrv != nil {
		api.RegisterPhotoServiceServer(grpcSrv, s)
	}
	if httpSrv != nil {
		api.RegisterPhotoServiceHTTPServer(httpSrv, s)

		// 额外注册非 proto 映射的原始 HTTP 路由
		// 手动注册的上传/图片路由
		r := httpSrv.Route("/")
		r.GET("/api/v1/photos/{id}/image", s.GetPhotoImageHandler)
		r.POST("/api/v1/photos/upload", s.UploadPhotoHandler)
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

	params := data.ListPhotosParams{
		Page:        int(req.Page),
		PageSize:    int(req.PageSize),
		Timeline:    req.Timeline,
		Tag:         req.Tag,
		Keyword:     req.Keyword,
		Brand:       req.Brand,
		Lens:        req.Lens,
		FocalMin:    req.FocalMin,
		FocalMax:    req.FocalMax,
		ISOMin:      req.IsoMin,
		ISOMax:      req.IsoMax,
		ShotAtStart: req.ShotAtStart,
		ShotAtEnd:   req.ShotAtEnd,
		SortBy:      req.SortBy,
		SortOrder:   req.SortOrder,
	}

	photos, total, err := data.PhotoDAO.ListPhotos(ctx, params)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	items := make([]*api.PhotoItem, len(photos))
	for i, p := range photos {
		items[i] = photoDO2Item(p)
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
	descEntry, _ := getDescriptionEntry(photo.FilePath, conf.C.Storage.DescriptionsPath)

	return &api.GetPhotoDetailResponse{
		Photo:            item,
		ImageUrl:         fmt.Sprintf("/api/v1/photos/%s/image", photo.ID),
		DescriptionModel: descEntry.Model,
		DescriptionTime:  descEntry.ProcessedAt,
	}, nil
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

	fullPath := filepath.Join(conf.C.Storage.PhotoPath, photo.FilePath)
	if err := os.Remove(fullPath); err != nil && !os.IsNotExist(err) {
		plogger.Warnf("Failed to delete photo file %s: %v", fullPath, err)
	}

	return &api.DeletePhotoResponse{
		Status: "deleted",
		Id:     req.Id,
	}, nil
}

// ================================================================
// 原始 HTTP 路由 handler（非 proto 映射）
// ================================================================

// GetPhotoImageHandler 返回图片原图文件
func (s *PhotoServer) GetPhotoImageHandler(kctx khttp.Context) error {
	id := kctx.Vars().Get("id")

	_ctx := kctx.Request().Context()
	ctx := papp.NewAppCtx(_ctx)

	photo, err := data.PhotoDAO.GetByID(ctx, id)
	if err != nil {
		return err
	}

	fullPath := filepath.Join(conf.C.Storage.PhotoPath, photo.FilePath)
	http.ServeFile(kctx.Response(), kctx.Request(), fullPath)
	return nil
}

// UploadPhotoHandler 上传图片。
// 流程：保存到 photo_src → 压缩到 photo_path → 读 EXIF → 匹配时间线 → 入库。
func (s *PhotoServer) UploadPhotoHandler(kctx khttp.Context) error {
	req := kctx.Request()

	if err := req.ParseMultipartForm(32 << 20); err != nil {
		return fmt.Errorf("parse multipart form failed: %w", err)
	}

	originalName := req.FormValue("original_name")
	originalShotAt := req.FormValue("original_shot_at")
	conflictResolution := req.FormValue("conflict_resolution")

	file, header, err := req.FormFile("file")
	if err != nil {
		return fmt.Errorf("missing file field: %w", err)
	}
	defer file.Close()

	ext := filepath.Ext(header.Filename)
	if ext == "" {
		ext = ".jpg"
	}
	targetFilename := sanitizeFilename(originalName, ext)
	newShotAt := parseShotAt(originalShotAt)

	_ctx := req.Context()
	ctx := papp.NewAppCtx(_ctx)

	// 检查冲突
	existingPhoto, _ := data.PhotoDAO.GetByFilename(ctx, targetFilename)
	if existingPhoto != nil {
		return s.handleConflict(kctx, ctx, file, targetFilename, existingPhoto, newShotAt, conflictResolution)
	}

	// 无冲突：保存 → 压缩 → 入库
	photoID := s.doUpload(ctx, file, targetFilename, newShotAt)
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
	resolution string,
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
		// 保存到 photo_src + 压缩到 photo_path
		if err := saveUploadedFile(file, targetFilename, conf.C.Storage.PhotoSrc); err != nil {
			return err
		}
		srcPath := filepath.Join(conf.C.Storage.PhotoSrc, targetFilename)
		maxBytes := int64(conf.C.VLM.MaxImageSizeMB * 1024 * 1024)
		if err := processToPhotoPath(srcPath, targetFilename, conf.C.Storage.PhotoPath, maxBytes); err != nil {
			return err
		}
		// 删除旧文件
		oldPath := filepath.Join(conf.C.Storage.PhotoPath, existingPhoto.FilePath)
		if oldPath != filepath.Join(conf.C.Storage.PhotoPath, targetFilename) {
			_ = os.Remove(oldPath)
		}
		overwritePhoto(ctx, existingPhoto.ID, targetFilename, newShotAt)
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
		photoID := s.doUpload(ctx, file, newFilename, newShotAt)
		return kctx.Result(200, map[string]any{
			"status":   "stored",
			"photo_id": photoID,
		})

	default:
		return kctx.Result(400, map[string]any{"error": "invalid conflict_resolution"})
	}
}

// doUpload 执行实际的上传流程（保存文件 + 压缩 + EXIF + 入库）
func (s *PhotoServer) doUpload(
	ctx *papp.AppCtx, file io.Reader, filename string,
	shotAt *time.Time,
) string {
	if err := saveUploadedFile(file, filename, conf.C.Storage.PhotoSrc); err != nil {
		plogger.Warnf("save uploaded file failed: %v", err)
		return ""
	}

	srcPath := filepath.Join(conf.C.Storage.PhotoSrc, filename)
	maxBytes := int64(conf.C.VLM.MaxImageSizeMB * 1024 * 1024)
	if err := processToPhotoPath(srcPath, filename, conf.C.Storage.PhotoPath, maxBytes); err != nil {
		plogger.Warnf("process to photo path failed: %v", err)
		return ""
	}

	return createPhotoRecord(ctx, filename, shotAt)
}

// ================================================================
// 辅助函数
// ================================================================

func photoDO2Item(do *data.PhotoDO) *api.PhotoItem {
	if do == nil {
		return nil
	}
	item := &api.PhotoItem{
		Id:             do.ID,
		Filename:       do.Filename,
		FilePath:       do.FilePath,
		Timeline:       do.Timeline,
		Tags:           do.Tags,
		Description:    do.Description,
		Objects:        do.Objects,
		Colors:         do.Colors,
		Scene:          do.Scene,
		Lighting:       do.Lighting,
		Mood:           do.Mood,
		Composition:    do.Composition,
		Width:          do.Width,
		Height:         do.Height,
		Brand:          do.Brand,
		Model:          do.Model,
		Lens:           do.Lens,
		FocalLength:    do.FocalLength,
		Aperture:       do.Aperture,
		Iso:            do.Iso,
		ExposureTime:   do.ExposureTime,
		Latitude:       do.Latitude,
		Longitude:      do.Longitude,
		Altitude:       do.Altitude,
		HasDescription: do.Description != "",
		ThumbnailUrl:   fmt.Sprintf("/api/v1/photos/%s/image", do.ID),
	}
	if !do.ShotAt.IsZero() {
		item.ShotAt = do.ShotAt.Unix()
	}
	if !do.ImportedAt.IsZero() {
		item.ImportedAt = do.ImportedAt.Unix()
	}
	return item
}

func parseShotAt(s string) *time.Time {
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

func createPhotoRecord(ctx *papp.AppCtx, filename string, shotAt *time.Time) string {
	fullPath := filepath.Join(conf.C.Storage.PhotoPath, filename)
	ei := getExifInfo(fullPath)
	if ei == nil {
		ei = &exifInfo{}
	}
	if shotAt != nil {
		ei.ShotAt = shotAt
	}

	timeline := ""
	if ei.ShotAt != nil {
		timeline = FindEventByTime(*ei.ShotAt, conf.C.Storage.TimelinePath)
	}

	width, height := getImageSize(fullPath)

	photoDO := &data.PhotoDO{
		ID:           putil.UUID(),
		Filename:     filename,
		FilePath:     filename,
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
	if ei.ShotAt != nil {
		photoDO.ShotAt = *ei.ShotAt
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
		plogger.Warnf("Create photo record failed: %v", err)
		return ""
	}

	return photoDO.ID
}

func overwritePhoto(ctx *papp.AppCtx, photoID, filename string, shotAt *time.Time) {
	fullPath := filepath.Join(conf.C.Storage.PhotoPath, filename)
	ei := getExifInfo(fullPath)
	if ei == nil {
		ei = &exifInfo{}
	}
	if shotAt != nil {
		ei.ShotAt = shotAt
	}

	timeline := ""
	if ei.ShotAt != nil {
		timeline = FindEventByTime(*ei.ShotAt, conf.C.Storage.TimelinePath)
	}
	width, height := getImageSize(fullPath)

	updates := map[string]any{"description": ""}
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
	if width > 0 && height > 0 {
		updates["width"] = width
		updates["height"] = height
	}

	pdb.GetGormDB().WithContext(ctx).Model(&data.PhotoDO{}).
		Where("id = ?", photoID).Updates(updates)
}

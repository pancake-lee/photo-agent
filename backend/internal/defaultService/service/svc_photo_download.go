package service

import (
	"archive/zip"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"

	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
)

const maxDownloadPhotos = 200

type downloadPhotosRequest struct {
	PhotoIDs []string `json:"photo_ids"`
}

type downloadPhotoSource struct{ path, name string }

// DownloadPhotosHandler 将指定照片的原始文件打包为一个 ZIP。全部文件先校验完毕，避免产生半截下载。
func (s *PhotoServer) DownloadPhotosHandler(kctx khttp.Context) error {
	var req downloadPhotosRequest
	if err := json.NewDecoder(kctx.Request().Body).Decode(&req); err != nil {
		return kctx.Result(http.StatusBadRequest, map[string]string{"error": "请求体必须包含 photo_ids"})
	}
	if len(req.PhotoIDs) == 0 || len(req.PhotoIDs) > maxDownloadPhotos {
		return kctx.Result(http.StatusBadRequest, map[string]string{"error": fmt.Sprintf("请选择 1 至 %d 张照片", maxDownloadPhotos)})
	}

	ids := make([]string, 0, len(req.PhotoIDs))
	seen := make(map[string]struct{}, len(req.PhotoIDs))
	for _, id := range req.PhotoIDs {
		id = strings.TrimSpace(id)
		if id == "" {
			return kctx.Result(http.StatusBadRequest, map[string]string{"error": "照片 ID 不能为空"})
		}
		if _, exists := seen[id]; exists {
			return kctx.Result(http.StatusBadRequest, map[string]string{"error": "照片 ID 不能重复"})
		}
		seen[id] = struct{}{}
		ids = append(ids, id)
	}

	ctx := papp.NewAppCtx(kctx.Request().Context())
	photos, err := data.PhotoDAO.GetByIDList(ctx, ids)
	if err != nil {
		return err
	}
	if len(photos) != len(ids) {
		return kctx.Result(http.StatusNotFound, map[string]string{"error": "存在找不到的照片"})
	}

	sources := make([]downloadPhotoSource, 0, len(ids))
	for _, id := range ids {
		photo := photos[id]
		fullPath := filepath.Join(conf.C.Storage.PhotoSrc, photo.FilePath)
		info, statErr := os.Stat(fullPath)
		if statErr != nil || info.IsDir() {
			return kctx.Result(http.StatusNotFound, map[string]string{"error": fmt.Sprintf("原始文件不可用：%s", photo.Filename)})
		}
		sources = append(sources, downloadPhotoSource{path: fullPath, name: filepath.Base(photo.FilePath)})
	}

	names := uniqueZipEntryNames(sources)
	w := kctx.Response()
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", "attachment; filename=photos.zip")
	zipWriter := zip.NewWriter(w)
	for i, item := range sources {
		file, openErr := os.Open(item.path)
		if openErr != nil {
			return openErr
		}
		entry, createErr := zipWriter.Create(names[i])
		if createErr == nil {
			_, createErr = io.Copy(entry, file)
		}
		file.Close()
		if createErr != nil {
			return createErr
		}
	}
	return zipWriter.Close()
}

func uniqueZipEntryNames(sources []downloadPhotoSource) []string {
	used := make(map[string]struct{}, len(sources))
	names := make([]string, len(sources))
	for i, source := range sources {
		base := filepath.Base(source.name)
		ext := filepath.Ext(base)
		stem := strings.TrimSuffix(base, ext)
		name := base
		for suffix := 2; ; suffix++ {
			if _, exists := used[name]; !exists {
				break
			}
			name = fmt.Sprintf("%s (%d)%s", stem, suffix, ext)
		}
		used[name] = struct{}{}
		names[i] = name
	}
	return names
}

package service

import (
	"context"
	"errors"
	"fmt"
	kratoserrors "github.com/go-kratos/kratos/v2/errors"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"
	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/putil"
)

type TimelineServer struct {
	api.UnimplementedTimelineServiceServer
}

func (s *TimelineServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if grpcSrv != nil {
		api.RegisterTimelineServiceServer(grpcSrv, s)
	}
	if httpSrv != nil {
		api.RegisterTimelineServiceHTTPServer(httpSrv, s)
	}
}

func (s *TimelineServer) ListTimelines(ctx context.Context, _ *api.Empty) (*api.ListTimelinesResponse, error) {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	list, err := syncActivityDirectoriesLocked(papp.NewAppCtx(ctx))
	if err != nil {
		return nil, err
	}
	result := &api.ListTimelinesResponse{Timelines: make([]string, 0, len(list))}
	for _, item := range list {
		result.Timelines = append(result.Timelines, item.Name)
	}
	return result, nil
}

func (s *TimelineServer) GetPhotosByTimeline(ctx context.Context, req *api.GetPhotosByTimelineRequest) (*api.GetPhotosByTimelineResponse, error) {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	app := papp.NewAppCtx(ctx)
	_, err := syncActivityDirectoriesLocked(app)
	if err != nil {
		return nil, err
	}
	photos, err := data.PhotoDAO.GetPhotosByTimeline(app, req.Name)
	if err != nil {
		return nil, err
	}
	result := &api.GetPhotosByTimelineResponse{Timeline: req.Name, Total: int32(len(photos)), Items: make([]*api.PhotoItem, 0, len(photos))}
	for _, photo := range photos {
		result.Items = append(result.Items, photoDO2Item(photo))
	}
	return result, nil
}

func (s *TimelineServer) ListEvents(ctx context.Context, _ *api.Empty) (*api.ListTimelineEventsResponse, error) {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	app := papp.NewAppCtx(ctx)
	list, err := syncActivityDirectoriesLocked(app)
	if err != nil {
		return nil, err
	}
	photos, err := data.PhotoDAO.GetAll(app)
	if err != nil {
		return nil, err
	}
	counts := make(map[string]int32)
	for _, photo := range photos {
		if photo.FileType != "nef" {
			counts[photo.Timeline]++
		}
	}
	result := &api.ListTimelineEventsResponse{Events: make([]*api.TimelineEventDetail, 0, len(list)), Scattered: []*api.TimelineEventDetail{}}
	for _, item := range list {
		result.Events = append(result.Events, &api.TimelineEventDetail{Id: item.Metadata.ID, Date: item.Metadata.Date, Event: item.Name, Note: item.Metadata.Note, PhotoCount: counts[item.Name]})
	}
	return result, nil
}

// SaveEvent renames the source directory and commits the same identity through
// normal reconciliation. Metadata owns date/note; its name is never duplicated.
func (s *TimelineServer) SaveEvent(ctx context.Context, req *api.SaveTimelineEventRequest) (*api.SaveTimelineEventResponse, error) {
	name := strings.TrimSpace(req.Event)
	if !archiveComponent(name) || !validActivityDate(req.Date) {
		return nil, api.ErrorInvalidArgument("活动目录名或时间无效")
	}
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	app := papp.NewAppCtx(ctx)
	list, err := syncActivityDirectoriesLocked(app)
	if err != nil {
		return nil, err
	}
	root := conf.C.Storage.PhotoSrc
	err = os.MkdirAll(root, 0755)
	if err != nil {
		return nil, err
	}
	var current *activityDirectory
	for i := range list {
		if list[i].Metadata.ID == req.Id {
			current = &list[i]
			break
		}
	}
	if req.Id != "" && current == nil {
		return nil, kratoserrors.NotFound("ACTIVITY_NOT_FOUND", "活动目录不存在")
	}
	if current == nil || current.Name != name {
		actual, err := caseInsensitiveFileName(root, name)
		if err != nil {
			return nil, err
		}
		if actual != "" {
			return nil, fmt.Errorf("活动目录已存在: %s", actual)
		}
	}
	if current == nil {
		err = os.Mkdir(filepath.Join(root, name), 0755)
		if err != nil {
			return nil, err
		}
		meta := activityMetadata{Version: 1, ID: putil.UUID(), Date: req.Date, Note: req.Note}
		err = writeActivityMetadata(name, meta)
		if err != nil {
			return nil, errors.Join(err, os.Remove(filepath.Join(root, name)))
		}
		return &api.SaveTimelineEventResponse{Id: meta.ID}, nil
	}
	old := current.Name
	meta := current.Metadata
	meta.Date, meta.Note = req.Date, req.Note
	if old != name {
		busy, err := data.HasActivityReservations(app, old)
		if err != nil {
			return nil, err
		}
		if busy {
			return nil, fmt.Errorf("请完成活动中的导入后再改名")
		}
		err = os.Rename(filepath.Join(root, old), filepath.Join(root, name))
		if err != nil {
			return nil, err
		}
	}
	rollback := func() error {
		if old == name {
			return writeActivityMetadata(old, current.Metadata)
		}
		moveErr := os.Rename(filepath.Join(root, name), filepath.Join(root, old))
		if moveErr != nil {
			return moveErr
		}
		metadataErr := writeActivityMetadata(old, current.Metadata)
		_, syncErr := syncActivityDirectoriesLocked(app)
		return errors.Join(metadataErr, syncErr)
	}
	err = writeActivityMetadata(name, meta)
	if err != nil {
		return nil, errors.Join(err, rollback())
	}
	_, err = syncActivityDirectoriesLocked(app)
	if err != nil {
		return nil, errors.Join(err, rollback())
	}
	return &api.SaveTimelineEventResponse{Id: meta.ID}, nil
}

// DeleteEvent only removes an empty activity. Photo/recycle operations retain
// ownership of their files and must be completed before deleting the directory.
func (s *TimelineServer) DeleteEvent(ctx context.Context, req *api.DeleteTimelineEventRequest) (*api.Empty, error) {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	app := papp.NewAppCtx(ctx)
	list, err := syncActivityDirectoriesLocked(app)
	if err != nil {
		return nil, err
	}
	for _, item := range list {
		if item.Metadata.ID != req.Id {
			continue
		}
		locations, err := data.ListActivityLocations(app)
		if err != nil {
			return nil, err
		}
		for _, location := range locations {
			if location.ActivityID == req.Id {
				return nil, fmt.Errorf("活动含照片或最近删除记录，不能删除")
			}
		}
		busy, err := data.HasActivityReservations(app, item.Name)
		if err != nil {
			return nil, err
		}
		if busy {
			return nil, fmt.Errorf("活动含尚未完成的导入，不能删除")
		}
		dir := filepath.Join(conf.C.Storage.PhotoSrc, item.Name)
		entries, err := os.ReadDir(dir)
		if err != nil {
			return nil, err
		}
		for _, entry := range entries {
			if entry.Name() != activityMetadataFile {
				return nil, fmt.Errorf("活动目录非空，不能删除")
			}
		}
		preview := filepath.Join(conf.C.Storage.PhotoPath, item.Name)
		if filepath.Clean(preview) != filepath.Clean(dir) {
			previewEntries, previewErr := os.ReadDir(preview)
			if previewErr != nil && !os.IsNotExist(previewErr) {
				return nil, previewErr
			}
			for _, entry := range previewEntries {
				if entry.Name() != activityPreviewIDFile {
					return nil, fmt.Errorf("活动预览目录非空，不能删除")
				}
			}
			if previewErr == nil {
				if len(previewEntries) > 0 {
					err = os.Remove(filepath.Join(preview, activityPreviewIDFile))
					if err != nil {
						return nil, err
					}
				}
				err = os.Remove(preview)
				if err != nil {
					return nil, err
				}
			}
		}
		err = os.Remove(filepath.Join(dir, activityMetadataFile))
		if err != nil {
			return nil, err
		}
		err = os.Remove(dir)
		if err != nil {
			return nil, errors.Join(err, writeActivityMetadata(item.Name, item.Metadata))
		}
		return &api.Empty{}, nil
	}
	return nil, kratoserrors.NotFound("ACTIVITY_NOT_FOUND", "活动目录不存在")
}

var activitySyncStatus struct {
	sync.Mutex
	processed int32
}

// RecomputeTimelines is retained as a compatibility endpoint. Synchronization
// now follows directories exclusively and never changes ownership by shot time.
func (s *TimelineServer) RecomputeTimelines(ctx context.Context, _ *api.Empty) (*api.RecomputeTimelinesResponse, error) {
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	app := papp.NewAppCtx(ctx)
	_, err := syncActivityDirectoriesLocked(app)
	if err != nil {
		return nil, err
	}
	photos, err := data.PhotoDAO.GetAll(app)
	if err != nil {
		return nil, err
	}
	activitySyncStatus.Lock()
	activitySyncStatus.processed = int32(len(photos))
	activitySyncStatus.Unlock()
	return &api.RecomputeTimelinesResponse{Status: "completed"}, nil
}

func (s *TimelineServer) GetRecomputeTimelinesStatus(context.Context, *api.Empty) (*api.GetRecomputeTimelinesStatusResponse, error) {
	activitySyncStatus.Lock()
	defer activitySyncStatus.Unlock()
	count := activitySyncStatus.processed
	return &api.GetRecomputeTimelinesStatusResponse{Processed: count, Total: count, EventCount: count}, nil
}

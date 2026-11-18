package service

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"github.com/pancake-lee/pgo/pkg/papp"
)

// ConsolidateEmptyActivity preserves recycle ownership and archives metadata
// after an explicitly requested move has emptied the source activity.
func ConsolidateEmptyActivity(ctx context.Context, fromName, toName,
	backup string,
) error {
	if !archiveComponent(fromName) || !archiveComponent(toName) || fromName == toName || !filepath.IsAbs(backup) {
		return fmt.Errorf("必须指定不同的源/目标活动及绝对备份目录")
	}
	info, err := os.Lstat(backup)
	if err != nil || !info.IsDir() {
		return fmt.Errorf("备份目录不存在或不是普通目录")
	}
	for _, root := range []string{conf.C.Storage.PhotoSrc, conf.C.Storage.PhotoPath} {
		rel, relErr := filepath.Rel(root, backup)
		if relErr != nil || filepath.IsLocal(rel) {
			return fmt.Errorf("备份目录必须位于照片和预览库之外")
		}
	}
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	app := papp.NewAppCtx(ctx)
	list, err := syncActivityDirectoriesLocked(app)
	if err != nil {
		return err
	}
	var source, target *activityDirectory
	for i := range list {
		if list[i].Name == fromName {
			source = &list[i]
		}
		if list[i].Name == toName {
			target = &list[i]
		}
	}
	if source == nil || target == nil {
		return fmt.Errorf("源活动或目标活动不存在")
	}
	for _, name := range []string{fromName, toName} {
		busy, busyErr := data.HasActivityReservations(app, name)
		if busyErr != nil {
			return busyErr
		}
		if busy {
			return fmt.Errorf("请先完成活动中的导入再合并目录")
		}
	}
	type directory struct{ from, to, marker string }
	directories := []directory{{filepath.Join(conf.C.Storage.PhotoSrc, fromName),
		filepath.Join(backup, "removed-empty-"+fromName), activityMetadataFile}}
	if filepath.Clean(conf.C.Storage.PhotoSrc) != filepath.Clean(conf.C.Storage.PhotoPath) {
		preview := filepath.Join(conf.C.Storage.PhotoPath, fromName)
		_, statErr := os.Lstat(preview)
		if statErr == nil {
			directories = append(directories, directory{preview,
				filepath.Join(backup, "removed-empty-preview-"+fromName), activityPreviewIDFile})
		} else if !os.IsNotExist(statErr) {
			return statErr
		}
	}
	for _, dir := range directories {
		info, statErr := os.Lstat(dir.from)
		if statErr != nil || !info.IsDir() {
			return fmt.Errorf("源目录无效: %s", dir.from)
		}
		entries, readErr := os.ReadDir(dir.from)
		if readErr != nil {
			return readErr
		}
		for _, entry := range entries {
			if entry.Name() != dir.marker || !entry.Type().IsRegular() {
				return fmt.Errorf("源目录仍有未迁移文件: %s", entry.Name())
			}
		}
		if _, statErr = os.Lstat(dir.to); !os.IsNotExist(statErr) {
			return fmt.Errorf("备份目标已存在或不可访问: %s", dir.to)
		}
	}
	_, err = data.RebindEmptyActivityRecycle(app, source.Metadata.ID, fromName,
		target.Metadata.ID, toName)
	if err != nil {
		return err
	}
	for _, dir := range directories {
		err = os.Rename(dir.from, dir.to)
		if err != nil {
			return fmt.Errorf("回收记录已归入目标活动，空目录归档未完成: %w", err)
		}
	}
	return nil
}

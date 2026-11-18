package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"github.com/pancake-lee/pgo/pkg/papp"
)

type legacyFavoritePlan struct {
	Version    int                   `json:"version"`
	SourceRoot string                `json:"source_root"`
	Activities []legacyActivity      `json:"activities"`
	Entries    []legacyFavoriteEntry `json:"entries"`
}

type legacyActivity struct {
	Name string `json:"name"`
	Date string `json:"date"`
	Note string `json:"note"`
}

type legacyFavoriteEntry struct {
	Source         string       `json:"source"`
	SourceName     string       `json:"source_name"`
	SHA256         string       `json:"sha256"`
	Activity       string       `json:"activity"`
	Filename       string       `json:"filename"`
	Photo          data.PhotoDO `json:"photo"`
	MatchPhotoIDs  []string     `json:"match_photo_ids"`
	OriginalSource string       `json:"original_source,omitempty"`
	OriginalSHA256 string       `json:"original_sha256,omitempty"`
}

type legacyFavoriteResult struct {
	Source    string   `json:"source"`
	OldID     string   `json:"old_id"`
	SHA256    string   `json:"sha256"`
	Action    string   `json:"action"`
	PhotoIDs  []string `json:"photo_ids"`
	AITargets []string `json:"ai_targets,omitempty"`
	Target    string   `json:"target,omitempty"`
	Created   bool     `json:"created"`
}

func restoreAIFields(target, source *data.PhotoDO) {
	target.Description = source.Description
	target.DescriptionModel = source.DescriptionModel
	target.DescriptionTime = source.DescriptionTime
	target.DescriptionRaw = source.DescriptionRaw
	target.Objects, target.Colors = source.Objects, source.Colors
	target.Scene, target.Lighting = source.Scene, source.Lighting
	target.Mood, target.Composition = source.Mood, source.Composition
}

func validateRestoreSource(root, path, digest string) error {
	relative, err := filepath.Rel(root, path)
	if err != nil || !filepath.IsLocal(relative) || !validArchiveDigest(digest) {
		return fmt.Errorf("无效恢复源路径或摘要: %s", path)
	}
	actual, _, err := digestFile(path)
	if err != nil {
		return err
	}
	if actual != digest {
		return fmt.Errorf("恢复源文件摘要不符: %s", path)
	}
	return nil
}

func restorePublish(root, target, source, digest string) error {
	present, matching, err := archiveFileState(root, target, digest)
	if err != nil {
		return err
	}
	if present {
		if matching {
			return nil
		}
		return fmt.Errorf("恢复目标已存在不同内容: %s", target)
	}
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer input.Close()
	info, err := input.Stat()
	if err != nil {
		return err
	}
	return writeVerifiedArchiveFile(root, target, digest, info.ModTime(), input, nil, nil)
}

func restoreFilename(ctx *papp.AppCtx, e legacyFavoriteEntry) (string, error) {
	stem := strings.TrimSuffix(e.Filename, filepath.Ext(e.Filename))
	extension := filepath.Ext(e.Filename)
	for n := 0; n < 100; n++ {
		filename := e.Filename
		if n > 0 {
			filename = fmt.Sprintf("%s_%s_%d%s", stem, e.SHA256[:12], n, extension)
		}
		target := filepath.Join(e.Activity, filename)
		current, err := data.PhotoDAO.FindByArchivePath(ctx, target)
		if err != nil {
			return "", err
		}
		if current != nil && current.ID != e.Photo.ID {
			continue
		}
		actual, err := archiveFileAt(conf.C.Storage.PhotoSrc, target)
		if err != nil {
			return "", err
		}
		if actual != "" {
			digest, _, err := digestFile(filepath.Join(conf.C.Storage.PhotoSrc, actual))
			if err != nil {
				return "", err
			}
			if digest != e.SHA256 {
				continue
			}
			return actual, nil
		}
		nef := filepath.Join(e.Activity, strings.TrimSuffix(filename, extension)+".nef")
		raw, err := archiveFileAt(conf.C.Storage.PhotoSrc, nef)
		if err != nil {
			return "", err
		}
		preview, err := archiveFileAt(conf.C.Storage.PhotoPath, target)
		if err != nil {
			return "", err
		}
		if raw == "" && preview == "" {
			return target, nil
		}
	}
	return "", fmt.Errorf("无法分配恢复位置: %s", e.SourceName)
}

// RestoreLegacyFavorites applies an explicit, reviewed local manifest only.
// It starts no service and performs no VLM/Embedding requests.
func RestoreLegacyFavorites(ctx context.Context, planPath, reportPath string,
	inheritAI bool, progress io.Writer,
) error {
	raw, err := os.ReadFile(planPath)
	if err != nil {
		return err
	}
	var plan legacyFavoritePlan
	err = json.Unmarshal(raw, &plan)
	if err != nil {
		return err
	}
	if plan.Version != 1 || !filepath.IsAbs(plan.SourceRoot) || reportPath == "" {
		return fmt.Errorf("恢复清单版本、源目录或报告路径无效")
	}
	photoArchiveMu.Lock()
	defer photoArchiveMu.Unlock()
	app := papp.NewAppCtx(ctx)
	_, err = syncActivityDirectoriesLocked(app)
	if err != nil {
		return err
	}
	metas := make(map[string]activityMetadata)
	for _, activity := range plan.Activities {
		if !archiveComponent(activity.Name) || !validActivityDate(activity.Date) {
			return fmt.Errorf("无效恢复活动: %s", activity.Name)
		}
		_, statErr := os.Lstat(filepath.Join(conf.C.Storage.PhotoSrc, activity.Name, activityMetadataFile))
		meta, err := ensureActivityMetadata(app, activity.Name)
		if err != nil {
			return err
		}
		if os.IsNotExist(statErr) {
			meta.Date, meta.Note = activity.Date, activity.Note
			err = writeActivityMetadata(activity.Name, meta)
			if err != nil {
				return err
			}
		}
		metas[activity.Name] = meta
	}
	for _, e := range plan.Entries {
		if !archiveComponent(e.Filename) || !archiveComponent(e.Activity) || !archiveComponent(e.Photo.ID) || metas[e.Activity].ID == "" || !validArchiveDigest(e.SHA256) {
			return fmt.Errorf("无效恢复条目: %s", e.SourceName)
		}
	}
	var dbMu sync.Mutex
	previewStage := filepath.Join(plan.SourceRoot, "prepared-previews")
	jobs := make(chan legacyFavoriteEntry)
	type outcome struct {
		result legacyFavoriteResult
		err    error
	}
	outcomes := make(chan outcome)
	var workers sync.WaitGroup
	for i := 0; i < 3; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for entry := range jobs {
				result, restoreErr := restoreLegacyFavorite(app, entry, metas[entry.Activity], previewStage, plan.SourceRoot, inheritAI, &dbMu)
				outcomes <- outcome{result: result, err: restoreErr}
			}
		}()
	}
	go func() {
		for _, entry := range plan.Entries {
			jobs <- entry
		}
		close(jobs)
		workers.Wait()
		close(outcomes)
	}()
	results := make([]legacyFavoriteResult, 0, len(plan.Entries))
	var failures []error
	for item := range outcomes {
		if item.err != nil {
			failures = append(failures, item.err)
		} else {
			results = append(results, item.result)
		}
		if (len(results)+len(failures))%25 == 0 || len(results)+len(failures) == len(plan.Entries) {
			fmt.Fprintf(progress, "RESTORE %d/%d failures=%d\n", len(results)+len(failures), len(plan.Entries), len(failures))
			err = writeRestoreReport(reportPath, results, failures)
			if err != nil {
				failures = append(failures, err)
			}
		}
	}
	if len(failures) > 0 {
		return errors.Join(failures...)
	}
	_, err = syncActivityDirectoriesLocked(app)
	return err
}

func restoreLegacyFavorite(ctx *papp.AppCtx, e legacyFavoriteEntry,
	meta activityMetadata, previewStage, sourceRoot string, inheritAI bool,
	dbMu *sync.Mutex,
) (legacyFavoriteResult, error) {
	result := legacyFavoriteResult{Source: e.SourceName, OldID: e.Photo.ID, SHA256: e.SHA256}
	err := validateRestoreSource(sourceRoot, e.Source, e.SHA256)
	if err != nil {
		return result, err
	}
	sourceAI := data.PhotoDO{}
	if inheritAI && validateVlmDescription(e.Photo.Description) == nil {
		restoreAIFields(&sourceAI, &e.Photo)
	}
	if len(e.MatchPhotoIDs) > 0 {
		result.Action = "merged"
		for _, id := range e.MatchPhotoIDs {
			dbMu.Lock()
			current, lookupErr := data.PhotoDAO.GetByID(ctx, id)
			dbMu.Unlock()
			if lookupErr != nil {
				return result, lookupErr
			}
			actual, _, lookupErr := digestFile(filepath.Join(conf.C.Storage.PhotoSrc, current.FilePath))
			if lookupErr != nil {
				return result, lookupErr
			}
			if actual != e.SHA256 {
				return result, fmt.Errorf("合并照片内容已变: %s", current.FilePath)
			}
			copy := sourceAI
			copy.ID = id
			dbMu.Lock()
			_, inherited, saveErr := data.SaveRestoredFavorite(ctx, &copy, data.PhotoArchiveDO{}, true)
			dbMu.Unlock()
			if saveErr != nil {
				return result, saveErr
			}
			result.PhotoIDs = append(result.PhotoIDs, id)
			if inherited {
				result.AITargets = append(result.AITargets, id)
			}
		}
		return result, nil
	}
	dbMu.Lock()
	target, err := restoreFilename(ctx, e)
	dbMu.Unlock()
	if err != nil {
		return result, err
	}
	err = restorePublish(conf.C.Storage.PhotoSrc, target, e.Source, e.SHA256)
	if err != nil {
		return result, err
	}
	if e.OriginalSource != "" {
		err = validateRestoreSource(sourceRoot, e.OriginalSource, e.OriginalSHA256)
		if err != nil {
			return result, err
		}
		rawTarget := filepath.Join(e.Activity, filepath.Base(e.OriginalSource))
		err = restorePublish(conf.C.Storage.PhotoSrc, rawTarget, e.OriginalSource, e.OriginalSHA256)
		if err != nil {
			return result, err
		}
	}
	dbMu.Lock()
	saved, lookupErr := data.PhotoDAO.FindByArchivePath(ctx, target)
	dbMu.Unlock()
	if lookupErr != nil {
		return result, lookupErr
	}
	preview := filepath.Join(conf.C.Storage.PhotoPath, target)
	width, height := getImageSize(preview)
	ownedPreview := saved != nil && saved.ID == e.Photo.ID
	if !ownedPreview && width > 0 && height > 0 {
		preparedHash, _, preparedErr := digestFile(filepath.Join(previewStage, e.Photo.ID+".jpg"))
		publishedHash, _, publishedErr := digestFile(preview)
		ownedPreview = preparedErr == nil && publishedErr == nil && preparedHash == publishedHash
	}
	if !ownedPreview || width <= 0 || height <= 0 {
		stageName := e.Photo.ID + ".jpg"
		limit := int64(conf.C.VLM.MaxImageSizeMB * 1024 * 1024)
		err = prepareLegacyPreview(ctx, e.Source, stageName, previewStage, limit)
		if err != nil {
			return result, err
		}
		stagePath := filepath.Join(previewStage, stageName)
		previewDigest, _, digestErr := digestFile(stagePath)
		if digestErr != nil {
			return result, digestErr
		}
		err = restorePublish(conf.C.Storage.PhotoPath, target, stagePath, previewDigest)
		if err != nil {
			return result, err
		}
	}
	row := newPhotoRecord(ctx, e.Photo.ID, filepath.Base(target), e.Activity, "jpg", &e.Photo.ShotAt)
	row.ActivityID = meta.ID
	row.ShotAt = e.Photo.ShotAt
	row.Tags = e.Photo.Tags
	if !e.Photo.ImportedAt.IsZero() {
		row.ImportedAt = e.Photo.ImportedAt
	}
	row.EmbeddingStatus = "pending"
	restoreAIFields(row, &sourceAI)
	state := data.PhotoArchiveDO{PhotoID: row.ID, Favorite: true, JPGSHA256: e.SHA256, ImportKey: data.ArchiveImportKey(e.Activity, e.SHA256, "")}
	dbMu.Lock()
	created, inherited, err := data.SaveRestoredFavorite(ctx, row, state, false)
	dbMu.Unlock()
	if err != nil {
		return result, err
	}
	result.Action, result.Target, result.Created = "restored", target, created
	result.PhotoIDs = []string{row.ID}
	if inherited {
		result.AITargets = []string{row.ID}
	}
	return result, nil
}

func writeRestoreReport(path string, results []legacyFavoriteResult, failures []error) error {
	messages := make([]string, 0, len(failures))
	for _, err := range failures {
		messages = append(messages, err.Error())
	}
	raw, err := json.MarshalIndent(struct {
		Entries []legacyFavoriteResult `json:"entries"`
		Errors  []string               `json:"errors"`
	}{results, messages}, "", "  ")
	if err != nil {
		return err
	}
	err = os.WriteFile(path+".tmp", append(raw, '\n'), 0600)
	if err != nil {
		return err
	}
	return os.Rename(path+".tmp", path)
}

// JPEG decoder downsampling avoids decoding full camera frames for a 512px
// preview. Originals and metadata remain untouched.
func prepareLegacyPreview(ctx context.Context, source, name, root string, limit int64) error {
	info, err := os.Stat(source)
	if err != nil {
		return err
	}
	if limit <= 0 || info.Size() <= limit {
		return processToPhotoPath(source, name, root, limit, nil)
	}
	err = os.MkdirAll(root, 0700)
	if err != nil {
		return err
	}
	temp, err := os.CreateTemp(root, ".restore-preview-*.jpg")
	if err != nil {
		return err
	}
	path := temp.Name()
	defer os.Remove(path)
	err = temp.Close()
	if err != nil {
		return err
	}
	command := exec.CommandContext(ctx, "convert", "-define", "jpeg:size=1024x1024", source, "-resize", "512x512>", "-quality", "85", path)
	output, err := command.CombinedOutput()
	if err != nil {
		return fmt.Errorf("恢复预览生成失败: %w: %s", err, output)
	}
	width, height := getImageSize(path)
	if width <= 0 || height <= 0 {
		return fmt.Errorf("恢复预览无效: %s", source)
	}
	return os.Rename(path, filepath.Join(root, name))
}

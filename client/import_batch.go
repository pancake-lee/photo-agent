package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/rwcarlsen/goexif/exif"
)

const (
	batchPending   = "pending"
	batchKept      = "kept"
	batchFavorite  = "favorite"
	batchDiscarded = "discarded"
)

type ImportBatchSource struct {
	Path string `json:"path"`
	Role string `json:"role"` // local, retained, favorite, starting
}

type ImportBatchFile struct {
	Path    string    `json:"path"`
	Root    string    `json:"root"`
	SHA256  string    `json:"sha256"`
	Size    int64     `json:"size"`
	ModTime time.Time `json:"mod_time"`
	ShotAt  string    `json:"shot_at,omitempty"`
	Camera  string    `json:"camera,omitempty"`
	ImageID string    `json:"image_id,omitempty"`
}

type ImportBatchEntry struct {
	StagedServer      string             `json:"staged_server,omitempty"`
	StageError        string             `json:"stage_error,omitempty"`
	ID                string             `json:"id"`
	JPG               *ImportBatchFile   `json:"jpg,omitempty"`
	NEF               *ImportBatchFile   `json:"nef,omitempty"`
	NEFCandidates     []*ImportBatchFile `json:"nef_candidates,omitempty"`
	Pair              string             `json:"pair"`
	Decision          string             `json:"decision"`
	Origin            string             `json:"origin"`
	Inherited         string             `json:"inherited,omitempty"`
	MissingFromExport bool               `json:"missing_from_export,omitempty"`
	Conflict          bool               `json:"conflict,omitempty"`
	Historical        bool               `json:"historical,omitempty"`
	ReferenceOnly     bool               `json:"reference_only,omitempty"`
	ShotAt            string             `json:"shot_at,omitempty"`
	Upload            *ImportBatchUpload `json:"upload,omitempty"`
}

type ImportBatch struct {
	Bursts       *ImportReviewBursts  `json:"bursts,omitempty"`
	ID           string               `json:"id"`
	Activity     string               `json:"activity"`
	Name         string               `json:"name,omitempty"`
	Step         string               `json:"step,omitempty"`
	StageServers []string             `json:"stage_servers,omitempty"`
	Sources      []ImportBatchSource  `json:"sources"`
	Complete     bool                 `json:"complete"`
	Entries      []ImportBatchEntry   `json:"entries"`
	Issues       []string             `json:"issues"`
	Undo         []ImportBatchUndo    `json:"undo,omitempty"`
	Recycling    []ImportRecycleGroup `json:"recycling,omitempty"`
}

type ImportBatchUndo struct {
	ID       string `json:"id"`
	Decision string `json:"decision"`
	Origin   string `json:"origin"`
	Conflict bool   `json:"conflict"`
}

func newImportBatchID() (string, error) {
	var raw [16]byte
	_, err := rand.Read(raw[:])
	return hex.EncodeToString(raw[:]), err
}

func validImportBatchID(id string) bool {
	_, err := hex.DecodeString(id)
	return len(id) == 32 && err == nil
}

func importBatchRoot() string {
	return filepath.Join(configDir(), "import-batches")
}

func importBatchPath(root, id string) string {
	return filepath.Join(root, id, "batch.json")
}

func loadImportBatch(root, id string) (*ImportBatch, error) {
	if !validImportBatchID(id) {
		return nil, fmt.Errorf("无效批次编号")
	}
	raw, err := os.ReadFile(importBatchPath(root, id))
	if err != nil {
		return nil, err
	}
	batch := &ImportBatch{}
	err = json.Unmarshal(raw, batch)
	return batch, err
}

func saveImportBatch(root string, batch *ImportBatch) error {
	path := importBatchPath(root, batch.ID)
	err := os.MkdirAll(filepath.Dir(path), 0700)
	if err != nil {
		return err
	}
	temp, err := os.CreateTemp(filepath.Dir(path), "batch-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	err = json.NewEncoder(temp).Encode(batch)
	if err == nil {
		err = temp.Sync()
	}
	err = errors.Join(err, temp.Close())
	if err != nil {
		return err
	}
	return os.Rename(temp.Name(), path)
}

func inspectBatchFile(path, root string) (*ImportBatchFile, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	digest := sha256.New()
	_, err = io.Copy(digest, f)
	if err != nil {
		return nil, err
	}
	result := &ImportBatchFile{
		Path: path, Root: root, Size: info.Size(), ModTime: info.ModTime(),
		SHA256: hex.EncodeToString(digest.Sum(nil)),
	}
	_, err = f.Seek(0, io.SeekStart)
	if err != nil {
		return nil, err
	}
	// Limit the prefix read for malformed TIFF/NEF metadata.
	metadata, _ := exif.Decode(io.LimitReader(f, 8<<20))
	if metadata != nil {
		date, dateErr := metadata.DateTime()
		if dateErr == nil {
			if raw := batchExifString(metadata, exif.SubSecTimeOriginal); raw != "" {
				if fraction, fractionErr := time.Parse("05.999999999", "00."+raw); fractionErr == nil {
					date = date.Add(time.Duration(fraction.Nanosecond()))
				}
			}
			result.ShotAt = date.Format(time.RFC3339Nano)
		}
		result.Camera = strings.TrimSpace(
			batchExifString(metadata, exif.Make) + " " +
				batchExifString(metadata, exif.Model),
		)
		result.ImageID = batchExifString(metadata, exif.ImageUniqueID)
	}
	end, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if info.Size() != end.Size() || !info.ModTime().Equal(end.ModTime()) {
		return nil, fmt.Errorf("扫描期间文件发生变化")
	}
	return result, nil
}

func batchExifString(metadata *exif.Exif, field exif.FieldName) string {
	tag, err := metadata.Get(field)
	if err != nil {
		return ""
	}
	value, _ := tag.StringVal()
	return strings.TrimSpace(strings.TrimRight(value, "\x00"))
}

func pathWithin(root, path string) bool {
	rel, err := filepath.Rel(root, path)
	return err == nil && rel != ".." &&
		!strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

func scanBatchSources(work string, batch *ImportBatch) map[string][]*ImportBatchFile {
	byRole := make(map[string][]*ImportBatchFile)
	byPath := make(map[string]*ImportBatchFile)
	seen := make(map[[2]string]bool)
	recycleDirs := make(map[string]bool)
	for _, group := range batch.Recycling {
		if group.Directory != "" {
			recycleDirs[strings.ToLower(group.Directory)] = true
		}
	}
	for _, source := range batch.Sources {
		sourcePath, err := filepath.Abs(source.Path)
		if err == nil {
			sourcePath, err = filepath.EvalSymlinks(sourcePath)
		}
		if err == nil && pathWithin(work, sourcePath) {
			err = fmt.Errorf("所选目录位于导入工作目录内")
		}
		if err == nil {
			var info os.FileInfo
			info, err = os.Stat(sourcePath)
			if err == nil && !info.IsDir() {
				err = fmt.Errorf("请选择目录")
			}
		}
		if err != nil {
			batch.Issues = append(batch.Issues, fmt.Sprintf("%s: %v", source.Path, err))
			continue
		}
		err = filepath.WalkDir(sourcePath, func(path string, entry os.DirEntry, err error) error {
			if err != nil {
				batch.Issues = append(batch.Issues, fmt.Sprintf("%s: %v", path, err))
				return nil
			}
			if entry.IsDir() {
				if pathWithin(work, path) || recycleDirs[strings.ToLower(path)] || entry.Name() == ".photo-agent-recycle" {
					return filepath.SkipDir
				}
				return nil
			}
			if !entry.Type().IsRegular() ||
				!(isJpg(path) || source.Role == "local" && isNef(path)) {
				return nil
			}
			key := [2]string{path, source.Role}
			if seen[key] {
				return nil
			}
			seen[key] = true
			file := byPath[path]
			if file == nil {
				file, err = inspectBatchFile(path, sourcePath)
				if err != nil {
					batch.Issues = append(batch.Issues, fmt.Sprintf("%s: %v", path, err))
					return nil
				}
				byPath[path] = file
			}
			byRole[source.Role] = append(byRole[source.Role], file)
			return nil
		})
		if err != nil {
			batch.Issues = append(batch.Issues, fmt.Sprintf("%s: %v", sourcePath, err))
		}
	}
	return byRole
}

type importMatchIndex struct {
	digest  map[string][]*ImportBatchFile
	stem    map[string][]*ImportBatchFile
	imageID map[string][]*ImportBatchFile
}

func newImportMatchIndex(files []*ImportBatchFile) importMatchIndex {
	index := importMatchIndex{
		digest:  make(map[string][]*ImportBatchFile),
		stem:    make(map[string][]*ImportBatchFile),
		imageID: make(map[string][]*ImportBatchFile),
	}
	for _, file := range files {
		index.add(file)
	}
	return index
}

func (index importMatchIndex) add(file *ImportBatchFile) {
	index.digest[file.SHA256] = append(index.digest[file.SHA256], file)
	base := baseNameOf(filepath.Base(file.Path))
	index.stem[base] = append(index.stem[base], file)
	if file.ImageID != "" {
		index.imageID[file.ImageID] = append(index.imageID[file.ImageID], file)
	}
}

func sameBatchShotTime(a, b string) bool {
	if a == "" || b == "" {
		return false
	}
	first, firstErr := time.Parse(time.RFC3339Nano, a)
	second, secondErr := time.Parse(time.RFC3339Nano, b)
	if firstErr != nil || secondErr != nil {
		return a == b
	}
	if first.Nanosecond() != 0 && second.Nanosecond() != 0 &&
		first.Nanosecond() != second.Nanosecond() {
		return false
	}
	return first.Equal(second) || first.Format("2006-01-02T15:04:05") ==
		second.Format("2006-01-02T15:04:05")
}

func compatibleBatchMetadata(a, b *ImportBatchFile) bool {
	if a.Camera != "" && b.Camera != "" && !strings.EqualFold(a.Camera, b.Camera) {
		return false
	}
	if a.ImageID != "" && b.ImageID != "" && a.ImageID != b.ImageID {
		return false
	}
	return a.ShotAt == "" || b.ShotAt == "" || sameBatchShotTime(a.ShotAt, b.ShotAt)
}

func (index importMatchIndex) exportedJPG(file *ImportBatchFile) (match, uncertain []*ImportBatchFile) {
	if exact := index.digest[file.SHA256]; len(exact) > 0 {
		return exact, nil
	}
	if file.ImageID != "" {
		for _, candidate := range index.imageID[file.ImageID] {
			if compatibleBatchMetadata(file, candidate) {
				match = append(match, candidate)
			}
		}
		if len(match) > 0 {
			return match, nil
		}
	}
	for _, candidate := range index.stem[baseNameOf(filepath.Base(file.Path))] {
		if !compatibleBatchMetadata(file, candidate) {
			continue
		}
		if sameBatchShotTime(file.ShotAt, candidate.ShotAt) {
			match = append(match, candidate)
		} else {
			uncertain = append(uncertain, candidate)
		}
	}
	return match, uncertain
}

func (index importMatchIndex) pairedNEF(jpg *ImportBatchFile) (paired *ImportBatchFile, candidates []*ImportBatchFile) {
	candidates = index.stem[baseNameOf(filepath.Base(jpg.Path))]
	var adjacent, supported []*ImportBatchFile
	for _, file := range candidates {
		if !compatibleBatchMetadata(jpg, file) {
			continue
		}
		if filepath.Dir(file.Path) == filepath.Dir(jpg.Path) {
			adjacent = append(adjacent, file)
		}
		if sameBatchShotTime(jpg.ShotAt, file.ShotAt) ||
			jpg.ImageID != "" && jpg.ImageID == file.ImageID {
			supported = append(supported, file)
		}
	}
	if len(adjacent) == 1 {
		return adjacent[0], adjacent
	}
	if len(adjacent) == 0 && len(supported) == 1 {
		return supported[0], supported
	}
	if len(adjacent) == 0 && len(candidates) == 1 &&
		compatibleBatchMetadata(jpg, candidates[0]) {
		return candidates[0], candidates
	}
	return nil, candidates
}

func batchEntryID(jpg, nef *ImportBatchFile) string {
	file := jpg
	if file == nil {
		file = nef
	}
	sum := sha256.Sum256([]byte(file.SHA256 + "\x00" + file.Path))
	return hex.EncodeToString(sum[:16])
}

func entryFilesKey(entry ImportBatchEntry) string {
	var jpg, nef string
	if entry.JPG != nil {
		jpg = entry.JPG.SHA256
	}
	if entry.NEF != nil {
		nef = entry.NEF.SHA256
	}
	return jpg + ":" + nef
}

func identicalImportFiles(files []*ImportBatchFile) bool {
	if len(files) == 0 {
		return false
	}
	for _, file := range files[1:] {
		if file.SHA256 != files[0].SHA256 {
			return false
		}
	}
	return true
}

func scanImportBatch(root string, batch, previous *ImportBatch) {
	batch.Entries = make([]ImportBatchEntry, 0)
	batch.Issues = make([]string, 0)
	if previous != nil {
		batch.Recycling = previous.Recycling
	}
	role := scanBatchSources(root, batch)
	var localJPG, nefList []*ImportBatchFile
	for _, file := range role["local"] {
		if isNef(file.Path) {
			nefList = append(nefList, file)
		} else {
			localJPG = append(localJPG, file)
		}
	}
	nefIndex := newImportMatchIndex(nefList)
	fullIndex := newImportMatchIndex(role["retained"])
	favoriteIndex := newImportMatchIndex(role["favorite"])
	startIndex := newImportMatchIndex(role["starting"])

	// Consider exported JPGs as originals where no camera JPG matches. Preserve
	// the camera JPG in mixed batches even when the iPad copy was re-encoded.
	selected := append([]*ImportBatchFile{}, localJPG...)
	seen := make(map[string]bool)
	for _, file := range selected {
		seen[file.SHA256] = true
	}
	selectedIndex := newImportMatchIndex(selected)
	exportUncertain := make(map[string]bool)
	for _, file := range append(append([]*ImportBatchFile{}, role["retained"]...), role["favorite"]...) {
		matches, uncertain := selectedIndex.exportedJPG(file)
		if len(matches) > 0 || seen[file.SHA256] {
			continue
		}
		if len(uncertain) > 0 {
			exportUncertain[file.Path] = true
		}
		seen[file.SHA256] = true
		selected = append(selected, file)
		selectedIndex.add(file)
	}
	reference := make(map[string]bool)
	if batch.Complete && len(batch.Issues) == 0 {
		for _, file := range role["starting"] {
			matches, uncertain := selectedIndex.exportedJPG(file)
			if len(matches) > 0 || len(uncertain) > 0 || seen[file.SHA256] {
				continue
			}
			nef, _ := nefIndex.pairedNEF(file)
			if nef == nil || !(sameBatchShotTime(file.ShotAt, nef.ShotAt) ||
				file.ImageID != "" && file.ImageID == nef.ImageID) {
				continue
			}
			// A starting-set JPG is evidence only. Only the paired local NEF
			// is eligible for cleanup in this case.
			seen[file.SHA256] = true
			reference[file.Path] = true
			selected = append(selected, file)
		}
	}

	for _, jpg := range selected {
		nef, candidates := nefIndex.pairedNEF(jpg)
		entry := ImportBatchEntry{
			ID: batchEntryID(jpg, nef), JPG: jpg, NEF: nef, NEFCandidates: candidates,
			Pair: "jpg_only", Decision: batchPending, Origin: "pending",
			ReferenceOnly: reference[jpg.Path], ShotAt: jpg.ShotAt,
		}
		if nef != nil {
			entry.Pair = "paired"
		} else if len(candidates) > 0 {
			entry.Pair = "review"
		}
		full, fullUncertain := fullIndex.exportedJPG(jpg)
		favorite, favoriteUncertain := favoriteIndex.exportedJPG(jpg)
		start, _ := startIndex.exportedJPG(jpg)
		entry.Inherited = batchKept
		if entry.ReferenceOnly {
			entry.Inherited = batchPending
		}
		switch {
		case len(favorite) == 1 || identicalImportFiles(favorite):
			entry.Inherited, entry.Origin = batchFavorite, "ipad"
		case len(favorite) > 1 || len(favoriteUncertain) > 0:
			entry.Conflict = true
		case identicalImportFiles(start) && len(full) == 0 && len(fullUncertain) == 0 &&
			batch.Complete && len(batch.Issues) == 0:
			entry.MissingFromExport = true
		case len(full) > 1 && !identicalImportFiles(full) || len(fullUncertain) > 0:
			entry.Conflict = true
		}
		entry.Decision = entry.Inherited
		if exportUncertain[jpg.Path] {
			entry.Conflict = true
		}
		batch.Entries = append(batch.Entries, entry)
	}

	// One NEF must never be claimed by two JPGs.
	claims := make(map[string]int)
	for _, entry := range batch.Entries {
		if entry.NEF != nil {
			claims[entry.NEF.Path]++
		}
	}
	for i := range batch.Entries {
		entry := &batch.Entries[i]
		if entry.NEF != nil && claims[entry.NEF.Path] > 1 {
			entry.NEF, entry.Pair = nil, "review"
		}
		if entry.MissingFromExport && entry.Pair == "review" {
			entry.MissingFromExport = false
		}
	}
	for _, nef := range nefList {
		if claims[nef.Path] == 0 {
			batch.Entries = append(batch.Entries, ImportBatchEntry{
				ID: batchEntryID(nil, nef), NEF: nef, Pair: "nef_only",
				Decision: batchPending, Origin: "pending",
			})
		}
	}
	if previous != nil {
		mergeImportBatch(batch, previous)
	}
}

func mergeImportBatch(batch, previous *ImportBatch) {
	priorByID := make(map[string]ImportBatchEntry)
	priorByContent := make(map[string][]ImportBatchEntry)
	newContentCount := make(map[string]int)
	for _, entry := range previous.Entries {
		if entry.Historical {
			continue
		}
		priorByID[entry.ID] = entry
		key := entryFilesKey(entry)
		priorByContent[key] = append(priorByContent[key], entry)
	}
	for _, entry := range batch.Entries {
		newContentCount[entryFilesKey(entry)]++
	}
	used := make(map[string]bool)
	for i := range batch.Entries {
		entry := &batch.Entries[i]
		old, exists := priorByID[entry.ID]
		if !exists {
			key := entryFilesKey(*entry)
			matches := priorByContent[key]
			if len(matches) != 1 || newContentCount[key] != 1 {
				continue
			}
			old = matches[0]
		}
		if old.Pair == "manual" {
			for _, candidate := range entry.NEFCandidates {
				if old.NEF != nil && old.NEF.Path == candidate.Path &&
					old.NEF.SHA256 == candidate.SHA256 {
					entry.NEF, entry.Pair = candidate, "manual"
				}
			}
			if old.NEF == nil && old.JPG != nil && entry.JPG != nil &&
				old.JPG.SHA256 == entry.JPG.SHA256 {
				entry.NEF, entry.Pair = nil, "manual"
			}
		}
		if entryFilesKey(old) != entryFilesKey(*entry) {
			continue
		}
		if used[old.ID] {
			continue
		}
		used[old.ID] = true
		entry.ID, entry.Upload = old.ID, old.Upload
		entry.StagedServer, entry.StageError = old.StagedServer, old.StageError
		if old.ShotAt != "" {
			entry.ShotAt = old.ShotAt
		}
		if old.Origin == "manual" || old.Upload != nil && old.Upload.Verified {
			entry.Decision, entry.Origin = old.Decision, old.Origin
			entry.Conflict = entry.Conflict || entry.Inherited == batchFavorite &&
				old.Decision != entry.Inherited &&
				(old.Conflict || old.Inherited != entry.Inherited)
		}
	}
	for _, entry := range previous.Entries {
		if used[entry.ID] || entry.Upload == nil && entry.StagedServer == "" {
			continue
		}
		entry.Historical = entry.Upload != nil && entry.Upload.Verified || entry.Historical
		for _, current := range batch.Entries {
			if current.ID == entry.ID {
				entry.Historical = true
				entry.ID = strings.TrimSuffix(entry.ID, "-prior") + "-prior"
				break
			}
		}
		batch.Entries = append(batch.Entries, entry)
	}
	batch.Undo = previous.Undo
	if previous.Bursts != nil {
		server := previous.Bursts.Server
		if slices.Equal(importBurstInputs(batch, server), importBurstInputs(previous, server)) {
			batch.Bursts = previous.Bursts
		}
	}
}

func validBatchDecision(decision string) bool {
	switch decision {
	case batchKept, batchFavorite, batchDiscarded:
		return true
	default:
		return false
	}
}

func (batch *ImportBatch) setDecisions(ids []string, decision string) error {
	if !validBatchDecision(decision) || len(ids) == 0 {
		return fmt.Errorf("无效审阅决定")
	}
	selected := make(map[string]bool)
	for _, id := range ids {
		selected[id] = true
	}
	undo := make([]ImportBatchUndo, 0, len(ids))
	for i := range batch.Entries {
		entry := &batch.Entries[i]
		if !selected[entry.ID] {
			continue
		}
		if entry.Historical || entry.JPG == nil || entry.ReferenceOnly && decision != batchDiscarded {
			continue
		}
		if entry.Upload != nil && entry.Upload.Verified {
			continue
		}
		undo = append(undo, ImportBatchUndo{entry.ID, entry.Decision, entry.Origin, entry.Conflict})
		entry.Decision, entry.Origin, entry.Conflict = decision, "manual", false
	}
	if len(undo) != len(selected) {
		return fmt.Errorf("部分条目已变更或无法应用该决定，请刷新批次")
	}
	batch.Undo = undo
	return nil
}

func (batch *ImportBatch) undoDecisions() {
	moved := make(map[string]bool)
	for _, group := range batch.Recycling {
		for _, file := range group.Files {
			switch file.Status {
			case "staged", "sending", "deleting", "recycled", "deleted":
				moved[file.Source] = true
			case "restored":
				delete(moved, file.Source)
			}
		}
	}
	for i := range batch.Entries {
		entry := &batch.Entries[i]
		if entry.Upload != nil && entry.Upload.Verified {
			continue
		}
		if entry.JPG != nil && moved[entry.JPG.Path] || entry.NEF != nil && moved[entry.NEF.Path] {
			continue
		}
		for _, undo := range batch.Undo {
			if undo.ID == entry.ID {
				entry.Decision, entry.Origin, entry.Conflict = undo.Decision, undo.Origin, undo.Conflict
				break
			}
		}
	}
	batch.Undo = nil
}

type ImportBatchSummary struct {
	ID       string `json:"id"`
	Activity string `json:"activity"`
	Name     string `json:"name"`
	Step     string `json:"step,omitempty"`
}

func listImportBatches(root string) ([]ImportBatchSummary, error) {
	result := make([]ImportBatchSummary, 0)
	items, err := os.ReadDir(root)
	if os.IsNotExist(err) {
		return result, nil
	}
	if err != nil {
		return nil, err
	}
	for _, item := range items {
		if !item.IsDir() || !validImportBatchID(item.Name()) {
			continue
		}
		batch, err := loadImportBatch(root, item.Name())
		if err != nil {
			return nil, err
		}
		result = append(result, ImportBatchSummary{ID: batch.ID, Activity: batch.Activity, Name: batch.Name, Step: batch.Step})
	}
	used := make(map[string]bool)
	for _, batch := range result {
		if batch.Name != "" {
			used[strings.ToLower(batch.Name)] = true
		}
	}
	for i := range result {
		if result[i].Name == "" {
			result[i].Name = nextImportBatchName(result[i].Activity, used)
			used[strings.ToLower(result[i].Name)] = true
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Name < result[j].Name })
	return result, nil
}

func nextImportBatchName(activity string, used map[string]bool) string {
	name := activity
	for i := 1; used[strings.ToLower(name)]; i++ {
		name = fmt.Sprintf("%s-%d", activity, i)
	}
	return name
}

func importBatchName(root string, batch *ImportBatch) (string, error) {
	if batch.Name != "" {
		return batch.Name, nil
	}
	list, err := listImportBatches(root)
	if err != nil {
		return "", err
	}
	used := make(map[string]bool)
	for _, item := range list {
		if item.ID == batch.ID {
			return item.Name, nil
		}
		used[strings.ToLower(item.Name)] = true
	}
	return nextImportBatchName(batch.Activity, used), nil
}

func importFileDigest(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	digest := sha256.New()
	_, err = io.Copy(digest, file)
	return hex.EncodeToString(digest.Sum(nil)), err
}

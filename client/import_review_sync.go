package main

import (
	"context"
	"fmt"
	"net/url"
	"path/filepath"
	"slices"
)

type ImportReviewSync struct {
	EntryIDs  []string `json:"entry_ids,omitempty"`
	Server    string   `json:"server"`
	Revision  uint64   `json:"revision"`
	UpdatedAt string   `json:"updated_at"`
	State     string   `json:"state"`
}

type importRemoteReviewEntry struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	SHA256   string `json:"sha256"`
	ShotAt   string `json:"shot_at,omitempty"`
	Decision string `json:"decision"`
	Origin   string `json:"origin"`
}

type importRemoteReview struct {
	BatchID   string                    `json:"batch_id"`
	Name      string                    `json:"name"`
	Activity  string                    `json:"activity"`
	State     string                    `json:"state"`
	Revision  uint64                    `json:"revision"`
	UpdatedAt string                    `json:"updated_at"`
	Entries   []importRemoteReviewEntry `json:"entries"`
	Fine      [][]string                `json:"fine,omitempty"`
	Coarse    [][]string                `json:"coarse,omitempty"`
}

type importRemoteChange struct {
	ID       string `json:"id"`
	Decision string `json:"decision"`
}

func (batch *ImportBatch) applyRemoteReview(remote *importRemoteReview) error {
	if remote.BatchID != batch.ID {
		return fmt.Errorf("服务器选片批次不匹配")
	}
	batch.Review.EntryIDs = nil
	entryMap := make(map[string]importRemoteReviewEntry)
	for _, entry := range remote.Entries {
		entryMap[entry.ID] = entry
		batch.Review.EntryIDs = append(batch.Review.EntryIDs, entry.ID)
	}
	for i := range batch.Entries {
		entry := &batch.Entries[i]
		other, ok := entryMap[entry.ID]
		if !ok || entry.JPG == nil || entry.JPG.SHA256 != other.SHA256 ||
			entry.Historical || entry.ReferenceOnly || (entry.Upload != nil && entry.Upload.Verified) {
			continue
		}
		entry.Decision, entry.Origin = other.Decision, other.Origin
	}
	batch.Review.Revision = remote.Revision
	batch.Review.UpdatedAt, batch.Review.State = remote.UpdatedAt, remote.State
	return nil
}

func (batch *ImportBatch) refreshRemoteReview() error {
	if batch.Review == nil {
		return nil
	}
	var remote importRemoteReview
	err := reviewHTTP(context.Background(), batch.Review.Server,
		"review?batch_id="+url.QueryEscape(batch.ID), nil, &remote)
	if err != nil {
		return err
	}
	return batch.applyRemoteReview(&remote)
}

func (batch *ImportBatch) editRemoteReview(changes []importRemoteChange, state string) error {
	if batch.Review == nil {
		return nil
	}
	changes = slices.DeleteFunc(changes, func(change importRemoteChange) bool {
		return !slices.Contains(batch.Review.EntryIDs, change.ID)
	})
	if len(changes) == 0 && state == "" {
		return nil
	}
	request := struct {
		BatchID string               `json:"batch_id"`
		Changes []importRemoteChange `json:"changes"`
		State   string               `json:"state,omitempty"`
	}{batch.ID, changes, state}
	var remote importRemoteReview
	err := reviewHTTP(context.Background(), batch.Review.Server,
		"review/edit", request, &remote)
	if err != nil {
		return err
	}
	return batch.applyRemoteReview(&remote)
}

func (a *App) PublishImportReview(id, server string) (*ImportBatch, error) {
	return a.editImportReview(id, func(batch *ImportBatch) error {
		if batch.Review != nil && batch.Review.Server != server {
			return fmt.Errorf("此批次已连接其他服务器，请使用原服务器完成选片")
		}
		input := importRemoteReview{
			BatchID: batch.ID, Name: batch.Name, Activity: batch.Activity,
			Entries: make([]importRemoteReviewEntry, 0),
		}
		for _, entry := range batch.Entries {
			if entry.JPG == nil || entry.StagedServer != server || entry.Historical ||
				entry.ReferenceOnly || entry.Conflict || entry.Pair == "review" ||
				(entry.Upload != nil && entry.Upload.Verified) {
				continue
			}
			input.Entries = append(input.Entries, importRemoteReviewEntry{
				ID: entry.ID, Name: filepath.Base(entry.JPG.Path),
				SHA256: entry.JPG.SHA256, ShotAt: entry.ShotAt,
				Decision: entry.Decision, Origin: entry.Origin,
			})
		}
		if len(input.Entries) == 0 {
			return fmt.Errorf("没有可手机接续的照片，请先处理需核对项并上传 JPG")
		}
		if batch.Bursts != nil && batch.Bursts.Server == server {
			input.Fine, input.Coarse = batch.Bursts.Fine, batch.Bursts.Coarse
		}
		var remote importRemoteReview
		err := reviewHTTP(context.Background(), server, "review/publish", input, &remote)
		if err != nil {
			return err
		}
		if batch.Review == nil {
			batch.Review = &ImportReviewSync{Server: server}
		}
		return batch.applyRemoteReview(&remote)
	})
}

func (a *App) RefreshImportReview(id string) (*ImportBatch, error) {
	return a.editImportBatch(id, func(batch *ImportBatch) error {
		if batch.Review == nil {
			return fmt.Errorf("请先开启手机选片")
		}
		return batch.refreshRemoteReview()
	})
}

// Compatibility adapters for the legacy generated CRUD API. Activity metadata
// lives in directories; these routes must not write the retired events table.
package service

import (
	"backend/internal/pkg/api"
	"context"
	"time"
)

func legacyTimelineEvent(item *api.TimelineEventDetail) *api.TimelineEventInfo {
	date, _ := time.Parse("2006-01-02", item.Date)
	if date.IsZero() {
		date, _ = time.Parse(time.RFC3339, item.Date)
	}
	var seconds int64
	if !date.IsZero() {
		seconds = date.Unix()
	}
	return &api.TimelineEventInfo{ID: item.Id, EventDate: seconds, Event: item.Event, Note: item.Note}
}

func (s *DefaultCURDServer) AddTimelineEvent(ctx context.Context, req *api.AddTimelineEventRequest) (*api.AddTimelineEventResponse, error) {
	if req.TimelineEvent == nil {
		return nil, api.ErrorInvalidArgument("活动不能为空")
	}
	item := req.TimelineEvent
	server := TimelineServer{}
	result, err := server.SaveEvent(ctx, &api.SaveTimelineEventRequest{Event: item.Event, Date: time.Unix(item.EventDate, 0).Format("2006-01-02"), Note: item.Note})
	if err != nil {
		return nil, err
	}
	return &api.AddTimelineEventResponse{TimelineEvent: &api.TimelineEventInfo{ID: result.Id, Event: item.Event, EventDate: item.EventDate, Note: item.Note}}, nil
}

func (s *DefaultCURDServer) GetTimelineEventList(ctx context.Context, req *api.GetTimelineEventListRequest) (*api.GetTimelineEventListResponse, error) {
	server := TimelineServer{}
	result, err := server.ListEvents(ctx, &api.Empty{})
	if err != nil {
		return nil, err
	}
	filter := make(map[string]bool)
	for _, id := range req.IDList {
		filter[id] = true
	}
	response := &api.GetTimelineEventListResponse{TimelineEventList: make([]*api.TimelineEventInfo, 0, len(result.Events))}
	for _, item := range result.Events {
		if len(filter) == 0 || filter[item.Id] {
			response.TimelineEventList = append(response.TimelineEventList, legacyTimelineEvent(item))
		}
	}
	return response, nil
}

func (s *DefaultCURDServer) UpdateTimelineEvent(ctx context.Context, req *api.UpdateTimelineEventRequest) (*api.UpdateTimelineEventResponse, error) {
	if req.TimelineEvent == nil {
		return nil, api.ErrorInvalidArgument("活动不能为空")
	}
	item := req.TimelineEvent
	server := TimelineServer{}
	_, err := server.SaveEvent(ctx, &api.SaveTimelineEventRequest{Id: item.ID, Event: item.Event, Date: time.Unix(item.EventDate, 0).Format("2006-01-02"), Note: item.Note})
	if err != nil {
		return nil, err
	}
	return &api.UpdateTimelineEventResponse{TimelineEvent: item}, nil
}

func (s *DefaultCURDServer) DelTimelineEventByIDList(ctx context.Context, req *api.DelTimelineEventByIDListRequest) (*api.Empty, error) {
	server := TimelineServer{}
	for _, id := range req.IDList {
		_, err := server.DeleteEvent(ctx, &api.DeleteTimelineEventRequest{Id: id})
		if err != nil {
			return nil, err
		}
	}
	return &api.Empty{}, nil
}

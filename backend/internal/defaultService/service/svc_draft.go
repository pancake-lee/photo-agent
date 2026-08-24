package service

import (
	"encoding/json"

	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"
	"backend/internal/pkg/perr"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/putil"

	"github.com/go-kratos/kratos/v2/transport/grpc"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

type DraftServer struct {
	api.UnimplementedDefaultCURDServer
}

func (s *DraftServer) Reg(grpcSrv *grpc.Server, httpSrv *khttp.Server) {
	if httpSrv != nil {
		r := httpSrv.Route("/")
		r.POST("/api/v1/drafts", s.CreateDraft)
		r.PUT("/api/v1/drafts/{id}", s.UpdateDraft)
		r.DELETE("/api/v1/drafts/{id}", s.DeleteDraft)
		r.GET("/api/v1/drafts", s.ListDrafts)
		r.GET("/api/v1/drafts/{id}", s.GetDraft)
	}
}

type draftCreateRequest struct {
	Title    string   `json:"title"`
	Content  string   `json:"content"`
	PhotoIDs []string `json:"photo_ids"`
	Style    string   `json:"style"`
	Source   string   `json:"source"`
}

type draftUpdateRequest struct {
	Title    string   `json:"title"`
	Content  string   `json:"content"`
	PhotoIDs []string `json:"photo_ids"`
	Style    string   `json:"style"`
	Source   string   `json:"source"`
	Status   string   `json:"status"`
}

type draftResponse struct {
	ID        string   `json:"id"`
	Title     string   `json:"title"`
	Content   string   `json:"content"`
	PhotoIDs  []string `json:"photo_ids"`
	Style     string   `json:"style"`
	Source    string   `json:"source"`
	Status    string   `json:"status"`
	CreatedAt string   `json:"created_at"`
	UpdatedAt string   `json:"updated_at"`
}

func draftDO2Response(do *data.DraftDO) *draftResponse {
	ids := parsePhotoIDs(do.PhotoIDs)
	return &draftResponse{
		ID:        do.ID,
		Title:     do.Title,
		Content:   do.Content,
		PhotoIDs:  ids,
		Style:     do.Style,
		Source:    do.Source,
		Status:    do.Status,
		CreatedAt: do.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
		UpdatedAt: do.UpdatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}
}

func parsePhotoIDs(s string) []string {
	if s == "" {
		return []string{}
	}
	var ids []string
	if err := json.Unmarshal([]byte(s), &ids); err != nil {
		return []string{}
	}
	return ids
}

func marshalPhotoIDs(ids []string) string {
	if len(ids) == 0 {
		return "[]"
	}
	b, err := json.Marshal(ids)
	if err != nil {
		return "[]"
	}
	return string(b)
}

func (s *DraftServer) CreateDraft(kctx khttp.Context) error {
	_ctx := kctx.Request().Context()
	ctx := papp.NewAppCtx(_ctx)

	var req draftCreateRequest
	if err := json.NewDecoder(kctx.Request().Body).Decode(&req); err != nil {
		return ctx.Log.LogErr(perr.ErrParamInvalid)
	}

	draft := &data.DraftDO{
		ID:       putil.UUID(),
		Title:    req.Title,
		Content:  req.Content,
		PhotoIDs: marshalPhotoIDs(req.PhotoIDs),
		Style:    req.Style,
		Source:   req.Source,
		Status:   "draft",
	}

	if err := data.DraftDAO.Add(ctx, draft); err != nil {
		return err
	}

	return kctx.Result(201, draftDO2Response(draft))
}

func (s *DraftServer) UpdateDraft(kctx khttp.Context) error {
	id := kctx.Vars().Get("id")
	_ctx := kctx.Request().Context()
	ctx := papp.NewAppCtx(_ctx)

	existing, err := data.DraftDAO.GetByID(ctx, id)
	if err != nil {
		return err
	}

	var req draftUpdateRequest
	if err := json.NewDecoder(kctx.Request().Body).Decode(&req); err != nil {
		return ctx.Log.LogErr(perr.ErrParamInvalid)
	}

	if req.Title != "" {
		existing.Title = req.Title
	}
	if req.Content != "" {
		existing.Content = req.Content
	}
	if req.PhotoIDs != nil {
		existing.PhotoIDs = marshalPhotoIDs(req.PhotoIDs)
	}
	if req.Style != "" {
		existing.Style = req.Style
	}
	if req.Source != "" {
		existing.Source = req.Source
	}
	if req.Status != "" {
		existing.Status = req.Status
	}

	if err := data.DraftDAO.Update(ctx, existing); err != nil {
		return err
	}

	return kctx.Result(200, draftDO2Response(existing))
}

func (s *DraftServer) DeleteDraft(kctx khttp.Context) error {
	id := kctx.Vars().Get("id")
	_ctx := kctx.Request().Context()
	ctx := papp.NewAppCtx(_ctx)

	if err := data.DraftDAO.DelByID(ctx, id); err != nil {
		return err
	}

	return kctx.Result(200, map[string]string{"status": "deleted", "id": id})
}

func (s *DraftServer) ListDrafts(kctx khttp.Context) error {
	_ctx := kctx.Request().Context()
	ctx := papp.NewAppCtx(_ctx)

	list, err := data.DraftDAO.GetAll(ctx)
	if err != nil {
		return err
	}

	items := make([]*draftResponse, len(list))
	for i, d := range list {
		items[i] = draftDO2Response(d)
	}
	return kctx.Result(200, map[string]any{"items": items, "total": len(items)})
}

func (s *DraftServer) GetDraft(kctx khttp.Context) error {
	id := kctx.Vars().Get("id")
	_ctx := kctx.Request().Context()
	ctx := papp.NewAppCtx(_ctx)

	draft, err := data.DraftDAO.GetByID(ctx, id)
	if err != nil {
		return err
	}

	return kctx.Result(200, draftDO2Response(draft))
}

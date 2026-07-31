"""
    FastAPI 服务器 — 为 Web 前端提供对话 API。

    用法:
        from chain.server import create_app, run_server
        app = create_app(cfg)
        # 开发: uvicorn chain.server:app --port 10005
        # 或直接: run_server(cfg, port=10005)
"""

import sys
import pathlib
import logging
import json
import uuid
import datetime
import os
import threading
import queue


import fastapi
import fastapi.middleware.cors
import fastapi.responses
import pydantic

import chain.photo_agent as photo_agent
import chain.session_store as session_store
import chain.embed_queue as embed_queue
import chain.evaluation as evaluation_mod
import chain.cluster as cluster_mod
import chain.suggest as suggest_mod
import chain.tracer as tracer_mod
import chain.eval_engine as eval_engine
import vectorstore.chroma_client as chroma_client
import config as config_mod

logger = logging.getLogger(__name__)

# ── 黄金用例 JSON 存储 ─────────────────────────────────────
# 注意: 黄金用例存储路径已迁移到 app.state.golden_queries_dir，
# 不再使用模块级全局变量。各函数通过 request.app.state 访问。


def _normalize_ext(filename: str) -> str:
    """去除文件扩展名，兼容大小写和 jpg/jpeg 变化。"""
    if not filename:
        return ""
    return os.path.splitext(filename)[0]


def _build_filename_to_uuid(go_backend_url: str) -> dict[str, str]:
    """从 Go 后端获取全部照片，构建 文件名(去后缀) → UUID 映射。"""
    import utils.http_client as http_utils
    mapping: dict[str, str] = {}
    client = http_utils.create_client(timeout=30.0)
    page = 1
    try:
        while True:
            resp = client.get(
                f"{go_backend_url}/api/v1/photos",
                params={"page": page, "page_size": 500},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", data if isinstance(data, list) else [])
            if not items:
                break
            for p in items:
                pid = p.get("id", "")
                fname = p.get("filename", "")
                if pid and fname:
                    mapping.setdefault(_normalize_ext(fname), pid)
            page += 1
    finally:
        client.close()
    return mapping



def _golden_queries_path(dir_path: pathlib.Path) -> pathlib.Path:
    """返回 golden_queries.json 的路径。"""
    return dir_path / "golden_queries.json"


def _load_golden_queries(dir_path: pathlib.Path) -> list[dict]:
    """加载所有黄金用例。文件不存在时返回空列表。

    兼容旧格式 relevant_photo_ids (list[str])，自动迁移为
    新格式 relevant_photos (list[{photo_id, filename}]).
    """
    fp = _golden_queries_path(dir_path)
    if not fp.exists():
        return []
    try:
        items = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    # 迁移旧格式 → 新格式
    migrated = False
    for it in items:
        if "relevant_photos" not in it and "relevant_photo_ids" in it:
            raw = it.pop("relevant_photo_ids")
            it["relevant_photos"] = [
                {"photo_id": pid, "filename": pid} for pid in raw
            ]
            migrated = True
    if migrated:
        _save_golden_queries(items, dir_path)
    return items


def _save_golden_queries(items: list[dict], dir_path: pathlib.Path) -> None:
    """保存黄金用例列表到 JSON 文件。"""
    fp = _golden_queries_path(dir_path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(
        json.dumps(items, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


# ── 选题历史 JSON 存储 ─────────────────────────────────────
# v2（suggest_history_v2.json）是唯一数据源。
# suggest_history.json 自 B13 起不再写入，仅保留文件供回退读取。

_suggest_history_lock = threading.Lock()


def _suggest_history_path(dir_path: pathlib.Path) -> pathlib.Path:
    """返回选题历史 v2 文件的路径（唯一数据源）。"""
    return dir_path / "suggest_history_v2.json"


def _suggest_history_v1_path(dir_path: pathlib.Path) -> pathlib.Path:
    """返回旧 v1 文件的路径（只读，用于懒迁移回退）。"""
    return dir_path / "suggest_history.json"


def _load_suggest_history(dir_path: pathlib.Path) -> list[dict]:
    """加载选题历史（v2 格式）。文件不存在时返回空列表。"""
    fp = _suggest_history_path(dir_path)
    if not fp.exists():
        return []
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_suggest_history(items: list[dict], dir_path: pathlib.Path) -> None:
    """保存选题历史列表到 v2 JSON 文件。"""
    fp = _suggest_history_path(dir_path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    try:
        fp.write_text(
            json.dumps(items, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError as e:
        logger.error("保存选题历史失败: %s", e)


def _migrate_to_v2(v1_item: dict, project_root: pathlib.Path) -> dict | None:
    """将 v1 单条记录懒迁移为 v2 格式（创建 v0 版本，不含步骤快照）。

    返回 v2 记录字典，失败返回 None。
    """
    import chain.trace_replay as trace_replay

    v2_id = v1_item.get("id", "")
    trace_id = v1_item.get("trace_id", "")

    # 尝试从 trace 重建步骤
    steps: list[dict] = []
    trace_expired = True
    if trace_id:
        try:
            replayed, expired = trace_replay.replay_trace(project_root, trace_id)
            trace_expired = expired
            if not expired:
                steps = [
                    {
                        "event": s.event,
                        "label": s.label,
                        "group": s.group,
                        "stage": s.stage,
                        "timestamp": s.timestamp,
                        "data": s.data,
                        "payload_content": s.payload_content,
                        "payload_ref": s.payload_ref,
                    }
                    for s in replayed
                ]
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            logger.warning(
                "v2 迁移: trace 重放失败 trace_id=%s, 错误类型=%s: %s",
                trace_id, type(e).__name__, e,
            )
            trace_expired = True

    v0_version = {
        "version_id": f"{v2_id}-v0",
        "parent_version_id": None,
        "created_at": v1_item.get("generated_at", ""),
        "created_from": "auto",
        "modified_step": None,
        "trace_id": trace_id,
        "trace_expired": trace_expired,
        "steps": steps,
    }

    return {
        "id": v2_id,
        "generated_at": v1_item.get("generated_at", ""),
        "pipeline": v1_item.get("pipeline", ""),
        "total_photos": v1_item.get("total_photos", 0),
        "cluster_count": v1_item.get("cluster_count", 0),
        "rating": v1_item.get("rating", 0),
        "title": v1_item.get("title", ""),
        "angle": v1_item.get("angle", ""),
        "rationale": v1_item.get("rationale", ""),
        "category": v1_item.get("category", ""),
        "photo_ids": v1_item.get("photo_ids", []),
        "photo_sequence": v1_item.get("photo_sequence", []),
        "intuition_source": v1_item.get("intuition_source", []),
        "error": v1_item.get("error", ""),
        "versions": [v0_version],
        "current_version_id": v0_version["version_id"],
    }


def _try_refill_steps(v2_item: dict, project_root: pathlib.Path) -> bool:
    """补偿修复：若 v2 条目版本步骤为空但 trace 未过期，尝试从 trace 回放填充。

    返回 True 表示有填充发生（调用方需要写回文件）。
    """
    import chain.trace_replay as trace_replay

    refilled = False
    for ver in v2_item.get("versions", []):
        if ver.get("steps"):
            continue
        if ver.get("trace_expired", True):
            continue
        trace_id = ver.get("trace_id", "")
        if not trace_id:
            continue
        try:
            replayed, expired = trace_replay.replay_trace(project_root, trace_id)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            logger.warning(
                "补偿回放失败 trace_id=%s: %s", trace_id, e,
            )
            continue
        if expired or not replayed:
            continue
        ver["steps"] = [
            {
                "event": s.event, "label": s.label, "group": s.group,
                "stage": s.stage, "timestamp": s.timestamp, "data": s.data,
                "payload_content": s.payload_content, "payload_ref": s.payload_ref,
            }
            for s in replayed
        ]
        ver["trace_expired"] = False
        refilled = True

    return refilled


# ── Pydantic 模型 ──────────────────────────────────────────

class CreateSessionRequest(pydantic.BaseModel):
    title: str | None = None


class UpdateSessionRequest(pydantic.BaseModel):
    title: str


class SendMessageRequest(pydantic.BaseModel):
    question: str


class SessionResponse(pydantic.BaseModel):
    session_id: str
    title: str
    message_count: int = 0
    created_at: str
    updated_at: str


class SessionDetailResponse(pydantic.BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[dict]


class PhotoRef(pydantic.BaseModel):
    photo_id: str
    filename: str
    image_url: str


class MessageResponse(pydantic.BaseModel):
    message_id: int
    answer: str
    query_type: str
    photos: list[PhotoRef] = []


class HealthResponse(pydantic.BaseModel):
    status: str
    model: str


# ── 黄金用例 Pydantic 模型 ──────────────────────────────

class GoldenPhotoRef(pydantic.BaseModel):
    photo_id: str
    filename: str
    uuid: str = ""  # Go 后端 UUID，前端用于构造图片 URL；列表接口自动填充


class GoldenQueryCreateRequest(pydantic.BaseModel):
    query_text: str
    relevant_photos: list[GoldenPhotoRef]
    category: str = ""
    notes: str = ""


class GoldenQueryItem(pydantic.BaseModel):
    id: str
    query_text: str
    relevant_photos: list[GoldenPhotoRef]
    category: str
    notes: str
    created_at: str
    updated_at: str


class EvalPhotoItem(pydantic.BaseModel):
    photo_id: str      # 文件名（去后缀）
    filename: str      # 同 photo_id
    uuid: str          # Go 后端 UUID，用于构造图片 URL


class EvalDetailItem(pydantic.BaseModel):
    question: str
    precision: float
    recall: float
    mrr: float
    hits: int = 0
    retrieved: int = 0
    relevant: int = 0
    effective_k: int = 10
    hit_ids: list[EvalPhotoItem] = []
    miss_ids: list[EvalPhotoItem] = []
    remaining_ids: list[EvalPhotoItem] = []


class EvalResultResponse(pydantic.BaseModel):
    precision_at_k: float
    recall_at_k: float
    mrr: float
    total: int
    precision_k: int
    details: list[EvalDetailItem]


# ── 聚类 Pydantic 模型 ────────────────────────────────────

class ClusterRunRequest(pydantic.BaseModel):
    min_cluster_size: int = 5
    min_samples: int = 3
    umap_n_neighbors: int = 15
    umap_min_dist: float = 0.1
    umap_n_components: int = 5
    umap_metric: str = "cosine"


class ClusterPhotoItem(pydantic.BaseModel):
    photo_id: str
    filename: str
    distance_to_centroid: float


class ClusterItem(pydantic.BaseModel):
    cluster_id: int
    label: str
    theme_description: str = ""
    size: int
    coherence_score: float
    photos: list[ClusterPhotoItem] = []


class ClusterStatsResponse(pydantic.BaseModel):
    total_photos: int
    clustered_photos: int
    noise_photos: int
    num_clusters: int
    duration_seconds: float


class ClusterResultSummary(pydantic.BaseModel):
    id: str
    created_at: str
    params: dict
    stats: ClusterStatsResponse
    cluster_labels: list[dict] = []


class ClusterResultDetail(pydantic.BaseModel):
    id: str
    created_at: str
    params: dict
    stats: ClusterStatsResponse
    clusters: list[ClusterItem]


# ── 应用工厂 ──────────────────────────────────────────────

def create_app(cfg: config_mod.Config) -> fastapi.FastAPI:
    """创建 FastAPI 应用，绑定配置和 Agent 实例。"""

    app = fastapi.FastAPI(
        title="Photo Agent Chat API",
        version="0.1.0",
        description="照片 AI 助手对话接口",
    )

    # CORS — 开发阶段允许所有来源
    # 注意: allow_credentials=True 时 allow_origins 不能是 *
    app.add_middleware(
        fastapi.middleware.cors.CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 初始化核心组件
    db_path = _resolve_db_path(cfg)
    store = session_store.SessionStore(db_path)
    agent = photo_agent.PhotoAgent(cfg)

    # 将实例挂到 app.state 上，路由中通过 request.app.state 访问
    app.state.store = store
    app.state.agent = agent

    # 初始化 Embedding 相关组件
    chroma_store = chroma_client.ChromaPhotoStore(
        persist_dir=str(cfg.resolve_path("./data/chroma")),
        collection_name="photos",
    )
    app.state.chroma_store = chroma_store
    app.state.cfg = cfg

    embed_q = embed_queue.EmbedQueue(cfg, chroma_store)
    app.state.embed_queue = embed_q

    # 初始化黄金用例存储路径（存入 app.state，避免模块级全局变量）
    app.state.golden_queries_dir = cfg.resolve_path("./data")

    # 初始化聚类结果存储路径（存入 app.state，避免模块级全局变量）
    app.state.cluster_dir = cfg.resolve_path("./data/clusters")
    app.state.cluster_dir.mkdir(parents=True, exist_ok=True)

    # 初始化选题历史存储路径
    app.state.suggest_history_dir = cfg.resolve_path("./data")

    # ── 注册路由 ──────────────────────────────────────────

    @app.get("/api/chat/health", response_model=HealthResponse)
    async def health():
        return {"status": "ok", "model": cfg.llm_model}

    @app.post("/api/chat/sessions", response_model=SessionResponse, status_code=201)
    async def create_session(req: fastapi.Request, body: CreateSessionRequest = CreateSessionRequest()):
        s = req.app.state.store
        result = s.create_session(title=body.title)
        result["message_count"] = 0
        return result

    @app.get("/api/chat/sessions", response_model=list[SessionResponse])
    async def list_sessions(req: fastapi.Request):
        s = req.app.state.store
        return s.list_sessions()

    @app.get("/api/chat/sessions/{session_id}", response_model=SessionDetailResponse)
    async def get_session(session_id: str, req: fastapi.Request):
        s = req.app.state.store
        result = s.get_session(session_id)
        if result is None:
            raise fastapi.HTTPException(status_code=404, detail="会话不存在")
        return result

    @app.patch("/api/chat/sessions/{session_id}", response_model=dict)
    async def update_session(session_id: str, body: UpdateSessionRequest, req: fastapi.Request):
        s = req.app.state.store
        ok = s.update_title(session_id, body.title)
        if not ok:
            raise fastapi.HTTPException(status_code=404, detail="会话不存在")
        return {"session_id": session_id, "title": body.title}

    @app.delete("/api/chat/sessions/{session_id}", response_model=dict)
    async def delete_session(session_id: str, req: fastapi.Request):
        s = req.app.state.store
        ok = s.delete_session(session_id)
        if not ok:
            raise fastapi.HTTPException(status_code=404, detail="会话不存在")
        return {"ok": True}

    @app.get("/api/chat/sessions/{session_id}/messages", response_model=list[dict])
    async def get_messages(session_id: str, req: fastapi.Request):
        s = req.app.state.store
        if s.get_session(session_id) is None:
            raise fastapi.HTTPException(status_code=404, detail="会话不存在")
        return s.get_messages(session_id)

    @app.post("/api/chat/sessions/{session_id}/messages", response_model=MessageResponse)
    async def send_message(session_id: str, body: SendMessageRequest, req: fastapi.Request):
        s: session_store.SessionStore = req.app.state.store
        agent_inst: photo_agent.PhotoAgent = req.app.state.agent

        # 验证会话存在
        if s.get_session(session_id) is None:
            raise fastapi.HTTPException(status_code=404, detail="会话不存在")

        question = body.question.strip()
        if not question:
            raise fastapi.HTTPException(status_code=400, detail="问题不能为空")

        # 保存用户消息
        s.add_message(session_id, "user", question)

        # 调用 Agent 路由
        try:
            result = agent_inst.route(question)
        except Exception as exc:
            logger.exception("Agent 路由失败")
            # 保存错误消息（仅向前端暴露通用提示，避免泄露内部信息）
            s.add_message(session_id, "assistant", "抱歉，处理请求时发生内部错误，请稍后重试。", query_type="error")
            raise fastapi.HTTPException(status_code=500, detail="处理请求时发生内部错误")

        answer = result.get("answer", "") or "未能获取回答。"
        query_type = result.get("query_type", "")
        photos_raw = result.get("photos", [])

        # 序列化照片引用
        import json
        photos_json = json.dumps(photos_raw, ensure_ascii=False) if photos_raw else ""

        # 保存 AI 回复
        msg_id = s.add_message(
            session_id, "assistant", answer,
            query_type=query_type,
            photos_json=photos_json,
        )

        # 首条提问后自动更新标题
        # 计算当前 user 消息数（包括刚保存的这条）= 1 表示是第一条
        user_count = sum(
            1 for m in s.get_messages(session_id) if m["role"] == "user"
        )
        if user_count == 1:
            new_title = session_store._format_question_title(question)
            s.update_title(session_id, new_title)

        return {
            "message_id": msg_id,
            "answer": answer,
            "query_type": query_type,
            "photos": photos_raw,
        }

    # ── Embedding API ─────────────────────────────────────

    @app.get("/api/embed/stats")
    async def embed_stats(req: fastapi.Request):
        """Embedding 统计（以 Go 照片为索引源，交叉比对 ChromaDB）。

        与 ChromaDB 原始数据不同，此端点先获取 Go 后端全量照片 ID，
        再与 ChromaDB 交叉比对，只统计"Go 中存在且已嵌入"的照片数。
        """
        q: embed_queue.EmbedQueue = req.app.state.embed_queue
        return q.get_embed_stats()

    @app.post("/api/embed/cleanup")
    async def embed_cleanup(req: fastapi.Request):
        """清理 ChromaDB 中孤立文档（Go 中已不存在的照片的 embedding 数据）。"""
        q: embed_queue.EmbedQueue = req.app.state.embed_queue
        removed = q.cleanup_orphans()
        return {"removed": removed}

    @app.post("/api/embed/photos/status")
    async def embed_photos_status(body: dict, req: fastapi.Request):
        """批量查询照片是否已嵌入。body: {"ids": ["id1", "id2", ...]}。"""
        photo_ids = body.get("ids", [])
        cs = req.app.state.chroma_store
        embedded_ids = cs.get_embedded_photo_ids()
        return {pid: (pid in embedded_ids) for pid in photo_ids}

    @app.post("/api/embed/queue/start")
    async def embed_queue_start(body: dict, req: fastapi.Request):
        """启动批量 embedding。body: {"force": false}。"""
        q: embed_queue.EmbedQueue = req.app.state.embed_queue
        force = body.get("force", False)
        return q.start(force=force)

    @app.post("/api/embed/queue/stop")
    async def embed_queue_stop(req: fastapi.Request):
        """中止批量 embedding。"""
        q: embed_queue.EmbedQueue = req.app.state.embed_queue
        return q.stop()

    @app.get("/api/embed/queue/status")
    async def embed_queue_status(req: fastapi.Request):
        """查询 Embed 队列运行状态。"""
        q: embed_queue.EmbedQueue = req.app.state.embed_queue
        return q.status()

    @app.post("/api/embed/photos/{photo_id}")
    async def embed_single_photo(photo_id: str, req: fastapi.Request):
        """嵌入单张照片到 ChromaDB。由前端单张触发调用。"""
        q: embed_queue.EmbedQueue = req.app.state.embed_queue
        return q.enqueue_one(photo_id)

    @app.get("/api/embed/photos/{photo_id}")
    async def embed_photo_info(photo_id: str, req: fastapi.Request):
        """获取单张照片的 embedding 详情（模型、时间、分块信息等）。"""
        store = req.app.state.chroma_store
        info = store.get_photo_embedding_info(photo_id)
        if info is None:
            raise fastapi.HTTPException(status_code=404, detail="该照片暂无 embedding 数据")
        return info

    # ── 黄金用例 API ─────────────────────────────────────

    @app.get("/api/golden-queries", response_model=list[GoldenQueryItem])
    async def list_golden_queries(req: fastapi.Request):
        """列出所有黄金查询用例。"""
        return _load_golden_queries(req.app.state.golden_queries_dir)

    @app.post("/api/golden-queries", response_model=GoldenQueryItem, status_code=201)
    async def create_golden_query(body: GoldenQueryCreateRequest, req: fastapi.Request):
        """创建一条黄金查询用例。"""
        if not body.query_text.strip():
            raise fastapi.HTTPException(status_code=400, detail="查询文本不能为空")
        if not body.relevant_photos:
            raise fastapi.HTTPException(status_code=400, detail="关联照片不能为空")

        gq_dir = req.app.state.golden_queries_dir
        now = datetime.datetime.now().isoformat()
        item = {
            "id": uuid.uuid4().hex[:12],
            "query_text": body.query_text.strip(),
            "relevant_photos": [
                {
                    "photo_id": _normalize_ext(p.photo_id),
                    "filename": _normalize_ext(p.filename),
                    "uuid": _normalize_ext(p.photo_id),  # ChatView 传入的 photo_id 即 UUID
                }
                for p in body.relevant_photos
            ],
            "category": body.category.strip(),
            "notes": body.notes.strip(),
            "created_at": now,
            "updated_at": now,
        }
        items = _load_golden_queries(gq_dir)
        items.append(item)
        _save_golden_queries(items, gq_dir)
        return item

    @app.delete("/api/golden-queries/{golden_id}", response_model=dict)
    async def delete_golden_query(golden_id: str, req: fastapi.Request):
        """删除一条黄金查询用例。"""
        gq_dir = req.app.state.golden_queries_dir
        items = _load_golden_queries(gq_dir)
        before = len(items)
        items = [it for it in items if it["id"] != golden_id]
        if len(items) == before:
            raise fastapi.HTTPException(status_code=404, detail="用例不存在")
        _save_golden_queries(items, gq_dir)
        return {"ok": True}

    @app.post("/api/golden-queries/import", response_model=dict)
    async def import_golden_queries(body: list[GoldenQueryCreateRequest], req: fastapi.Request):
        """批量导入黄金查询用例（追加模式）。

        导入时自动通过 Go 后端将文件名映射到当前环境的 UUID，
        保证导入后即可展示缩略图。导出时不包含 UUID。
        """
        if not body:
            raise fastapi.HTTPException(status_code=400, detail="导入数据不能为空")

        cfg = req.app.state.cfg
        gq_dir = req.app.state.golden_queries_dir
        fname_to_uuid = _build_filename_to_uuid(cfg.go_backend_url)

        items = _load_golden_queries(gq_dir)
        added = 0
        now = datetime.datetime.now().isoformat()
        for it in body:
            if not it.query_text.strip() or not it.relevant_photos:
                continue
            photos = []
            for p in it.relevant_photos:
                pid = _normalize_ext(p.photo_id)
                fname = _normalize_ext(p.filename)
                photos.append({
                    "photo_id": pid,
                    "filename": fname,
                    "uuid": fname_to_uuid.get(pid, ""),
                })
            items.append({
                "id": uuid.uuid4().hex[:12],
                "query_text": it.query_text.strip(),
                "relevant_photos": photos,
                "category": it.category.strip(),
                "notes": it.notes.strip(),
                "created_at": now,
                "updated_at": now,
            })
            added += 1
        _save_golden_queries(items, gq_dir)
        return {"ok": True, "imported": added}

    @app.post("/api/golden-queries/evaluate", response_model=EvalResultResponse)
    async def evaluate_golden_queries(req: fastapi.Request):
        """对当前全部黄金用例运行 RAG 检索评估。"""
        cfg = req.app.state.cfg

        # 从 JSON 加载用例（复用 evaluation 模块的加载逻辑）
        queries = evaluation_mod._load_golden_queries(cfg)
        if not queries:
            raise fastapi.HTTPException(status_code=400, detail="没有黄金用例可评估，请先导入用例")

        try:
            logger.info("开始评估 %d 条黄金用例...", len(queries))
            raw = evaluation_mod.run_evaluation(
                cfg,
                test_queries=queries,
                precision_k=10,
                verbose=True,
            )
        except Exception:
            logger.exception("评估执行失败")
            raise fastapi.HTTPException(status_code=500, detail="评估执行失败，请稍后重试")

        # 扁平化 details，提取前端需要的字段
        flat_details: list[EvalDetailItem] = []
        for d in raw["details"]:
            def _to_items(key: str) -> list[EvalPhotoItem]:
                return [EvalPhotoItem(**p) for p in d.get(key, [])]

            flat_details.append(EvalDetailItem(
                question=d.get("question", ""),
                precision=round(d.get("precision", 0.0), 4),
                recall=round(d.get("recall", 0.0), 4),
                mrr=round(d.get("mrr", 0.0), 4),
                hits=len(d.get("hits", [])),
                retrieved=min(len(d.get("retrieved_ids", [])), d.get("effective_k", 10)),
                relevant=len(d.get("relevant_ids", [])),
                effective_k=d.get("effective_k", 10),
                hit_ids=_to_items("hit_ids"),
                miss_ids=_to_items("miss_ids"),
                remaining_ids=_to_items("remaining_ids"),
            ))

        return {
            "precision_at_k": round(raw["precision@k"], 4),
            "recall_at_k": round(raw["recall@k"], 4),
            "mrr": round(raw["mrr"], 4),
            "total": raw["total"],
            "precision_k": raw["precision_k"],
            "details": flat_details,
        }

    # ── 聚类任务后台状态 ───────────────────────────────────

    # 聚类后台任务追踪: task_id -> {"status": "running"|"done"|"error", "result_id": str, "error": str}
    _cluster_tasks: dict[str, dict] = {}

    # ── 聚类 API ─────────────────────────────────────────

    @app.post("/api/cluster/run")
    async def cluster_run(body: ClusterRunRequest, req: fastapi.Request, background_tasks: fastapi.BackgroundTasks):
        """触发一次聚类计算（后台异步执行，结果存入 JSON 文件）。

        立即返回 task_id，前端可通过 GET /api/cluster/status/{task_id} 查询进度，
        或通过 GET /api/cluster/results 轮询结果列表。
        """
        chroma = req.app.state.chroma_store

        # 检查是否有 embedding 数据
        if chroma.count() == 0:
            raise fastapi.HTTPException(status_code=400, detail="ChromaDB 中无嵌入数据，请先运行 embedding")

        import threading

        task_id = uuid.uuid4().hex[:12]
        _cluster_dir = req.app.state.cluster_dir  # 在线程启动前捕获
        _cluster_tasks[task_id] = {"status": "running", "result_id": "", "error": ""}

        def _run_in_thread():
            try:
                _tracer = tracer_mod.Tracer(cfg.project_root)
                result = cluster_mod.run_clustering(
                    chroma,
                    min_cluster_size=body.min_cluster_size,
                    min_samples=body.min_samples,
                    umap_n_neighbors=body.umap_n_neighbors,
                    umap_min_dist=body.umap_min_dist,
                    umap_n_components=body.umap_n_components,
                    umap_metric=body.umap_metric,
                    tracer=_tracer,
                )
                cluster_mod.save_result(result, _cluster_dir)
                logger.info("聚类结果已保存: %s (trace_id=%s)", result.id, _tracer.trace_id)
                _cluster_tasks[task_id] = {"status": "done", "result_id": result.id, "error": ""}
            except Exception as exc:
                logger.exception("聚类计算失败")
                _cluster_tasks[task_id] = {"status": "error", "result_id": "", "error": "聚类计算失败，请稍后重试"}

        thread = threading.Thread(target=_run_in_thread, daemon=True)
        thread.start()

        return {"task_id": task_id, "status": "started"}

    @app.get("/api/cluster/status/{task_id}")
    async def cluster_task_status(task_id: str):
        """查询聚类后台任务状态。"""
        task = _cluster_tasks.get(task_id)
        if task is None:
            raise fastapi.HTTPException(status_code=404, detail="任务不存在")
        return task

    @app.get("/api/cluster/results", response_model=list[ClusterResultSummary])
    async def cluster_list_results(req: fastapi.Request):
        """列出所有聚类结果（摘要，不含簇内照片详情）。"""
        return cluster_mod.list_results(req.app.state.cluster_dir)

    @app.get("/api/cluster/results/{result_id}", response_model=ClusterResultDetail)
    async def cluster_get_result(result_id: str, req: fastapi.Request):
        """获取一次聚类结果的完整详情。"""
        r = cluster_mod.load_result(result_id, req.app.state.cluster_dir)
        if r is None:
            raise fastapi.HTTPException(status_code=404, detail="聚类结果不存在")
        return cluster_mod._result_to_dict(r)

    @app.delete("/api/cluster/results/{result_id}", response_model=dict)
    async def cluster_delete_result(result_id: str, req: fastapi.Request):
        """删除一次聚类结果。"""
        ok = cluster_mod.delete_result(result_id, req.app.state.cluster_dir)
        if not ok:
            raise fastapi.HTTPException(status_code=404, detail="聚类结果不存在")
        return {"ok": True}

    @app.post("/api/cluster/results/{result_id}/clusters/{cluster_id}/generate-theme", response_model=ClusterResultDetail)
    async def cluster_generate_theme(result_id: str, cluster_id: int, req: fastapi.Request):
        """为指定簇生成主题标签和描述。

        通过 LLM 分析该簇的代表性照片，生成有意义的主题标签
        （如"云南雪山系列"）和一句话描述，结果回写 JSON 文件。
        """
        cluster_dir = req.app.state.cluster_dir
        result = cluster_mod.load_result(result_id, cluster_dir)
        if result is None:
            raise fastapi.HTTPException(status_code=404, detail="聚类结果不存在")

        cfg = req.app.state.cfg
        _tracer = tracer_mod.Tracer(cfg.project_root)
        try:
            updated = cluster_mod.generate_cluster_theme(
                cfg, result, cluster_id, cfg.go_backend_url, cluster_dir,
                tracer=_tracer,
            )
        except ValueError as exc:
            raise fastapi.HTTPException(status_code=404, detail=str(exc))
        except RuntimeError:
            raise fastapi.HTTPException(status_code=500, detail="主题标签生成失败")
        except Exception:
            logger.exception("主题标签生成失败")
            raise fastapi.HTTPException(status_code=500, detail="主题标签生成失败，请稍后重试")

        return cluster_mod._result_to_dict(updated)

    # ── 批量操作请求模型 ───────────────────────────────

    class BatchClusterIdsRequest(pydantic.BaseModel):
        cluster_ids: list[int] | None = None

    @app.post("/api/cluster/results/{result_id}/generate-all-themes", response_model=ClusterResultDetail)
    async def cluster_generate_all_themes(result_id: str, body: BatchClusterIdsRequest, req: fastapi.Request):
        """批量为聚类结果的所有/指定簇生成主题标签和描述。

        Body: { "cluster_ids": [1, 2, 3] | null }
        - cluster_ids 为 null 或不传时，生成所有簇的主题
        - cluster_ids 为数组时，仅生成指定簇的主题
        """
        cluster_dir = req.app.state.cluster_dir
        result = cluster_mod.load_result(result_id, cluster_dir)
        if result is None:
            raise fastapi.HTTPException(status_code=404, detail="聚类结果不存在")

        target_ids = body.cluster_ids
        if target_ids is None:
            target_ids = [c.cluster_id for c in result.clusters]

        cfg = req.app.state.cfg
        _tracer = tracer_mod.Tracer(cfg.project_root)

        for cid in target_ids:
            try:
                result = cluster_mod.generate_cluster_theme(
                    cfg, result, cid, cfg.go_backend_url, cluster_dir,
                    tracer=_tracer,
                )
            except ValueError as exc:
                raise fastapi.HTTPException(status_code=404, detail=str(exc))
            except RuntimeError:
                logger.warning("簇 %d 主题生成失败，继续处理下一个", cid)
            except Exception:
                logger.exception("簇 %d 主题生成异常", cid)

        return cluster_mod._result_to_dict(result)

    # ── 评估 API 模型 ─────────────────────────────────────

    class EvalRuleResult(pydantic.BaseModel):
        rule_id: str
        severity: str
        passed: bool
        value: str = ""
        expected: str = ""
        message: str = ""
        cluster_id: int | None = None

    class EvalHeuristicSummary(pydantic.BaseModel):
        total_checks: int = 0
        passed: int = 0
        failed: int = 0
        failures: list[EvalRuleResult] = []

    class SingleClusterEvalResponse(pydantic.BaseModel):
        cluster_id: int
        checks: list[EvalRuleResult]
        passed: int
        failed: int

    class EvalReportResponse(pydantic.BaseModel):
        report_id: str
        created_at: str
        result_id: str
        total_clusters: int
        heuristic: EvalHeuristicSummary

    class EvalReportSummary(pydantic.BaseModel):
        report_id: str
        created_at: str
        result_id: str
        total_clusters: int
        heuristic_passed: int
        heuristic_failed: int
        has_attribute_check: bool = False

    # ── 选题建议 API ─────────────────────────────────────

    class SuggestHistoryItem(pydantic.BaseModel):
        id: str
        generated_at: str
        pipeline: str = ""
        total_photos: int = 0
        cluster_count: int = 0
        rating: int = 0
        title: str = ""
        angle: str = ""
        rationale: str = ""
        category: str = ""
        photo_ids: list[str] = []
        photo_sequence: list[dict] = []    # [{photo_id, role_in_narrative}]
        trace_id: str = ""
        intuition_source: list[str] = []   # Stage 1 启发照片 ID
        error: str = ""


    class SuggestRatingRequest(pydantic.BaseModel):
        rating: int

    # ── v2 管线步骤模型 ──

    class PipelineStepModel(pydantic.BaseModel):
        event: str
        label: str
        group: str
        stage: int
        timestamp: str = ""
        data: dict = {}
        payload_content: str = ""
        payload_ref: str = ""

    class SuggestVersionModel(pydantic.BaseModel):
        version_id: str
        parent_version_id: str | None = None
        created_at: str
        created_from: str = "auto"  # "auto" | "manual" | "rerun"
        modified_step: str | None = None  # 被修改的步骤 event
        trace_id: str = ""
        trace_expired: bool = False
        steps: list[PipelineStepModel] = []

    class SuggestHistoryDetail(pydantic.BaseModel):
        id: str
        generated_at: str
        pipeline: str = ""
        total_photos: int = 0
        cluster_count: int = 0
        rating: int = 0
        title: str
        angle: str
        rationale: str
        category: str
        photo_ids: list[str]
        photo_sequence: list[dict] = []
        intuition_source: list[str] = []
        error: str = ""
        versions: list[SuggestVersionModel] = []
        current_version_id: str = ""

    class RerunRequest(pydantic.BaseModel):
        from_step: str  # 步骤 event 名
        overrides: dict = {}  # 编辑后的步骤数据

    class ManualSuggestRequest(pydantic.BaseModel):
        photo_ids: list[str] = []  # 为空则自动随机采样
        intuition: dict | None = None  # {"title", "angle", "rationale", "inspired_indices"}


    class SuggestBatchResponse(pydantic.BaseModel):
        items: list[SuggestHistoryItem]
        count: int
        error: str = ""

    @app.post("/api/suggest/run", response_model=SuggestBatchResponse)
    async def suggest_run(req: fastapi.Request):
        """运行潜在主题识别，返回选题建议列表。

        三阶段编辑视角提案（随机采样 → RAG 扩展 → LLM 提案）。

        每个主题作为独立记录持久化到 suggest_history.json。
        """
        cfg = req.app.state.cfg
        cluster_dir = cfg.resolve_path("./data/clusters")

        # 创建 Tracer 用于全链路可观测
        tracer = tracer_mod.Tracer(cfg.project_root)

        suggestions, meta = suggest_mod.run_suggest(
            cfg, cfg.go_backend_url, cluster_dir, tracer=tracer,
        )

        # 从 trace 重建管线步骤（对齐手动选题的行为）
        import chain.trace_replay as trace_replay
        replayed, expired = trace_replay.replay_trace(cfg.project_root, tracer.trace_id)
        steps_snapshots = [
            {
                "event": st.event, "label": st.label, "group": st.group,
                "stage": st.stage, "timestamp": st.timestamp, "data": st.data,
                "payload_content": st.payload_content, "payload_ref": st.payload_ref,
            }
            for st in replayed
        ] if not expired else []

        generated_at = meta.get("generated_at", "")
        pipeline = meta.get("pipeline", "")
        total_photos = meta.get("total_photos", 0)
        cluster_count = meta.get("cluster_count", 0)
        error = meta.get("error", "")

        items: list[dict] = []
        for s in suggestions:
            item = {
                "id": uuid.uuid4().hex[:12],
                "generated_at": generated_at,
                "pipeline": pipeline,
                "total_photos": total_photos,
                "cluster_count": cluster_count,
                "rating": 0,
                "title": s.title,
                "angle": s.angle,
                "rationale": s.rationale,
                "category": s.category,
                "photo_ids": s.photo_ids,
                "photo_sequence": s.photo_sequence,
                "trace_id": s.trace_id or tracer.trace_id,
                "intuition_source": s.intuition_source,
                "error": error,
            }
            items.append(item)

        # 持久化保存（最新的插入列表头部），加锁防止并发写丢失
        v2_items_batch: list[dict] = []
        for it in items:
            v2_items_batch.append({
                "id": it["id"],
                "generated_at": it["generated_at"],
                "pipeline": it.get("pipeline", ""),
                "total_photos": it.get("total_photos", 0),
                "cluster_count": it.get("cluster_count", 0),
                "rating": it.get("rating", 0),
                "title": it.get("title", ""),
                "angle": it.get("angle", ""),
                "rationale": it.get("rationale", ""),
                "category": it.get("category", ""),
                "photo_ids": it.get("photo_ids", []),
                "photo_sequence": it.get("photo_sequence", []),
                "intuition_source": it.get("intuition_source", []),
                "error": it.get("error", ""),
                "versions": [{
                    "version_id": f"{it['id']}-v0",
                    "parent_version_id": None,
                    "created_at": it["generated_at"],
                    "created_from": "auto",
                    "modified_step": None,
                    "trace_id": it.get("trace_id", ""),
                    "trace_expired": expired,
                    "steps": steps_snapshots,
                }],
                "current_version_id": f"{it['id']}-v0",
            })
        with _suggest_history_lock:
            v2_history = _load_suggest_history(req.app.state.suggest_history_dir)
            for v2_item in reversed(v2_items_batch):
                v2_history.insert(0, v2_item)
            _save_suggest_history(v2_history, req.app.state.suggest_history_dir)

        return {"items": items, "count": len(items), "error": error}

    @app.get("/api/suggest/history", response_model=list[SuggestHistoryItem])
    async def suggest_history(req: fastapi.Request):
        """获取选题历史列表（时间倒序，含完整数据）。"""
        return _load_suggest_history(req.app.state.suggest_history_dir)

    @app.get("/api/suggest/history/{item_id}")
    async def suggest_history_detail(item_id: str, req: fastapi.Request):
        """获取单条选题历史详情。"""
        items = _load_suggest_history(req.app.state.suggest_history_dir)
        for it in items:
            if it["id"] == item_id:
                return it
        raise fastapi.HTTPException(status_code=404, detail="选题记录不存在")

    @app.delete("/api/suggest/history/{item_id}", response_model=dict)
    async def suggest_history_delete(item_id: str, req: fastapi.Request):
        """删除单条选题历史。"""
        hist_dir = req.app.state.suggest_history_dir
        with _suggest_history_lock:
            items = _load_suggest_history(hist_dir)
            before = len(items)
            items = [it for it in items if it["id"] != item_id]
            if len(items) == before:
                raise fastapi.HTTPException(status_code=404, detail="选题记录不存在")
            _save_suggest_history(items, hist_dir)
        return {"ok": True}

    @app.patch("/api/suggest/history/{item_id}/rating", response_model=dict)
    async def suggest_history_rating(item_id: str, body: SuggestRatingRequest, req: fastapi.Request):
        """更新选题历史的评分（0-5）。"""
        if not 0 <= body.rating <= 5:
            raise fastapi.HTTPException(status_code=400, detail="评分必须在 0-5 之间")
        hist_dir = req.app.state.suggest_history_dir
        with _suggest_history_lock:
            items = _load_suggest_history(hist_dir)
            for it in items:
                if it["id"] == item_id:
                    it["rating"] = body.rating
                    _save_suggest_history(items, hist_dir)
                    return {"id": item_id, "rating": body.rating}
            raise fastapi.HTTPException(status_code=404, detail="选题记录不存在")

    @app.get("/api/suggest/history/{item_id}/detail", response_model=SuggestHistoryDetail)
    async def suggest_history_detail_v2(item_id: str, req: fastapi.Request):
        """获取选题历史详情（v2 格式，含版本和管线步骤）。

        若记录尚未迁移到 v2，触发懒迁移：从 v1 数据创建 v0 版本并从 trace 重建步骤。
        trace 数据过期时，步骤列表为空且 trace_expired=True。
        若 v2 条目步骤为空但 trace 未过期（例如旧版 suggest/run 未填充），
        自动尝试从 trace 回放填补并写回。
        """
        hist_dir = req.app.state.suggest_history_dir
        cfg = req.app.state.cfg

        # 先查 v2
        v2_item: dict | None = None
        with _suggest_history_lock:
            v2_items = _load_suggest_history(hist_dir)
            for v2 in v2_items:
                if v2["id"] == item_id:
                    v2_item = v2
                    break

        if v2_item is not None:
            # 补偿修复：若步骤为空但 trace 未过期，尝试重新回放
            if _try_refill_steps(v2_item, cfg.project_root):
                with _suggest_history_lock:
                    v2_items2 = _load_suggest_history(hist_dir)
                    for i, v in enumerate(v2_items2):
                        if v["id"] == item_id:
                            v2_items2[i] = v2_item
                            break
                    _save_suggest_history(v2_items2, hist_dir)
            return v2_item

        # 回退到旧 v1 文件并懒迁移（只读，不写回 v1）
        v1_item = None
        v1_fp = _suggest_history_v1_path(hist_dir)
        if v1_fp.exists():
            try:
                v1_items = json.loads(v1_fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                v1_items = []
            for it in v1_items:
                if it["id"] == item_id:
                    v1_item = dict(it)
                    break

        if v1_item is None:
            raise fastapi.HTTPException(status_code=404, detail="选题记录不存在")

        # 懒迁移
        v2_item = _migrate_to_v2(v1_item, cfg.project_root)
        if v2_item is None:
            raise fastapi.HTTPException(status_code=500, detail="迁移失败")

        with _suggest_history_lock:
            v2_items = _load_suggest_history(hist_dir)
            v2_items.insert(0, v2_item)
            _save_suggest_history(v2_items, hist_dir)

        return v2_item

    @app.patch("/api/suggest/history/{item_id}/version/{version_id}/switch", response_model=dict)
    async def suggest_history_version_switch(item_id: str, version_id: str, req: fastapi.Request):
        """切换当前活跃版本。"""
        hist_dir = req.app.state.suggest_history_dir
        with _suggest_history_lock:
            v2_items = _load_suggest_history(hist_dir)
            for v2 in v2_items:
                if v2["id"] == item_id:
                    version_ids = {v["version_id"] for v in v2.get("versions", [])}
                    if version_id not in version_ids:
                        raise fastapi.HTTPException(status_code=404, detail="版本不存在")
                    v2["current_version_id"] = version_id
                    _save_suggest_history(v2_items, hist_dir)
                    return {"id": item_id, "current_version_id": version_id}
            raise fastapi.HTTPException(status_code=404, detail="选题记录不存在")

    @app.post("/api/suggest/random-sample", response_model=dict)
    async def suggest_random_sample(req: fastapi.Request):
        """随机采样照片，返回照片 ID 列表和简要描述。

        用于前端「手动选题」中的「随机选取」按钮。
        """
        cfg = req.app.state.cfg
        try:
            photos = suggest_mod._fetch_all_photos(cfg.go_backend_url)
        except Exception as e:
            raise fastapi.HTTPException(status_code=500, detail=f"获取照片数据失败: {e}")

        if not photos:
            raise fastapi.HTTPException(status_code=400, detail="照片库为空")

        sampled = suggest_mod._random_sample_photos(photos)
        result = []
        for p in sampled:
            pid = getattr(p, "id", "")
            desc = (getattr(p, "description", "") or "").strip()[:120]
            result.append({"photo_id": pid, "description": desc})
        return {"photo_ids": [r["photo_id"] for r in result], "photos": result, "count": len(result)}

    @app.post("/api/suggest/manual-run", response_model=SuggestHistoryDetail)
    async def suggest_manual_run(body: ManualSuggestRequest, req: fastapi.Request):
        """手动选题：用户自选照片 + 可选直觉 → 走管线 → 新建 v2 记录。

        photo_ids 为空时自动随机采样。
        提供 intuition 时跳过 Stage 1 LLM，直接进入 Stage 2+3。
        """
        cfg = req.app.state.cfg
        cluster_dir = cfg.resolve_path("./data/clusters")
        hist_dir = req.app.state.suggest_history_dir

        try:
            all_photos = suggest_mod._fetch_all_photos(cfg.go_backend_url)
        except Exception as e:
            raise fastapi.HTTPException(status_code=500, detail=f"获取照片数据失败: {e}")

        if not all_photos:
            raise fastapi.HTTPException(status_code=400, detail="照片库为空")

        tracer = tracer_mod.Tracer(cfg.project_root)
        generated_at = datetime.datetime.now().isoformat()

        # 确定照片：用户指定 或 随机采样
        if body.photo_ids:
            photo_by_id = {getattr(p, "id", ""): p for p in all_photos}
            selected_photos = [photo_by_id[pid] for pid in body.photo_ids if pid in photo_by_id]
            photo_ids_override = [getattr(p, "id", "") for p in selected_photos]
        else:
            sampled = suggest_mod._random_sample_photos(all_photos)
            photo_ids_override = [getattr(p, "id", "") for p in sampled]

        # 如果有直觉，跳过 Stage 1 LLM；若同时提供照片则也跳过 RAG
        if body.intuition:
            intuitions = suggest_mod._stage1_generate_intuitions(
                cfg, all_photos, tracer=tracer,
                intuitions_override=[body.intuition],
                photo_ids_override=photo_ids_override,
            )
            if not intuitions:
                raise fastapi.HTTPException(status_code=400, detail="未能生成选题直觉，请尝试更换照片或提供直觉")

            # 用户同时提供了直觉和照片：直接用用户照片作为候选池，跳过 RAG
            if body.photo_ids and photo_ids_override:
                expanded_photos = [photo_by_id[pid] for pid in photo_ids_override if pid in photo_by_id]
                proposals = suggest_mod._stage3_generate_proposals(
                    cfg, intuitions, all_photos, tracer=tracer,
                    expanded_photos_override={0: expanded_photos},
                )
            else:
                proposals = suggest_mod._stage3_generate_proposals(
                    cfg, intuitions, all_photos, tracer=tracer,
                )
        else:
            intuitions = suggest_mod._stage1_generate_intuitions(
                cfg, all_photos, tracer=tracer,
                photo_ids_override=photo_ids_override,
            )
            if not intuitions:
                raise fastapi.HTTPException(status_code=400, detail="未能生成选题直觉，请尝试更换照片或提供直觉")
            proposals = suggest_mod._stage3_generate_proposals(
                cfg, intuitions, all_photos, tracer=tracer,
            )

        if not proposals:
            raise fastapi.HTTPException(status_code=400, detail="未能生成选题提案")

        # 取第一个提案作为结果
        s = proposals[0]

        # 从 trace 重建步骤
        import chain.trace_replay as trace_replay
        replayed, expired = trace_replay.replay_trace(cfg.project_root, tracer.trace_id)
        steps_snapshots = [
            {
                "event": st.event, "label": st.label, "group": st.group,
                "stage": st.stage, "timestamp": st.timestamp, "data": st.data,
                "payload_content": st.payload_content, "payload_ref": st.payload_ref,
            }
            for st in replayed
        ] if not expired else []

        v2_id = uuid.uuid4().hex[:12]
        version = {
            "version_id": f"{v2_id}-v0",
            "parent_version_id": None,
            "created_at": generated_at,
            "created_from": "manual",
            "modified_step": None,
            "trace_id": tracer.trace_id,
            "trace_expired": expired,
            "steps": steps_snapshots,
        }

        v2_item = {
            "id": v2_id,
            "generated_at": generated_at,
            "pipeline": "editorial_three_stage",
            "total_photos": len(all_photos),
            "cluster_count": 0,
            "rating": 0,
            "title": s.title,
            "angle": s.angle,
            "rationale": s.rationale,
            "category": s.category,
            "photo_ids": s.photo_ids,
            "photo_sequence": s.photo_sequence,
            "intuition_source": s.intuition_source,
            "error": "",
            "versions": [version],
            "current_version_id": version["version_id"],
        }

        with _suggest_history_lock:
            v2_items = _load_suggest_history(hist_dir)
            v2_items.insert(0, v2_item)
            _save_suggest_history(v2_items, hist_dir)

        return v2_item

    @app.post("/api/suggest/history/{item_id}/rerun", response_model=SuggestHistoryDetail)
    async def suggest_history_rerun(item_id: str, body: RerunRequest, req: fastapi.Request):
        """从指定步骤重跑管线，产生新版本。

        body.from_step: 起始步骤的 event 名（如 "suggest.stage1.sample"）
        body.overrides:  编辑后的步骤数据，由前端根据步骤类型构造
        """
        cfg = req.app.state.cfg
        hist_dir = req.app.state.suggest_history_dir

        # 找到当前 v2 记录
        with _suggest_history_lock:
            v2_items = _load_suggest_history(hist_dir)
            v2_item = None
            for v in v2_items:
                if v["id"] == item_id:
                    v2_item = v
                    break

        if v2_item is None:
            # 尝试从旧 v1 文件懒迁移（只读，不写回 v1）
            v1_item = None
            v1_fp = _suggest_history_v1_path(hist_dir)
            if v1_fp.exists():
                try:
                    v1_items = json.loads(v1_fp.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    v1_items = []
                for it in v1_items:
                    if it["id"] == item_id:
                        v1_item = dict(it)
                        break
            if v1_item is None:
                raise fastapi.HTTPException(status_code=404, detail="选题记录不存在")
            v2_item = _migrate_to_v2(v1_item, cfg.project_root)
            if v2_item is None:
                raise fastapi.HTTPException(status_code=500, detail="迁移失败")

        try:
            all_photos = suggest_mod._fetch_all_photos(cfg.go_backend_url)
        except Exception as e:
            raise fastapi.HTTPException(status_code=500, detail=f"获取照片数据失败: {e}")

        photo_by_id = {getattr(p, "id", ""): p for p in all_photos}

        tracer = tracer_mod.Tracer(cfg.project_root)
        generated_at = datetime.datetime.now().isoformat()

        from_step = body.from_step
        overrides = body.overrides or {}

        # 判断起始步骤的阶段
        stage1_events = {"suggest.stage1.sample", "suggest.stage1.llm.start", "suggest.stage1.llm.end"}
        stage2_events = {"suggest.stage2.rag.start", "suggest.stage2.rag.end", "suggest.stage2.diversity"}
        # stage3 events are the rest

        intuitions: list = []
        proposals: list = []

        if from_step in stage1_events:
            # 从 Stage 1 某步开始，跑完整管线
            photo_ids_ov = overrides.get("photo_ids")
            prompt_ov = overrides.get("prompt")
            intuitions_ov = overrides.get("intuitions")

            if intuitions_ov:
                intuitions = suggest_mod._stage1_generate_intuitions(
                    cfg, all_photos, tracer=tracer,
                    intuitions_override=intuitions_ov,
                )
            else:
                intuitions = suggest_mod._stage1_generate_intuitions(
                    cfg, all_photos, tracer=tracer,
                    photo_ids_override=photo_ids_ov,
                    prompt_override=prompt_ov,
                )

            if intuitions:
                proposals = suggest_mod._stage3_generate_proposals(
                    cfg, intuitions, all_photos, tracer=tracer,
                )

        elif from_step in stage2_events:
            # 从 Stage 2 开始，使用已有的直觉 + 覆盖的 RAG/扩展数据
            photo_ids_for_expand = overrides.get("photo_ids", [])
            expanded = [photo_by_id[pid] for pid in photo_ids_for_expand if pid in photo_by_id]

            # 从当前版本的步骤中恢复直觉
            current_version = None
            for ver in v2_item.get("versions", []):
                if ver["version_id"] == v2_item.get("current_version_id", ""):
                    current_version = ver
                    break

            if current_version:
                for st in current_version.get("steps", []):
                    if st["event"] == "suggest.stage1.intuitions":
                        intuitions_data = st.get("data", {}).get("intuitions", [])
                        intuitions = [
                            suggest_mod.TopicIntuition(
                                title=it.get("title", ""),
                                angle=it.get("angle", ""),
                                rationale=it.get("rationale", ""),
                                inspired_indices=[],
                                inspired_photo_ids=it.get("inspired_photo_ids", []),
                            )
                            for it in intuitions_data
                        ]
                        break

            if not intuitions:
                raise fastapi.HTTPException(status_code=400, detail="无法从当前版本恢复主题直觉，请从 Stage 1 重新运行")

            if expanded:
                proposals = suggest_mod._stage3_generate_proposals(
                    cfg, intuitions, all_photos, tracer=tracer,
                    expanded_photos_override={0: expanded},
                )
            else:
                proposals = suggest_mod._stage3_generate_proposals(
                    cfg, intuitions, all_photos, tracer=tracer,
                )

        else:
            # 从 Stage 3 开始，使用覆盖的提案数据
            proposal_ov = overrides.get("proposal")
            photo_ids_ov = overrides.get("photo_ids", [])

            current_version = None
            for ver in v2_item.get("versions", []):
                if ver["version_id"] == v2_item.get("current_version_id", ""):
                    current_version = ver
                    break

            if current_version:
                for st in current_version.get("steps", []):
                    if st["event"] == "suggest.stage1.intuitions":
                        intuitions_data = st.get("data", {}).get("intuitions", [])
                        intuitions = [
                            suggest_mod.TopicIntuition(
                                title=it.get("title", ""),
                                angle=it.get("angle", ""),
                                rationale=it.get("rationale", ""),
                                inspired_indices=[],
                                inspired_photo_ids=it.get("inspired_photo_ids", []),
                            )
                            for it in intuitions_data
                        ]
                        break

            if not intuitions:
                raise fastapi.HTTPException(status_code=400, detail="无法从当前版本恢复主题直觉，请从 Stage 1 重新运行")

            if proposal_ov:
                proposals = suggest_mod._stage3_generate_proposals(
                    cfg, intuitions, all_photos, tracer=tracer,
                    proposal_overrides={0: proposal_ov},
                )
            else:
                # 用覆盖的照片扩展
                expanded = [photo_by_id[pid] for pid in photo_ids_ov if pid in photo_by_id] if photo_ids_ov else None
                prompt_ov = overrides.get("prompt")
                kwargs = {}
                if expanded:
                    kwargs["expanded_photos_override"] = {0: expanded}
                if prompt_ov:
                    kwargs["prompt_overrides"] = {0: prompt_ov}
                proposals = suggest_mod._stage3_generate_proposals(
                    cfg, intuitions, all_photos, tracer=tracer, **kwargs,
                )

        if not proposals:
            raise fastapi.HTTPException(status_code=400, detail="重跑未能生成有效提案")

        s = proposals[0]

        # 从 trace 重建步骤
        import chain.trace_replay as trace_replay
        replayed, expired = trace_replay.replay_trace(cfg.project_root, tracer.trace_id)
        steps_snapshots = [
            {
                "event": st.event, "label": st.label, "group": st.group,
                "stage": st.stage, "timestamp": st.timestamp, "data": st.data,
                "payload_content": st.payload_content, "payload_ref": st.payload_ref,
            }
            for st in replayed
        ] if not expired else []

        # 生成新版本号
        existing_versions = v2_item.get("versions", [])
        version_num = len(existing_versions)
        new_version_id = f"{item_id}-v{version_num}"
        parent_id = v2_item.get("current_version_id", None)

        new_version = {
            "version_id": new_version_id,
            "parent_version_id": parent_id,
            "created_at": generated_at,
            "created_from": "rerun",
            "modified_step": from_step,
            "trace_id": tracer.trace_id,
            "trace_expired": expired,
            "steps": steps_snapshots,
        }

        # 更新 v2 记录
        v2_item["title"] = s.title
        v2_item["angle"] = s.angle
        v2_item["rationale"] = s.rationale
        v2_item["photo_ids"] = s.photo_ids
        v2_item["photo_sequence"] = s.photo_sequence
        v2_item["intuition_source"] = s.intuition_source
        v2_item["versions"].append(new_version)
        v2_item["current_version_id"] = new_version_id

        with _suggest_history_lock:
            v2_all = _load_suggest_history(hist_dir)
            for i, v in enumerate(v2_all):
                if v["id"] == item_id:
                    v2_all[i] = v2_item
                    break
            else:
                v2_all.insert(0, v2_item)
            _save_suggest_history(v2_all, hist_dir)

        return v2_item

    @app.post("/api/suggest/history/{item_id}/rerun-stream")
    async def suggest_history_rerun_stream(item_id: str, body: RerunRequest, req: fastapi.Request):
        """SSE 版本的 rerun，推送管线阶段进度事件。

        事件格式:
          {"event": "progress", "data": {"stage": 1, "label": "Stage 1 灵感发现", "status": "running"}}
          {"event": "complete", "data": <SuggestHistoryDetail>}
          {"event": "error", "data": {"message": "..."}}
        """
        cfg = req.app.state.cfg
        hist_dir = req.app.state.suggest_history_dir

        # 复制 rerun 所需上下文（在 async 上下文中捕获）
        from_step = body.from_step
        overrides = body.overrides or {}

        def generate():
            progress_q: queue.Queue = queue.Queue()

            def run():
                try:
                    # ── 加载 v2 记录 ──
                    with _suggest_history_lock:
                        v2_items = _load_suggest_history(hist_dir)
                        v2_item_local = None
                        for v in v2_items:
                            if v["id"] == item_id:
                                v2_item_local = v
                                break

                    if v2_item_local is None:
                        v1_item = None
                        v1_fp = _suggest_history_v1_path(hist_dir)
                        if v1_fp.exists():
                            try:
                                v1_items = json.loads(v1_fp.read_text(encoding="utf-8"))
                            except (json.JSONDecodeError, OSError):
                                v1_items = []
                            for it in v1_items:
                                if it["id"] == item_id:
                                    v1_item = dict(it)
                                    break
                        if v1_item is None:
                            progress_q.put({"event": "error", "data": {"message": "选题记录不存在"}})
                            return
                        v2_item_local = _migrate_to_v2(v1_item, cfg.project_root)
                        if v2_item_local is None:
                            progress_q.put({"event": "error", "data": {"message": "迁移失败"}})
                            return

                    all_photos = suggest_mod._fetch_all_photos(cfg.go_backend_url)
                    photo_by_id = {getattr(p, "id", ""): p for p in all_photos}

                    tracer = tracer_mod.Tracer(cfg.project_root)
                    generated_at = datetime.datetime.now().isoformat()

                    stage1_events = {"suggest.stage1.sample", "suggest.stage1.llm.start", "suggest.stage1.llm.end"}
                    stage2_events = {"suggest.stage2.rag.start", "suggest.stage2.rag.end", "suggest.stage2.diversity"}

                    intuitions: list = []
                    proposals: list = []

                    if from_step in stage1_events:
                        progress_q.put({"event": "progress", "data": {"stage": 1, "label": "Stage 1 灵感发现", "status": "running"}})
                        photo_ids_ov = overrides.get("photo_ids")
                        prompt_ov = overrides.get("prompt")
                        intuitions_ov_data = overrides.get("intuitions")

                        if intuitions_ov_data:
                            intuitions = suggest_mod._stage1_generate_intuitions(
                                cfg, all_photos, tracer=tracer,
                                intuitions_override=intuitions_ov_data,
                            )
                        else:
                            intuitions = suggest_mod._stage1_generate_intuitions(
                                cfg, all_photos, tracer=tracer,
                                photo_ids_override=photo_ids_ov,
                                prompt_override=prompt_ov,
                            )
                        progress_q.put({"event": "progress", "data": {"stage": 1, "label": "Stage 1 灵感发现", "status": "done"}})

                        if intuitions:
                            progress_q.put({"event": "progress", "data": {"stage": 2, "label": "Stage 2 扩展选片", "status": "running"}})
                            progress_q.put({"event": "progress", "data": {"stage": 3, "label": "Stage 3 选题提案", "status": "running"}})
                            proposals = suggest_mod._stage3_generate_proposals(
                                cfg, intuitions, all_photos, tracer=tracer,
                            )
                            progress_q.put({"event": "progress", "data": {"stage": 3, "label": "Stage 3 选题提案", "status": "done"}})

                    elif from_step in stage2_events:
                        progress_q.put({"event": "progress", "data": {"stage": 2, "label": "Stage 2 扩展选片", "status": "running"}})

                        # 恢复直觉
                        current_version = None
                        for ver in v2_item_local.get("versions", []):
                            if ver["version_id"] == v2_item_local.get("current_version_id", ""):
                                current_version = ver
                                break
                        if current_version:
                            for st in current_version.get("steps", []):
                                if st["event"] == "suggest.stage1.intuitions":
                                    intuitions_data = st.get("data", {}).get("intuitions", [])
                                    intuitions = [
                                        suggest_mod.TopicIntuition(
                                            title=it.get("title", ""),
                                            angle=it.get("angle", ""),
                                            rationale=it.get("rationale", ""),
                                            inspired_indices=[],
                                            inspired_photo_ids=it.get("inspired_photo_ids", []),
                                        )
                                        for it in intuitions_data
                                    ]
                                    break
                        if not intuitions:
                            progress_q.put({"event": "error", "data": {"message": "无法从当前版本恢复主题直觉，请从 Stage 1 重新运行"}})
                            return

                        photo_ids_for_expand = overrides.get("photo_ids", [])
                        expanded = [photo_by_id[pid] for pid in photo_ids_for_expand if pid in photo_by_id]

                        progress_q.put({"event": "progress", "data": {"stage": 3, "label": "Stage 3 选题提案", "status": "running"}})
                        if expanded:
                            proposals = suggest_mod._stage3_generate_proposals(
                                cfg, intuitions, all_photos, tracer=tracer,
                                expanded_photos_override={0: expanded},
                            )
                        else:
                            proposals = suggest_mod._stage3_generate_proposals(
                                cfg, intuitions, all_photos, tracer=tracer,
                            )
                        progress_q.put({"event": "progress", "data": {"stage": 3, "label": "Stage 3 选题提案", "status": "done"}})

                    else:
                        progress_q.put({"event": "progress", "data": {"stage": 3, "label": "Stage 3 选题提案", "status": "running"}})

                        # 恢复直觉
                        current_version = None
                        for ver in v2_item_local.get("versions", []):
                            if ver["version_id"] == v2_item_local.get("current_version_id", ""):
                                current_version = ver
                                break
                        if current_version:
                            for st in current_version.get("steps", []):
                                if st["event"] == "suggest.stage1.intuitions":
                                    intuitions_data = st.get("data", {}).get("intuitions", [])
                                    intuitions = [
                                        suggest_mod.TopicIntuition(
                                            title=it.get("title", ""),
                                            angle=it.get("angle", ""),
                                            rationale=it.get("rationale", ""),
                                            inspired_indices=[],
                                            inspired_photo_ids=it.get("inspired_photo_ids", []),
                                        )
                                        for it in intuitions_data
                                    ]
                                    break
                        if not intuitions:
                            progress_q.put({"event": "error", "data": {"message": "无法从当前版本恢复主题直觉，请从 Stage 1 重新运行"}})
                            return

                        proposal_ov = overrides.get("proposal")
                        photo_ids_ov_stage3 = overrides.get("photo_ids", [])

                        if proposal_ov:
                            proposals = suggest_mod._stage3_generate_proposals(
                                cfg, intuitions, all_photos, tracer=tracer,
                                proposal_overrides={0: proposal_ov},
                            )
                        else:
                            expanded_stage3 = [photo_by_id[pid] for pid in photo_ids_ov_stage3 if pid in photo_by_id] if photo_ids_ov_stage3 else None
                            prompt_ov_stage3 = overrides.get("prompt")
                            kwargs = {}
                            if expanded_stage3:
                                kwargs["expanded_photos_override"] = {0: expanded_stage3}
                            if prompt_ov_stage3:
                                kwargs["prompt_overrides"] = {0: prompt_ov_stage3}
                            proposals = suggest_mod._stage3_generate_proposals(
                                cfg, intuitions, all_photos, tracer=tracer, **kwargs,
                            )
                        progress_q.put({"event": "progress", "data": {"stage": 3, "label": "Stage 3 选题提案", "status": "done"}})

                    if not proposals:
                        progress_q.put({"event": "error", "data": {"message": "重跑未能生成有效提案"}})
                        return

                    s_result = proposals[0]

                    # 从 trace 重建步骤
                    import chain.trace_replay as trace_replay
                    replayed, expired = trace_replay.replay_trace(cfg.project_root, tracer.trace_id)
                    steps_snapshots = [
                        {
                            "event": st.event, "label": st.label, "group": st.group,
                            "stage": st.stage, "timestamp": st.timestamp, "data": st.data,
                            "payload_content": st.payload_content, "payload_ref": st.payload_ref,
                        }
                        for st in replayed
                    ] if not expired else []

                    # 生成新版本号
                    existing_versions = v2_item_local.get("versions", [])
                    version_num = len(existing_versions)
                    new_version_id = f"{item_id}-v{version_num}"
                    parent_id = v2_item_local.get("current_version_id", None)

                    new_version = {
                        "version_id": new_version_id,
                        "parent_version_id": parent_id,
                        "created_at": generated_at,
                        "created_from": "rerun",
                        "modified_step": from_step,
                        "trace_id": tracer.trace_id,
                        "trace_expired": expired,
                        "steps": steps_snapshots,
                    }

                    # 更新 v2 记录
                    v2_item_local["title"] = s_result.title
                    v2_item_local["angle"] = s_result.angle
                    v2_item_local["rationale"] = s_result.rationale
                    v2_item_local["photo_ids"] = s_result.photo_ids
                    v2_item_local["photo_sequence"] = s_result.photo_sequence
                    v2_item_local["intuition_source"] = s_result.intuition_source
                    v2_item_local["versions"].append(new_version)
                    v2_item_local["current_version_id"] = new_version_id

                    with _suggest_history_lock:
                        v2_all = _load_suggest_history(hist_dir)
                        for i, v in enumerate(v2_all):
                            if v["id"] == item_id:
                                v2_all[i] = v2_item_local
                                break
                        else:
                            v2_all.insert(0, v2_item_local)
                        _save_suggest_history(v2_all, hist_dir)

                    progress_q.put({"event": "complete", "data": v2_item_local})

                except Exception as e:
                    logger.exception("SSE rerun 失败")
                    progress_q.put({"event": "error", "data": {"message": f"重跑失败: {e}"}})

            thread = threading.Thread(target=run, daemon=True)
            thread.start()

            while True:
                try:
                    event = progress_q.get(timeout=120)
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                    if event["event"] in ("complete", "error"):
                        break
                except queue.Empty:
                    yield f"data: {json.dumps({'event': 'error', 'data': {'message': '重跑超时'}})}\n\n"
                    break

        return fastapi.responses.StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── 评估 API ─────────────────────────────────────────

    @app.post("/api/cluster/results/{result_id}/evaluate-themes", response_model=EvalReportResponse)
    async def eval_cluster_themes(result_id: str, body: BatchClusterIdsRequest, req: fastapi.Request):
        """对聚类结果的所有/指定簇标题执行启发式规则评估。

        加载 eval_rules.yaml 中的 cluster_theme 规则，
        检查标题长度、兜底文本、markdown 残留、描述长度、簇间多样性。

        Body: { "cluster_ids": [1, 2, 3] | null }
        - cluster_ids 为 null 或不传时，评估所有簇（含跨簇规则）
        - cluster_ids 为数组时，仅评估指定簇，且跳过跨簇规则
        """
        cluster_dir = req.app.state.cluster_dir
        result = cluster_mod.load_result(result_id, cluster_dir)
        if result is None:
            raise fastapi.HTTPException(status_code=404, detail="聚类结果不存在")

        cfg = req.app.state.cfg
        rules_path = cfg.resolve_path("./data/eval_rules.yaml")
        if not rules_path.exists():
            raise fastapi.HTTPException(status_code=500, detail="规则配置文件不存在")

        all_rules = eval_engine.load_rules(rules_path)
        theme_rules = all_rules.get("cluster_theme", [])
        if not theme_rules:
            raise fastapi.HTTPException(status_code=500, detail="未找到 cluster_theme 规则")

        target_ids = body.cluster_ids

        try:
            if target_ids is not None:
                # 部分簇评估：过滤 clusters + 跳过跨簇规则
                filtered_clusters = [c for c in result.clusters if c.cluster_id in target_ids]
                result_with_filtered = cluster_mod.ClusterResult(
                    id=result.id,
                    created_at=result.created_at,
                    params=result.params,
                    stats=result.stats,
                    clusters=filtered_clusters,
                )
                non_cross_rules = [r for r in theme_rules if r.get("scope") != "all_clusters"]
                report = eval_engine.evaluate_cluster_themes(result_with_filtered, non_cross_rules)
            else:
                report = eval_engine.evaluate_cluster_themes(result, theme_rules)
            eval_engine.save_report(report, cfg.project_root)
        except Exception:
            logger.exception("评估执行失败")
            raise fastapi.HTTPException(status_code=500, detail="评估执行失败")

        return {
            "report_id": report["report_id"],
            "created_at": report["created_at"],
            "result_id": report["result_id"],
            "total_clusters": report["total_clusters"],
            "heuristic": {
                "total_checks": report["heuristic"]["total_checks"],
                "passed": report["heuristic"]["passed"],
                "failed": report["heuristic"]["failed"],
                "failures": [
                    {
                        "rule_id": f["rule_id"],
                        "severity": f["severity"],
                        "passed": f["passed"],
                        "value": f.get("value", ""),
                        "expected": f.get("expected", ""),
                        "message": f.get("message", ""),
                        "cluster_id": f.get("cluster_id"),
                    }
                    for f in report["heuristic"]["failures"]
                ],
            },
        }

    @app.post("/api/cluster/results/{result_id}/clusters/{cluster_id}/evaluate-theme",
              response_model=SingleClusterEvalResponse)
    async def eval_single_cluster_theme(result_id: str, cluster_id: int, req: fastapi.Request):
        """对单个簇的标题和主题描述执行单簇启发式规则。

        不执行跨簇规则（diverse_labels）。
        返回该簇的评估结果。
        """
        cluster_dir = req.app.state.cluster_dir
        result = cluster_mod.load_result(result_id, cluster_dir)
        if result is None:
            raise fastapi.HTTPException(status_code=404, detail="聚类结果不存在")

        target = None
        for c in result.clusters:
            if c.cluster_id == cluster_id:
                target = c
                break
        if target is None:
            raise fastapi.HTTPException(status_code=404, detail=f"簇 {cluster_id} 不存在")

        cfg = req.app.state.cfg
        rules_path = cfg.resolve_path("./data/eval_rules.yaml")
        if not rules_path.exists():
            raise fastapi.HTTPException(status_code=500, detail="规则配置文件不存在")

        all_rules = eval_engine.load_rules(rules_path)
        theme_rules = all_rules.get("cluster_theme", [])
        # 排除跨簇规则
        non_cross_rules = [r for r in theme_rules if r.get("scope") != "all_clusters"]
        if not non_cross_rules:
            raise fastapi.HTTPException(status_code=500, detail="未找到可用规则")

        try:
            results = eval_engine.run_theme_rules(
                [{"cluster_id": cluster_id, "label": target.label,
                  "theme_description": target.theme_description, "size": target.size}],
                non_cross_rules,
            )
        except Exception:
            logger.exception("单簇评估执行失败")
            raise fastapi.HTTPException(status_code=500, detail="评估执行失败")

        passed = sum(1 for r in results if r["passed"])
        failed = sum(1 for r in results if not r["passed"])

        return {
            "cluster_id": cluster_id,
            "checks": [
                {
                    "rule_id": r["rule_id"],
                    "severity": r["severity"],
                    "passed": r["passed"],
                    "value": r.get("value", ""),
                    "expected": r.get("expected", ""),
                    "message": r.get("message", ""),
                    "cluster_id": r.get("cluster_id"),
                }
                for r in results
            ],
            "passed": passed,
            "failed": failed,
        }

    @app.get("/api/eval/reports", response_model=list[EvalReportSummary])
    async def eval_list_reports(req: fastapi.Request):
        """列出所有评估报告摘要。"""
        cfg = req.app.state.cfg
        return eval_engine.list_reports(cfg.project_root)

    @app.get("/api/eval/reports/{report_id}", response_model=EvalReportResponse)
    async def eval_get_report(report_id: str, req: fastapi.Request):
        """获取单份评估报告详情。"""
        cfg = req.app.state.cfg
        report = eval_engine.load_report(report_id, cfg.project_root)
        if report is None:
            raise fastapi.HTTPException(status_code=404, detail="评估报告不存在")
        return {
            "report_id": report["report_id"],
            "created_at": report["created_at"],
            "result_id": report["result_id"],
            "total_clusters": report["total_clusters"],
            "heuristic": {
                "total_checks": report["heuristic"]["total_checks"],
                "passed": report["heuristic"]["passed"],
                "failed": report["heuristic"]["failed"],
                "failures": [
                    {
                        "rule_id": f["rule_id"],
                        "severity": f["severity"],
                        "passed": f["passed"],
                        "value": f.get("value", ""),
                        "expected": f.get("expected", ""),
                        "message": f.get("message", ""),
                        "cluster_id": f.get("cluster_id"),
                    }
                    for f in report["heuristic"]["failures"]
                ],
            },
        }

    return app


# ── 辅助函数 ──────────────────────────────────────────────

def _resolve_db_path(cfg: config_mod.Config) -> str:
    """解析会话数据库路径，优先配置，兜底 data/chat_sessions.db。"""
    db_rel = getattr(cfg, "chat_db_path", "") or "./data/chat_sessions.db"
    return cfg.resolve_path(db_rel).as_posix()


def run_server(cfg: config_mod.Config, port: int = 10005) -> None:
    """启动 uvicorn 服务器（阻塞调用）。"""
    import uvicorn

    # 为 chain.* 应用层 logger 配置 handler（uvicorn 不管这些）
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    _handler.setLevel(logging.DEBUG)
    logging.getLogger("chain").addHandler(_handler)
    logging.getLogger("chain").setLevel(logging.INFO)

    app = create_app(cfg)
    logger.info("Chat API 服务启动: http://0.0.0.0:%d", port)
    logger.info("API 文档: http://localhost:%d/docs", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

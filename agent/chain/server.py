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

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import fastapi
import fastapi.middleware.cors
import pydantic

import chain.photo_agent as photo_agent
import chain.session_store as session_store
import chain.embed_queue as embed_queue
import chain.evaluation as evaluation_mod
import vectorstore.chroma_client as chroma_client
import config as config_mod

logger = logging.getLogger(__name__)

# ── 黄金用例 JSON 存储 ─────────────────────────────────────

_GOLDEN_QUERIES_DIR: pathlib.Path | None = None


def _normalize_ext(filename: str) -> str:
    """去除文件扩展名，兼容大小写和 jpg/jpeg 变化。"""
    if not filename:
        return ""
    return os.path.splitext(filename)[0]


def _build_filename_to_uuid(go_backend_url: str) -> dict[str, str]:
    """从 Go 后端获取全部照片，构建 文件名(去后缀) → UUID 映射。"""
    import httpx
    mapping: dict[str, str] = {}
    client = httpx.Client(timeout=30.0)
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



def _golden_queries_path() -> pathlib.Path:
    """返回 golden_queries.json 的路径（首次调用时根据 cfg 解析）。"""
    global _GOLDEN_QUERIES_DIR
    if _GOLDEN_QUERIES_DIR is None:
        raise RuntimeError("golden_queries 存储路径未初始化，请先调用 create_app()")
    return _GOLDEN_QUERIES_DIR / "golden_queries.json"


def _load_golden_queries() -> list[dict]:
    """加载所有黄金用例。文件不存在时返回空列表。

    兼容旧格式 relevant_photo_ids (list[str])，自动迁移为
    新格式 relevant_photos (list[{photo_id, filename}]).
    """
    fp = _golden_queries_path()
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
        _save_golden_queries(items)
    return items


def _save_golden_queries(items: list[dict]) -> None:
    """保存黄金用例列表到 JSON 文件。"""
    fp = _golden_queries_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(
        json.dumps(items, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


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


# ── 应用工厂 ──────────────────────────────────────────────

def create_app(cfg: config_mod.Config) -> fastapi.FastAPI:
    """创建 FastAPI 应用，绑定配置和 Agent 实例。"""

    app = fastapi.FastAPI(
        title="Photo Agent Chat API",
        version="0.1.0",
        description="照片 AI 助手对话接口",
    )

    # CORS — 开发阶段允许所有来源
    app.add_middleware(
        fastapi.middleware.cors.CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
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

    # 初始化黄金用例存储路径
    global _GOLDEN_QUERIES_DIR
    _GOLDEN_QUERIES_DIR = cfg.resolve_path("./data")

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
            # 保存错误消息
            s.add_message(session_id, "assistant", f"抱歉，处理请求时出错: {exc}", query_type="error")
            raise fastapi.HTTPException(status_code=500, detail=str(exc))

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
    async def list_golden_queries():
        """列出所有黄金查询用例。"""
        return _load_golden_queries()

    @app.post("/api/golden-queries", response_model=GoldenQueryItem, status_code=201)
    async def create_golden_query(body: GoldenQueryCreateRequest):
        """创建一条黄金查询用例。"""
        if not body.query_text.strip():
            raise fastapi.HTTPException(status_code=400, detail="查询文本不能为空")
        if not body.relevant_photos:
            raise fastapi.HTTPException(status_code=400, detail="关联照片不能为空")

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
        items = _load_golden_queries()
        items.append(item)
        _save_golden_queries(items)
        return item

    @app.delete("/api/golden-queries/{golden_id}", response_model=dict)
    async def delete_golden_query(golden_id: str):
        """删除一条黄金查询用例。"""
        items = _load_golden_queries()
        before = len(items)
        items = [it for it in items if it["id"] != golden_id]
        if len(items) == before:
            raise fastapi.HTTPException(status_code=404, detail="用例不存在")
        _save_golden_queries(items)
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
        fname_to_uuid = _build_filename_to_uuid(cfg.go_backend_url)

        items = _load_golden_queries()
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
        _save_golden_queries(items)
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
        except Exception as exc:
            logger.exception("评估执行失败")
            raise fastapi.HTTPException(status_code=500, detail=f"评估失败: {exc}")

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

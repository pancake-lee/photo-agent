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


import fastapi
import fastapi.middleware.cors
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

    class SuggestResponse(pydantic.BaseModel):
        generated_at: str
        total_photos: int
        cluster_count: int
        candidates_found: int
        suggestions: list[dict] = []
        error: str = ""
        pipeline: str = ""

    @app.post("/api/suggest/run", response_model=SuggestResponse)
    async def suggest_run(req: fastapi.Request):
        """运行潜在主题识别，返回选题建议列表。

        主路径：三阶段编辑视角提案（随机采样 → RAG 扩展 → LLM 提案）
        回退路径：三维度属性分析（高频未成组 / 时间线规律 / 稀缺优质）
        """
        cfg = req.app.state.cfg
        cluster_dir = cfg.resolve_path("./data/clusters")

        suggestions, meta = suggest_mod.run_suggest(
            cfg, cfg.go_backend_url, cluster_dir,
        )

        result = {
            "generated_at": meta.get("generated_at", ""),
            "total_photos": meta.get("total_photos", 0),
            "cluster_count": meta.get("cluster_count", 0),
            "candidates_found": meta.get("candidates_found", 0),
            "suggestions": [
                {
                    "title": s.title,
                    "angle": s.angle,
                    "rationale": s.rationale,
                    "category": s.category,
                    "photo_ids": s.photo_ids,
                }
                for s in suggestions
            ],
            "error": meta.get("error", ""),
            "pipeline": meta.get("pipeline", ""),
        }
        return result

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

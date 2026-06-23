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

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import fastapi
import fastapi.middleware.cors
import pydantic

import chain.photo_agent as photo_agent
import chain.session_store as session_store
import chain.embed_queue as embed_queue
import vectorstore.chroma_client as chroma_client
import config as config_mod

logger = logging.getLogger(__name__)


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


class MessageResponse(pydantic.BaseModel):
    message_id: int
    answer: str
    query_type: str


class HealthResponse(pydantic.BaseModel):
    status: str
    model: str


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

        # 保存 AI 回复
        msg_id = s.add_message(session_id, "assistant", answer, query_type=query_type)

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

    return app


# ── 辅助函数 ──────────────────────────────────────────────

def _resolve_db_path(cfg: config_mod.Config) -> str:
    """解析会话数据库路径，优先配置，兜底 data/chat_sessions.db。"""
    db_rel = getattr(cfg, "chat_db_path", "") or "./data/chat_sessions.db"
    return cfg.resolve_path(db_rel).as_posix()


def run_server(cfg: config_mod.Config, port: int = 10005) -> None:
    """启动 uvicorn 服务器（阻塞调用）。"""
    import uvicorn
    app = create_app(cfg)
    logger.info("Chat API 服务启动: http://0.0.0.0:%d", port)
    logger.info("API 文档: http://localhost:%d/docs", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

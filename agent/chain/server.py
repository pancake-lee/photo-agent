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

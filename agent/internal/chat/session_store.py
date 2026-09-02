"""
    会话存储层 — SQLite 持久化对话会话和消息。

    提供 SessionStore 类，管理 sessions 和 messages 两张表。
    Python Agent CLI 和 API 服务共享同一个数据库文件。
"""

import sqlite3
import uuid
import pathlib
import threading
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_initial_title() -> str:
    """生成初始会话标题：YYMMDD-hh:mm:ss。"""
    return datetime.now().strftime("%y%m%d-%H:%M:%S")


def _format_question_title(question: str) -> str:
    """从提问生成标题：取前 8 个字符 + ...。"""
    text = question.strip()
    if len(text) <= 8:
        return text
    return text[:8] + "..."


class SessionStore:
    """会话和消息的 SQLite 持久化存储。"""

    def __init__(self, db_path: str):
        """
        初始化存储。

        参数:
            db_path: SQLite 数据库文件路径。父目录不存在时自动创建。
        """
        self._db_path = str(pathlib.Path(db_path).resolve())
        pathlib.Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_tables()

    # ── 内部方法 ──────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（线程安全）。"""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_tables(self) -> None:
        """创建表和索引（幂等），并执行列迁移。"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id          TEXT PRIMARY KEY,
                        title       TEXT NOT NULL,
                        last_granularity TEXT NOT NULL DEFAULT 'photo',
                        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id  TEXT NOT NULL,
                        role        TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                        content     TEXT NOT NULL,
                        query_type  TEXT,
                        trace_id    TEXT,
                        runtime_steps TEXT DEFAULT '',
                        granularity TEXT,
                        usage_json  TEXT DEFAULT '{}',
                        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                    );

                    CREATE INDEX IF NOT EXISTS idx_messages_session
                        ON messages(session_id, id);

                    CREATE TABLE IF NOT EXISTS runtime_pending_clarifications (
                        session_id TEXT PRIMARY KEY,
                        original_goal TEXT NOT NULL,
                        clarification_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    );
                """)

                # 迁移：添加 photos 列（若不存在）
                cols = conn.execute("PRAGMA table_info(messages)").fetchall()
                col_names = {row[1] for row in cols}
                if "photos" not in col_names:
                    conn.execute(
                        "ALTER TABLE messages ADD COLUMN photos TEXT DEFAULT ''"
                    )
                if "granularity" not in col_names:
                    conn.execute(
                        "ALTER TABLE messages ADD COLUMN granularity TEXT"
                    )
                if "trace_id" not in col_names:
                    conn.execute(
                        "ALTER TABLE messages ADD COLUMN trace_id TEXT"
                    )
                if "runtime_steps" not in col_names:
                    conn.execute(
                        "ALTER TABLE messages ADD COLUMN runtime_steps TEXT DEFAULT ''"
                    )

                session_cols = conn.execute("PRAGMA table_info(sessions)").fetchall()
                session_col_names = {row[1] for row in session_cols}
                if "last_granularity" not in session_col_names:
                    conn.execute(
                        "ALTER TABLE sessions ADD COLUMN last_granularity TEXT NOT NULL DEFAULT 'photo'"
                    )

                conn.commit()
            finally:
                conn.close()

    # ── 会话 CRUD ─────────────────────────────────────────────

    def create_session(self, title: Optional[str] = None) -> dict:
        """创建新会话，返回 { session_id, title, created_at, updated_at }。"""
        session_id = uuid.uuid4().hex[:12]
        if title is None:
            title = _format_initial_title()
        now = _now_iso()

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO sessions (id, title, last_granularity, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, title, "photo", now, now),
                )
                conn.commit()
            finally:
                conn.close()

        return {
            "session_id": session_id,
            "title": title,
            "last_granularity": "photo",
            "created_at": now,
            "updated_at": now,
        }

    def list_sessions(self) -> list[dict]:
        """列出所有会话，按 updated_at 降序。"""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    """SELECT s.id, s.title, s.last_granularity, s.created_at, s.updated_at,
                              COUNT(m.id) AS message_count
                       FROM sessions s
                       LEFT JOIN messages m ON m.session_id = s.id
                       GROUP BY s.id
                       ORDER BY s.updated_at DESC"""
                ).fetchall()
                return [
                    {
                        "session_id": row["id"],
                        "title": row["title"],
                        "last_granularity": row["last_granularity"],
                        "message_count": row["message_count"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
                    for row in rows
                ]
            finally:
                conn.close()

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话详情（含消息列表），不存在返回 None。"""
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT id, title, last_granularity, created_at, updated_at FROM sessions WHERE id=?",
                    (session_id,),
                ).fetchone()
                if row is None:
                    return None

                msg_rows = conn.execute(
                    """SELECT id, session_id, role, content, query_type, trace_id, granularity, usage_json, photos, runtime_steps, created_at
                       FROM messages WHERE session_id=? ORDER BY id""",
                    (session_id,),
                ).fetchall()

                messages = []
                for m in msg_rows:
                    import json
                    usage = json.loads(m["usage_json"] or "{}")
                    photos_list = []
                    runtime_steps = []
                    if m["photos"]:
                        try:
                            photos_list = json.loads(m["photos"])
                        except json.JSONDecodeError:
                            photos_list = []
                    if m["runtime_steps"]:
                        try:
                            runtime_steps = json.loads(m["runtime_steps"])
                        except json.JSONDecodeError:
                            runtime_steps = []
                    messages.append({
                        "id": m["id"],
                        "session_id": m["session_id"],
                        "role": m["role"],
                        "content": m["content"],
                        "query_type": m["query_type"],
                        "trace_id": m["trace_id"],
                        "granularity": m["granularity"],
                        "photos": photos_list,
                        "runtime_steps": runtime_steps,
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cost": usage.get("cost", 0.0),
                        "created_at": m["created_at"],
                    })

                return {
                    "session_id": row["id"],
                    "title": row["title"],
                    "last_granularity": row["last_granularity"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "messages": messages,
                }
            finally:
                conn.close()

    def update_title(self, session_id: str, title: str) -> bool:
        """更新会话标题，返回是否成功。"""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute(
                    "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
                    (title, _now_iso(), session_id),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def update_last_granularity(self, session_id: str, granularity: str) -> bool:
        """更新会话下次提问默认使用的检索粒度。"""
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute(
                    "UPDATE sessions SET last_granularity=?, updated_at=? WHERE id=?",
                    (granularity, _now_iso(), session_id),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def delete_session(self, session_id: str) -> bool:
        """删除会话及其所有消息（级联），返回是否成功。"""
        with self._lock:
            conn = self._get_conn()
            try:
                # 先删消息再删会话（虽然设置了 ON DELETE CASCADE，但显式操作更安全）
                conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
                conn.execute("DELETE FROM runtime_pending_clarifications WHERE session_id=?", (session_id,))
                cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def save_runtime_clarification(self, session_id: str, original_goal: str, clarification: dict) -> None:
        """保存 Runtime 等待澄清的原始目标，下一条短回复据此续跑。"""
        import json
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO runtime_pending_clarifications
                       (session_id, original_goal, clarification_json, created_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(session_id) DO UPDATE SET
                       original_goal=excluded.original_goal,
                       clarification_json=excluded.clarification_json,
                       created_at=excluded.created_at""",
                    (session_id, original_goal, json.dumps(clarification, ensure_ascii=False), _now_iso()),
                )
                conn.commit()
            finally:
                conn.close()

    def get_runtime_clarification(self, session_id: str) -> dict | None:
        """读取会话等待中的 Runtime 澄清状态。"""
        import json
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT original_goal, clarification_json FROM runtime_pending_clarifications WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                if row is None:
                    return None
                return {"original_goal": row["original_goal"], "clarification": json.loads(row["clarification_json"] or "{}")}
            finally:
                conn.close()

    def clear_runtime_clarification(self, session_id: str) -> None:
        """清除已完成或确定性失败的 Runtime 澄清状态。"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM runtime_pending_clarifications WHERE session_id=?", (session_id,))
                conn.commit()
            finally:
                conn.close()

    # ── 消息操作 ──────────────────────────────────────────────

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        query_type: Optional[str] = None,
        trace_id: Optional[str] = None,
        granularity: Optional[str] = None,
        usage: Optional[dict] = None,
        photos_json: str = "",
        runtime_steps: list[dict] | None = None,
    ) -> int:
        """添加一条消息，返回消息 ID。同时更新会话的 updated_at。"""
        import json
        now = _now_iso()
        usage_str = json.dumps(usage or {}, ensure_ascii=False)
        runtime_steps_json = json.dumps(runtime_steps or [], ensure_ascii=False)

        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.execute(
                    """INSERT INTO messages (session_id, role, content, query_type, trace_id, granularity, usage_json, photos, runtime_steps, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (session_id, role, content, query_type, trace_id, granularity, usage_str, photos_json, runtime_steps_json, now),
                )
                conn.execute(
                    "UPDATE sessions SET updated_at=? WHERE id=?",
                    (now, session_id),
                )
                conn.commit()
                return cur.lastrowid
            finally:
                conn.close()

    def get_messages(self, session_id: str) -> list[dict]:
        """获取会话的所有消息，按 id 升序。"""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    """SELECT id, session_id, role, content, query_type, trace_id, granularity, usage_json, photos, runtime_steps, created_at
                       FROM messages WHERE session_id=? ORDER BY id""",
                    (session_id,),
                ).fetchall()
                import json
                result = []
                for m in rows:
                    usage = json.loads(m["usage_json"] or "{}")
                    photos_list = []
                    runtime_steps = []
                    if m["photos"]:
                        try:
                            photos_list = json.loads(m["photos"])
                        except json.JSONDecodeError:
                            photos_list = []
                    if m["runtime_steps"]:
                        try:
                            runtime_steps = json.loads(m["runtime_steps"])
                        except json.JSONDecodeError:
                            runtime_steps = []
                    result.append({
                        "id": m["id"],
                        "session_id": m["session_id"],
                        "role": m["role"],
                        "content": m["content"],
                        "query_type": m["query_type"],
                        "trace_id": m["trace_id"],
                        "granularity": m["granularity"],
                        "photos": photos_list,
                        "runtime_steps": runtime_steps,
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cost": usage.get("cost", 0.0),
                        "created_at": m["created_at"],
                    })
                return result
            finally:
                conn.close()

    def message_count(self, session_id: str) -> int:
        """返回会话的消息数。"""
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM messages WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                return row["cnt"] if row else 0
            finally:
                conn.close()

    def is_first_message(self, session_id: str) -> bool:
        """判断是否为会话的首条用户消息（即尚无 user 消息）。"""
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM messages WHERE session_id=? AND role='user'",
                    (session_id,),
                ).fetchone()
                return (row["cnt"] if row else 0) == 0
            finally:
                conn.close()

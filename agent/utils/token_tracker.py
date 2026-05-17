"""
    Token 成本追踪：SQLite 本地存储 + LangChain 自动回调。

    用法:
        from utils.token_tracker import TokenTracker, TokenCallback, load_prices

        tracker = TokenTracker("data/tokens.db", prices)
        callback = TokenCallback(tracker)
        llm = ChatOpenAI(callbacks=[callback])
"""

import pathlib
import sqlite3

import langchain_core.callbacks as lc_callbacks
import yaml


def load_prices(prices_path: str) -> dict[str, dict[str, float]]:
    """从 YAML 加载模型单价（input/output 均为每 1K token 价格）。"""
    if not prices_path:
        return {}
    p = pathlib.Path(prices_path)
    if not p.exists():
        print(f"warning: Token 单价文件不存在: {prices_path}")
        return {}
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("models", {})


class TokenTracker:
    """SQLite 本地 Token 用量与成本追踪。"""

    def __init__(self, db_path: str, prices: dict[str, dict[str, float]] | None = None):
        self._db_path = db_path
        self._prices = prices or {}
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    model     TEXT    NOT NULL,
                    input_tokens  INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cost      REAL    NOT NULL,
                    created_at TEXT    DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.commit()

    def record(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """记录一次调用，返回成本。"""
        price = self._prices.get(model, {})
        input_price = price.get("input", 0.0)
        output_price = price.get("output", 0.0)
        cost = (input_tokens / 1000.0) * input_price + (output_tokens / 1000.0) * output_price

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO token_usage (model, input_tokens, output_tokens, cost) "
                "VALUES (?, ?, ?, ?)",
                (model, input_tokens, output_tokens, cost),
            )
            conn.commit()
        return cost

    def summary(self, days: int = 7) -> list[dict]:
        """按模型聚合最近 N 天用量。"""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT model,
                       SUM(input_tokens)  AS total_input,
                       SUM(output_tokens) AS total_output,
                       SUM(cost)          AS total_cost,
                       COUNT(*)           AS calls
                FROM token_usage
                WHERE created_at >= datetime('now', 'localtime', ? || ' days')
                GROUP BY model
                ORDER BY total_cost DESC
                """,
                (f"-{days}",),
            ).fetchall()
        return [dict(r) for r in rows]

    def daily_breakdown(self, days: int = 7) -> list[dict]:
        """按天 + 模型聚合用量。"""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT date(created_at) AS day,
                       model,
                       SUM(input_tokens)  AS total_input,
                       SUM(output_tokens) AS total_output,
                       SUM(cost)          AS total_cost,
                       COUNT(*)           AS calls
                FROM token_usage
                WHERE created_at >= datetime('now', 'localtime', ? || ' days')
                GROUP BY day, model
                ORDER BY day DESC, total_cost DESC
                """,
                (f"-{days}",),
            ).fetchall()
        return [dict(r) for r in rows]


class TokenCallback(lc_callbacks.BaseCallbackHandler):
    """LangChain callback：自动将每次 LLM 调用的 token 用量写入 TokenTracker。"""

    def __init__(self, tracker: TokenTracker):
        super().__init__()
        self._tracker = tracker

    def on_llm_end(self, response, **kwargs) -> None:
        llm_output = getattr(response, "llm_output", None) or {}
        token_usage = llm_output.get("token_usage", {})
        input_tokens = token_usage.get("prompt_tokens", 0)
        output_tokens = token_usage.get("completion_tokens", 0)
        if input_tokens or output_tokens:
            model = (llm_output.get("model_name", "") or
                     getattr(response, "model_name", "") or "unknown")
            if isinstance(model, str) and model:
                self._tracker.record(model, input_tokens, output_tokens)

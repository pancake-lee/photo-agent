"""
    Token 成本追踪：SQLite 本地存储 + LangChain 自动回调。

    用法:
        import infra.token_tracker as token_tracker

        tracker = token_tracker.TokenTracker("data/tokens.db", prices)
        callback = TokenCallback(tracker)
        llm = ChatOpenAI(callbacks=[callback])
"""

import pathlib
import sqlite3

import langchain_core.callbacks as lc_callbacks
import yaml


def load_prices(prices_path: str) -> dict[str, dict[str, float]]:
    """加载人民币元/百万 Token 价格表，并在配置边界严格校验。"""
    if not prices_path:
        raise ValueError("❌ 价格配置路径不能为空。")
    p = pathlib.Path(prices_path)
    if not p.exists():
        raise FileNotFoundError(f"价格配置文件不存在: {prices_path}")
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict) or data.get("currency") != "CNY" or data.get("unit") != "yuan_per_million_tokens":
        raise ValueError("❌ 价格配置无效: 必须声明 currency: CNY 和 unit: yuan_per_million_tokens。")
    models = data.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError("❌ 价格配置无效: [models] 必须是非空对象。")
    for model, price in models.items():
        if not isinstance(model, str) or not model.strip() or not isinstance(price, dict):
            raise ValueError("❌ 价格配置无效: 模型名和价格项必须有效。")
        for field in ("input", "output"):
            if field in price and (isinstance(price[field], bool) or not isinstance(price[field], (int, float)) or price[field] < 0):
                raise ValueError(f"❌ 价格配置无效: [models.{model}.{field}] 必须是非负数字。")
        if "input" not in price:
            raise ValueError(f"❌ 价格配置无效: [models.{model}.input] 缺失。")
    return models


def validate_model_prices(prices: dict[str, dict[str, float]], *models: str) -> None:
    """确保运行中实际会调用的模型均有价格，避免静默记为零成本。"""
    missing = [model for model in models if model and model not in prices]
    if missing:
        raise ValueError(f"❌ 价格配置缺少当前启用模型: {', '.join(missing)}。")


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
        cost = (input_tokens / 1_000_000.0) * input_price + (output_tokens / 1_000_000.0) * output_price

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO token_usage (model, input_tokens, output_tokens, cost) "
                "VALUES (?, ?, ?, ?)",
                (model, input_tokens, output_tokens, cost),
            )
            conn.commit()
        return cost

    def record_embedding(self, model: str, tokens: int) -> float:
        """记录一次 embedding 调用（仅有 total_tokens，无 output）。"""
        price = self._prices.get(model, {})
        input_price = price.get("input", 0.0)
        cost = (tokens / 1_000_000.0) * input_price

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO token_usage (model, input_tokens, output_tokens, cost) "
                "VALUES (?, ?, ?, ?)",
                (model, tokens, 0, cost),
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

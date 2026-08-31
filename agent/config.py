"""
配置模块：通过 -c 参数读取统一 YAML 配置。

所有 Agent 配置均从公共段读取，服务地址从 Http/Agent 段读取。
"""

import argparse
import pathlib
import typing

import yaml


def _split_addr(addr: str, default_host: str) -> tuple[str, int]:
    """解析 host:port 地址，缺省 host 时使用 default_host。"""
    host, sep, port = addr.rpartition(":")
    if not sep or not port.isdigit():
        raise ValueError(f"❌ 配置无效: 地址必须是 host:port，实际为 {addr!r}")
    return host or default_host, int(port)


def _addr_to_local_url(addr: str) -> str:
    """将监听地址转换为本机服务访问地址。"""
    host, port = _split_addr(addr, "127.0.0.1")
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def _require_int(value: typing.Any, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"❌ 配置无效: [{path}] 必须是大于等于 {minimum} 的整数。")
    return value


def _require_number(value: typing.Any, path: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ValueError(f"❌ 配置无效: [{path}] 必须是大于等于 {minimum} 的数字。")
    return float(value)


class Config:
    """统一管理 Agent 所需配置，缺失必填项时直接报错。"""

    def __init__(self, config_path: str):
        self.llm_api_key = ""
        self.llm_model = ""
        self.llm_base_url = ""
        self.llm_fallback_model = ""
        self.retry_enabled = True
        self.retry_max_attempts = 3
        self.llm_request_timeout = 60.0
        self.tool_max_rounds = 20

        self.embedding_model = ""
        self.embedding_context_size = 0
        self.chunk_strategy = "none"
        self.chunk_size = 500
        self.chunk_overlap = 50
        self.heading_level = 2

        self.go_backend_url = ""
        self.agent_addr = ""
        self.agent_url = ""
        self.agent_host = ""
        self.agent_port = 0
        self.agent_data_dir = ""
        self.chat_db_path = ""
        self.runtime_max_steps = 12
        self.runtime_timeout_seconds = 300.0
        self.runtime_cost_limit = 2.0
        self.eval_reports_dir = ""
        self.evaluation_config_path = ""
        self.prices_path = ""
        self.rag_distance_threshold: float | None = None
        self.rag_auto_distance_ratio = 1.8
        self.compose_group_limit = 20
        self.compose_cover_limit = 40
        self.project_root = pathlib.Path(".")

        self._load_from_yaml(config_path)

    @staticmethod
    def _require(data: dict, section: str, key: str) -> typing.Any:
        section_dict = data.get(section)
        if not isinstance(section_dict, dict):
            raise KeyError(f"❌ 配置缺失: 缺少 [{section}] 配置段。")
        if key not in section_dict:
            raise KeyError(f"❌ 配置缺失: [{section}].{key} 未配置。")

        value = section_dict[key]
        if value is None or (isinstance(value, str) and value.strip() == ""):
            raise ValueError(f"❌ 配置无效: [{section}].{key} 值为空。")
        return value

    @staticmethod
    def _optional(data: dict, section: str, key: str, fallback: typing.Any) -> typing.Any:
        section_dict = data.get(section, {})
        if not isinstance(section_dict, dict):
            return fallback
        return section_dict.get(key, fallback)

    def _load_from_yaml(self, config_path: str) -> None:
        path = pathlib.Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with path.open(encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        if not isinstance(data, dict):
            raise ValueError(f"❌ 配置无效: 根节点必须是对象: {config_path}")

        self.llm_api_key = self._require(data, "LLM", "APIKey")
        self.llm_model = self._require(data, "LLM", "Model")
        self.llm_base_url = self._require(data, "LLM", "BaseURL")
        self.llm_fallback_model = self._optional(data, "LLM", "FallbackModel", "")
        retry_enabled = self._optional(data, "LLM", "RetryEnabled", True)
        if not isinstance(retry_enabled, bool):
            raise ValueError("❌ 配置无效: [LLM].RetryEnabled 必须是布尔值。")
        self.retry_enabled = retry_enabled
        self.retry_max_attempts = _require_int(
            self._optional(data, "LLM", "RetryMaxAttempts", 3), "LLM.RetryMaxAttempts", 1
        )
        self.llm_request_timeout = _require_number(
            self._optional(data, "LLM", "RequestTimeout", 60.0), "LLM.RequestTimeout", 0.001
        )
        self.tool_max_rounds = _require_int(
            self._optional(data, "LLM", "ToolMaxRounds", 20), "LLM.ToolMaxRounds", 1
        )

        self.embedding_model = self._require(data, "Embedding", "Model")
        self.embedding_context_size = _require_int(
            self._optional(data, "Embedding", "ContextSize", 0), "Embedding.ContextSize", 0
        )
        self.chunk_strategy = self._optional(data, "Embedding", "ChunkStrategy", "none")
        if self.chunk_strategy not in {"none", "fixed_size", "markdown_heading"}:
            raise ValueError("❌ 配置无效: [Embedding].ChunkStrategy 必须是 none、fixed_size 或 markdown_heading。")
        self.chunk_overlap = _require_int(
            self._optional(data, "Embedding", "ChunkOverlap", 50), "Embedding.ChunkOverlap", 0
        )
        self.heading_level = _require_int(
            self._optional(data, "Embedding", "HeadingLevel", 2), "Embedding.HeadingLevel", 1
        )
        configured_chunk_size = self._optional(data, "Embedding", "ChunkSize", None)
        if configured_chunk_size is not None:
            self.chunk_size = _require_int(configured_chunk_size, "Embedding.ChunkSize", 1)
        elif self.embedding_context_size > 0:
            self.chunk_size = int(self.embedding_context_size * 0.5)

        self.go_backend_url = _addr_to_local_url(self._require(data, "Http", "Addr"))
        self.agent_addr = self._require(data, "Agent", "Addr")
        self.agent_url = _addr_to_local_url(self.agent_addr)
        self.agent_host, self.agent_port = _split_addr(self.agent_addr, "0.0.0.0")
        self.agent_data_dir = self._require(data, "Agent", "DataDir")
        self.chat_db_path = self._require(data, "Agent", "ChatDBPath")
        self.runtime_max_steps = _require_int(
            self._optional(data, "Agent", "RuntimeMaxSteps", 12), "Agent.RuntimeMaxSteps", 1
        )
        self.runtime_timeout_seconds = _require_number(
            self._optional(data, "Agent", "RuntimeTimeoutSeconds", 300.0),
            "Agent.RuntimeTimeoutSeconds", 0.001,
        )
        self.runtime_cost_limit = _require_number(
            self._optional(data, "Agent", "RuntimeCostLimit", 2.0), "Agent.RuntimeCostLimit", 0
        )

        self.prices_path = self._require(data, "Prices", "Path")
        distance_threshold = self._optional(data, "RAG", "DistanceThreshold", None)
        self.rag_distance_threshold = (
            float(distance_threshold) if distance_threshold is not None else None
        )
        self.rag_auto_distance_ratio = _require_number(
            self._optional(data, "RAG", "AutoDistanceRatio", 1.8), "RAG.AutoDistanceRatio", 1
        )
        self.compose_group_limit = _require_int(
            self._optional(data, "Compose", "GroupLimit", 20), "Compose.GroupLimit", 1
        )
        self.compose_cover_limit = _require_int(
            self._optional(data, "Compose", "CoverLimit", 40), "Compose.CoverLimit", 1
        )
        if self.compose_cover_limit < self.compose_group_limit:
            raise ValueError("❌ 配置无效: [Compose].CoverLimit 必须大于等于 GroupLimit。")
        if self.rag_distance_threshold is not None and self.rag_distance_threshold < 0:
            raise ValueError("❌ 配置无效: [RAG].DistanceThreshold 必须大于等于 0。")

        if self.chunk_strategy == "fixed_size" and self.chunk_overlap >= self.chunk_size:
            raise ValueError("❌ 配置无效: [Embedding].ChunkOverlap 必须小于 ChunkSize。")

        self.eval_reports_dir = self._require(data, "Evaluation", "ReportsDir")
        self.evaluation_config_path = self._require(data, "Evaluation", "ConfigPath")
        project_root = pathlib.Path(self._require(data, "Storage", "ProjectRoot"))
        self.project_root = (
            project_root
            if project_root.is_absolute()
            else (path.parent / project_root)
        ).resolve()

    def resolve_path(self, rel_path: str) -> pathlib.Path:
        path = pathlib.Path(rel_path)
        if path.is_absolute():
            return path
        return (self.project_root / path).resolve()

    def agent_path(self, *parts: str) -> pathlib.Path:
        return self.resolve_path(self.agent_data_dir).joinpath(*parts)

    def check_api_key(self) -> None:
        if not self.llm_api_key:
            raise ValueError("❌ LLM API Key 未配置！请通过 -c 参数指定 YAML 配置文件。")

    def __repr__(self) -> str:
        return (
            f"Config(model={self.llm_model}, "
            f"backend={self.go_backend_url}, agent={self.agent_addr})"
        )


def load_config(config_path: typing.Optional[str] = None) -> Config:
    """加载配置，从 config_path 指定的 YAML 文件读取。"""
    if not config_path:
        parser = argparse.ArgumentParser()
        parser.add_argument("-c", "--config", required=True, help="YAML 配置文件路径")
        args = parser.parse_args()
        config_path = args.config

    cfg = Config(config_path)
    cfg.check_api_key()
    print(f"✅ 配置加载成功: {cfg}")
    print()
    return cfg

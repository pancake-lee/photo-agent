"""
    配置模块：通过 -c 参数指定 YAML 配置文件读取所有配置。

    所有配置项均从 YAML 读取，代码中不设默认值，缺失即报错。

    用法：cfg = config.load_config()
"""

import argparse
import pathlib
import typing

import yaml


class Config:
    """统一管理所有配置，从 YAML 文件严格读取，缺失即报错。"""

    def __init__(self, config_path: str):
        """
        初始化配置。

        参数:
            config_path: YAML 配置文件路径，必须提供。
        """
        self.llm_api_key: str = ""
        self.llm_model: str = ""
        self.llm_base_url: str = ""

        self.embedding_api_key: str = ""
        self.embedding_model: str = ""
        self.embedding_base_url: str = ""
        self.embedding_context_size: int = 0

        self.chunk_strategy: str = "none"
        self.chunk_size: int = 500
        self.chunk_overlap: int = 50
        self.heading_level: int = 2

        self.go_backend_url: str = ""

        self.llm_fallback_model: str = ""
        self.prices_path: str = ""
        self.retry_enabled: bool = True
        self.retry_max_attempts: int = 3
        self.llm_request_timeout: float = 60.0

        self.project_root: pathlib.Path = pathlib.Path(".")

        self._load_from_yaml(config_path)

    @staticmethod
    def _require(data: dict, section: str, key: str) -> typing.Any:
        """从配置字典中严格读取指定键，缺失则报错。"""
        section_dict = data.get(section)
        if section_dict is None:
            raise KeyError(
                f"❌ 配置缺失: 缺少 [{section}] 配置段。\n"
                f"   请在配置文件中添加 '{section}:' 并包含必要的子配置。"
            )

        if key not in section_dict:
            raise KeyError(
                f"❌ 配置缺失: [{section}].{key} 未配置。\n"
                f"   请在配置文件中设置该值。"
            )

        value = section_dict[key]
        if value is None or (isinstance(value, str) and value.strip() == ""):
            raise ValueError(
                f"❌ 配置无效: [{section}].{key} 值为空。\n"
                f"   请设置一个有效值。"
            )
        return value

    @staticmethod
    def _optional(data: dict, section: str, key: str, fallback: typing.Any = None) -> typing.Any:
        """从配置字典中读取指定键，缺失则返回 fallback。"""
        section_dict = data.get(section, {})
        return section_dict.get(key, fallback)

    def _load_from_yaml(self, config_path: str):
        """从 YAML 文件严格读取配置，缺失项直接报错。"""
        path = pathlib.Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # llm 配置（必填）
        self.llm_api_key = self._require(data, "llm", "api_key")
        self.llm_model = self._require(data, "llm", "model")
        self.llm_base_url = self._require(data, "llm", "base_url")

        # embedding 配置（必填，但 api_key 可回退到 llm）
        self.embedding_model = self._require(data, "embedding", "model")
        self.embedding_base_url = self._require(data, "embedding", "base_url")
        emb_key = self._optional(data, "embedding", "api_key", "")
        self.embedding_api_key = emb_key if emb_key else self.llm_api_key

        # embedding 分块配置（可选）
        self.embedding_context_size = self._optional(data, "embedding", "context_size", 0)
        self.chunk_strategy = self._optional(data, "embedding", "chunk_strategy", "none")
        self.chunk_overlap = self._optional(data, "embedding", "chunk_overlap", 50)
        self.heading_level = self._optional(data, "embedding", "heading_level", 2)

        # chunk_size 默认逻辑：优先配置值，无配置时取 context_size 的 50%，兜底 500
        configured_chunk_size = self._optional(data, "embedding", "chunk_size", None)
        if configured_chunk_size is not None:
            self.chunk_size = int(configured_chunk_size)
        elif self.embedding_context_size > 0:
            self.chunk_size = int(self.embedding_context_size * 0.5)
        else:
            self.chunk_size = 500

        # llm fallback 配置（可选）
        self.llm_fallback_model = self._optional(data, "llm", "fallback_model", "")
        self.retry_enabled = self._optional(data, "llm", "retry_enabled", True)
        self.retry_max_attempts = self._optional(data, "llm", "retry_max_attempts", 3)
        self.llm_request_timeout = float(self._optional(data, "llm", "request_timeout", 60.0))

        # server 配置（必填）
        # server.addr 格式为 "host:port"（如 "0.0.0.0:10004" 或 ":10004"）
        # 0.0.0.0 是监听地址，客户端连接需替换为 127.0.0.1
        server_addr: str = self._require(data, "server", "addr")
        if ":" in server_addr:
            host, port = server_addr.rsplit(":", 1)
            if not host or host == "0.0.0.0":
                host = "127.0.0.1"
        else:
            host, port = "127.0.0.1", server_addr
        self.go_backend_url = f"http://{host}:{port}"

        # prices 配置（可选）
        self.prices_path = self._optional(data, "prices", "path", "")

        # rag 配置（可选）
        self.rag_distance_threshold: float | None = self._optional(data, "rag", "distance_threshold", None)
        self.rag_auto_distance_ratio: float = float(self._optional(data, "rag", "auto_distance_ratio", 1.8))

        # chat 配置（可选）
        self.chat_db_path: str = self._optional(data, "chat", "db_path", "")

        # storage 配置（必填）
        self.project_root = pathlib.Path(
            self._require(data, "storage", "project_root")
        ).resolve()

    def resolve_path(self, rel_path: str) -> pathlib.Path:
        """
        将相对路径解析为基于 project_root 的绝对路径。

        如果路径已是绝对路径，则直接返回。
        """
        p = pathlib.Path(rel_path)
        if p.is_absolute():
            return p
        return (self.project_root / p).resolve()

    def check_api_key(self):
        """检查 LLM 的 API Key 是否已配置。"""
        if not self.llm_api_key:
            raise ValueError(
                "❌ LLM API Key 未配置！\n"
                "   请通过 -c 参数指定 YAML 配置文件:\n"
                "   python script.py -c ../.local/my-config.yaml"
            )

    def __repr__(self):
        return (
            f"Config(model={self.llm_model}, "
            f"base_url={self.llm_base_url}, "
            f"go_backend={self.go_backend_url})"
        )


def load_config(config_path: typing.Optional[str] = None) -> Config:
    """加载配置，从 config_path 指定的 YAML 文件读取。"""

    if not config_path:
        # 解析命令行参数
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-c", "--config",
            dest="config", required=True,
            help="YAML 配置文件路径（如 ../.local/config.yaml）",
        )
        args = parser.parse_args()
        config_path = args.config

    # 加载配置
    cfg = Config(config_path) # type: ignore
    cfg.check_api_key()
    print(f"✅ 配置加载成功: {cfg}")
    print()
    return cfg

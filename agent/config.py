"""
配置模块：通过 -c 参数指定 YAML 配置文件读取所有配置。

用法（在每个脚本里）：
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True, help="YAML 配置文件路径")
    args = parser.parse_args()

    cfg = Config(config_path=args.config)
"""

import argparse
import pathlib
import typing

import yaml


class Config:
    """统一管理所有配置，从 YAML 文件读取。"""

    def __init__(self, config_path: str):
        """
        初始化配置。

        参数:
            config_path: YAML 配置文件路径，必须提供。
        """
        # 默认配置
        self.llm_api_key: str = ""
        self.llm_model: str = "doubao-pro-32k-241215"
        self.llm_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"

        self.embedding_api_key: str = ""
        self.embedding_model: str = "doubao-embedding-vision-251215"
        self.embedding_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"

        self.go_backend_url: str = "http://localhost:8080"

        self._load_from_yaml(config_path)

    def _load_from_yaml(self, config_path: str):
        """从 YAML 文件读取配置。"""
        path = pathlib.Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # llm 配置
        llm = data.get("llm", {})
        self.llm_api_key = llm.get("api_key", "")
        self.llm_model = llm.get("model", self.llm_model)
        self.llm_base_url = llm.get("base_url", self.llm_base_url)

        # embedding 配置
        emb = data.get("embedding", {})
        self.embedding_api_key = emb.get("api_key", "")
        self.embedding_model = emb.get("model", self.embedding_model)
        self.embedding_base_url = emb.get("base_url", self.embedding_base_url)

        # 如果 embedding 没有单独配 key，回退到 llm 的 key
        if not self.embedding_api_key:
            self.embedding_api_key = self.llm_api_key

        # go 后端地址
        server = data.get("server", {})
        addr = server.get("addr", ":8080")
        self.go_backend_url = f"http://localhost{addr}"

    def check_api_key(self):
        """检查 LLM 的 API Key 是否已配置。"""
        if not self.llm_api_key:
            raise ValueError(
                "❌ LLM API Key 未配置！\n"
                "   请通过 -c 参数指定 YAML 配置文件:\n"
                "   python script.py -c ../.local/pancake.yaml"
            )

    def __repr__(self):
        return (
            f"Config(model={self.llm_model}, "
            f"base_url={self.llm_base_url}, "
            f"go_backend={self.go_backend_url})"
        )

def load_config(config_path: typing.Optional[str] = None) -> Config:
    """加载配置，从 config_path 指定的 YAML 文件读取。"""
    # 解析命令行参数
    parser = argparse.ArgumentParser()
    parser.add_argument("-c","--config",
        dest="config",required=True,
        help="YAML 配置文件路径（如 ../.local/config.yaml）",
    )
    args = parser.parse_args()

    # 加载配置（-c 指定 YAML，否则读 .env）
    cfg = Config(config_path=args.config)
    cfg.check_api_key()
    print(f"✅ 配置加载成功: {cfg}")
    print()
    return cfg
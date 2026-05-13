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

        self.go_backend_url: str = ""

        self.project_root: pathlib.Path = pathlib.Path(".")
        self.descriptions_path: str = ""

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

        # server 配置（必填）
        server_addr = self._require(data, "server", "addr")
        self.go_backend_url = f"http://localhost{server_addr}"

        # storage 配置（必填）
        self.project_root = pathlib.Path(
            self._require(data, "storage", "project_root")
        ).resolve()
        self.descriptions_path = self._require(data, "storage", "descriptions_path")

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
    parser.add_argument(
        "-c", "--config",
        dest="config", required=True,
        help="YAML 配置文件路径（如 ../.local/config.yaml）",
    )
    args = parser.parse_args()

    # 加载配置
    cfg = Config(config_path=args.config)
    cfg.check_api_key()
    print(f"✅ 配置加载成功: {cfg}")
    print()
    return cfg

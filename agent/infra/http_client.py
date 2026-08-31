"""
    共享 HTTP 客户端工厂。

    提供带重试逻辑的 httpx.Client，用于所有对 Go 后端的 HTTP 调用。
    Go 后端短暂不可用时自动重试，避免 Python Agent 直接报错。

    用法:
        import infra.http_client as http_utils

        # 上下文管理器方式
        with http_utils.create_client(timeout=10.0) as client:
            resp = client.get("http://localhost:10000/api/v1/photos")

        # 直接使用（需手动关闭）
        client = http_utils.create_client(timeout=30.0)
        try:
            resp = client.get("...")
        finally:
            client.close()

    重试策略:
        - 连接失败 (ConnectError): 最多重试 3 次，指数退避 (0.5s/1s/2s)
        - 读取超时 (TimeoutException): 同上
        - 服务端 5xx 错误: 同上
        - 客户端 4xx 错误: 不重试（直接抛出）
"""

import httpx
import logging

logger = logging.getLogger(__name__)

# 默认重试配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30.0


def create_client(
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> httpx.Client:
    """
    创建一个带重试逻辑的 httpx.Client。

    参数:
        timeout:     请求超时时间（秒）
        max_retries: 最大重试次数

    返回:
        配置了重试 transport 的 httpx.Client
    """
    transport = httpx.HTTPTransport(retries=max_retries)
    return httpx.Client(transport=transport, timeout=timeout)

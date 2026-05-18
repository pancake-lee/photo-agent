"""
    Embedding 调用封装模块。

    通过 go-server 的 `/v1/embeddings` 代理接口调用 embedding 服务。
    请求/响应均使用 OpenAI 标准格式，与具体模型提供商解耦。

    为什么不用 langchain_openai.OpenAIEmbeddings：
    - OpenAIEmbeddings 默认启用 tiktoken，会将文本预编码为 token ID 数组后传给 API
    - 我们的 go-server 代理只接受原始字符串 input，无法处理 token ID 数组 → 返回 400
    - 禁用 tiktoken（tiktoken_enabled=False）后，LangChain 会 fallback 到 transformers
      tokenizer，但 transformers 不在当前依赖中，引入它得不偿失
    - 因此直接使用 httpx 发送标准 OpenAI 格式请求，代码更简洁、可控

    用法：
        from embedding.embedder import Embedder

        embedder = Embedder(base_url="http://localhost:10000", model="xxx")
        vectors = embedder.embed_texts(["文本1", "文本2"])
"""

import httpx
import numpy as np


class Embedder:
    """通过 go-server 代理调用 Embedding 服务。"""

    def __init__(
        self,
        base_url: str,
        model: str,
        tracker=None,
    ):
        """
        初始化 Embedder。

        参数:
            base_url: go-server 地址，如 http://localhost:10000
            model:    模型名称，由服务端配置决定
            tracker:  可选 TokenTracker，用于持久化 token 用量
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(timeout=60.0)
        self._tracker = tracker
        self.total_tokens = 0

    def embed_texts(self, texts: list[str]) -> list[np.ndarray]:
        """
        批量计算文本的 Embedding 向量。

        使用 OpenAI 标准格式请求，通过 go-server 代理转发到实际模型。

        参数:
            texts: 待编码的文本列表

        返回:
            与输入顺序一致的向量列表
        """
        if not texts:
            return []

        url = f"{self.base_url}/v1/embeddings"
        payload = {
            "model": self.model,
            "input": texts,
        }

        resp = self._client.post(url, json=payload)
        resp.raise_for_status()

        data = resp.json()

        # 累计并持久化 token 用量
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", 0)
        self.total_tokens += tokens
        if self._tracker and tokens > 0:
            self._tracker.record_embedding(self.model, tokens)

        # 按 index 排序，保证与输入顺序一致
        items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))

        vectors: list[np.ndarray] = []
        for item in items:
            embedding = item.get("embedding", [])
            if not embedding:
                raise ValueError(f"embedding 结果为空: {item}")
            vectors.append(np.array(embedding, dtype=np.float32))

        return vectors

    def __del__(self):
        """关闭 HTTP 客户端。"""
        if hasattr(self, "_client"):
            self._client.close()

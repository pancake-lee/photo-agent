"""
    ChromaDB 照片向量库存储封装。

    提供 Collection 级别的增删改查和向量相似度搜索，
    不负责 Embedding 生成（由调用方或上层 Chain 处理）。

    用法（作为模块导入）:
        import vectorstore.chroma_client as chroma_client

        store = chroma_client.ChromaPhotoStore(persist_dir="./data/chroma")
        store.add(
            ids=["photo_001", "photo_002"],
            documents=["夕阳下的海滩", "雪山清晨"],
            metadatas=[{"file_path": "/a.jpg"}, {"file_path": "/b.jpg"}],
            embeddings=[[0.1, ...], [0.2, ...]],  # 预计算向量
        )
        results = store.query(query_embeddings=[[0.1, ...]], n_results=3)

    用法（独立演示）:
        venv/bin/python vectorstore/chroma_client.py
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import typing

# 部分系统 sqlite3 版本过低，用 pysqlite3 替代后再导入 chromadb
import sqlite3

if sqlite3.sqlite_version_info < (3, 35, 0):
    import pysqlite3

    sys.modules["sqlite3"] = pysqlite3

import chromadb
import chromadb.config as chroma_config


class ChromaPhotoStore:
    """基于 ChromaDB 的照片描述向量存储。"""

    def __init__(
        self,
        persist_dir: str = "./data/chroma",
        collection_name: str = "photos",
    ):
        """
        初始化 ChromaDB 持久化客户端并获取/创建 Collection。

        参数:
            persist_dir: 数据持久化目录路径。
            collection_name: Collection 名称，类似 SQL 的"表名"。
        """
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(name=collection_name)

    # ------------------------------------------------------------------ #
    # 写入操作
    # ------------------------------------------------------------------ #

    def add(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: typing.Optional[list[dict]] = None,
        embeddings: typing.Optional[list[list[float]]] = None,
    ) -> None:
        """
        批量添加或更新文档。

        注意:
            - 若提供 embeddings，则直接入库；否则需确保 Chroma 已配置 embedding_function。
            - 本项目的使用模式由上层调用方预计算 embedding 后传入，因此 embeddings 通常不为 None。
            - ids 重复时会覆盖已有数据。

        参数:
            ids: 文档唯一标识列表，长度需与 documents 一致。
            documents: 文本内容列表（照片描述）。
            metadatas: 每条文档的附加元数据（如 photo_id、file_path）。
            embeddings: 预计算的向量列表，长度和维度需一致。
        """
        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def delete(
        self,
        ids: typing.Optional[list[str]] = None,
        where: typing.Optional[dict] = None,
    ) -> None:
        """
        删除指定文档。

        参数:
            ids: 要删除的文档 ID 列表（与 where 二选一）。
            where: 元数据过滤条件，如 {"brand": "NIKON"}。
        """
        self.collection.delete(ids=ids, where=where)

    # ------------------------------------------------------------------ #
    # 查询操作
    # ------------------------------------------------------------------ #

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int = 5,
        where: typing.Optional[dict] = None,
        where_document: typing.Optional[dict] = None,
    ) -> list[dict]:
        """
        向量相似度搜索。

        参数:
            query_embeddings: 查询向量列表（支持批量查询，通常传一个即可）。
            n_results: 每个查询返回的最相似结果数量。
            where: 元数据过滤条件，如 {"brand": "Canon"}、{"iso": {"$gte": 100}}。
            where_document: 文档内容过滤条件。

        返回:
            格式化后的结果列表，每条包含:
            - id: 文档 ID
            - document: 文本内容
            - metadata: 元数据字典
            - distance: 向量距离（越小越相似）
        """
        raw = self.collection.query(
            query_embeddings=query_embeddings,
            n_results=n_results,
            where=where,
            where_document=where_document,
            include=["metadatas", "documents", "distances"],
        )
        return self._format_results(raw)

    def get(
        self,
        ids: typing.Optional[list[str]] = None,
        where: typing.Optional[dict] = None,
    ) -> list[dict]:
        """
        按 ID 或条件精确获取文档（非相似度搜索）。

        参数:
            ids: 文档 ID 列表。
            where: 元数据过滤条件。

        返回:
            格式化后的结果列表，不含 distance 字段。
        """
        raw = self.collection.get(
            ids=ids,
            where=where,
            include=["metadatas", "documents"],
        )
        return self._format_get_results(raw)

    def peek(self, n: int = 5) -> list[dict]:
        """查看集合中的前 n 条数据（调试用）。"""
        raw = self.collection.peek(limit=n)
        return self._format_get_results(raw)

    def count(self) -> int:
        """返回集合中的文档总数。"""
        return self.collection.count()

    # ------------------------------------------------------------------ #
    # 内部格式化
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_results(raw: dict) -> list[dict]:
        """
        将 Chroma query 原始返回格式化为扁平列表。

        Chroma 返回结构:
            {
                "ids": [["id1", "id2"]],
                "distances": [[0.1, 0.2]],
                "metadatas": [[{"k": "v"}, {"k": "v"}]],
                "documents": [["doc1", "doc2"]],
            }

        返回扁平列表，方便上层直接遍历使用。
        """
        results: list[dict] = []
        ids_batch = raw.get("ids", [])
        distances_batch = raw.get("distances", [])
        metadatas_batch = raw.get("metadatas", [])
        documents_batch = raw.get("documents", [])

        for i, ids in enumerate(ids_batch):
            distances = distances_batch[i] if i < len(distances_batch) else []
            metadatas = metadatas_batch[i] if i < len(metadatas_batch) else []
            documents = documents_batch[i] if i < len(documents_batch) else []

            for j, doc_id in enumerate(ids):
                results.append({
                    "id": doc_id,
                    "document": documents[j] if j < len(documents) else None,
                    "metadata": metadatas[j] if j < len(metadatas) else None,
                    "distance": distances[j] if j < len(distances) else None,
                })
        return results

    @staticmethod
    def _format_get_results(raw: dict) -> list[dict]:
        """将 Chroma get/peek 原始返回格式化为扁平列表（不含 distance）。"""
        results: list[dict] = []
        ids = raw.get("ids", [])
        metadatas = raw.get("metadatas", [])
        documents = raw.get("documents", [])

        for i, doc_id in enumerate(ids):
            results.append({
                "id": doc_id,
                "document": documents[i] if i < len(documents) else None,
                "metadata": metadatas[i] if i < len(metadatas) else None,
            })
        return results


# ---------------------------------------------------------------------- #
# 独立演示
# ---------------------------------------------------------------------- #

def _demo() -> None:
    """独立运行演示：展示 ChromaPhotoStore 的增删查功能。"""
    print("🎯 ChromaPhotoStore 演示")
    print("=" * 60)
    print()

    # 部分系统 sqlite3 版本过低，用 pysqlite3 替代
    import sys
    import sqlite3

    if sqlite3.sqlite_version_info < (3, 35, 0):
        import pysqlite3

        sys.modules["sqlite3"] = pysqlite3

    # 使用内存模式演示（不污染持久化数据）
    import chromadb

    client = chromadb.Client()
    store = ChromaPhotoStore.__new__(ChromaPhotoStore)
    store.persist_dir = ":memory:"
    store.collection_name = "demo_photos"
    store.client = client
    store.collection = client.create_collection(name="demo_photos")

    # 模拟数据：照片描述 + 预计算 embedding（3维简化演示）
    photo_ids = ["photo_001", "photo_002", "photo_003"]
    documents = [
        "夕阳下的金色海滩，海浪拍打着礁石",
        "黄昏海边，晚霞映照在波涛上",
        "雪山之巅的清晨，冰川闪耀蓝光",
    ]
    metadatas = [
        {"file_path": "/photos/beach_01.jpg", "brand": "Canon"},
        {"file_path": "/photos/beach_02.jpg", "brand": "Sony"},
        {"file_path": "/photos/mountain_01.jpg", "brand": "Nikon"},
    ]
    # 简化向量：海滩两组向量相近，雪山较远
    embeddings = [
        [1.0, 0.8, 0.1],
        [0.9, 0.85, 0.15],
        [0.1, 0.2, 1.0],
    ]

    print("📥 写入 3 条照片描述...")
    store.add(
        ids=photo_ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )
    print(f"✅ 当前集合文档数: {store.count()}")
    print()

    # 查询：用接近海滩的向量搜索
    print("🔍 向量搜索（查询向量接近海滩场景）...")
    query_vec = [[0.95, 0.82, 0.12]]
    results = store.query(query_embeddings=query_vec, n_results=2)
    for r in results:
        print(f"  ID: {r['id']}")
        print(f"  描述: {r['document']}")
        print(f"  距离: {r['distance']:.4f}")
        print(f"  元数据: {r['metadata']}")
        print()

    # 元数据过滤查询
    print("🔍 元数据过滤（brand = Canon）...")
    filtered = store.get(where={"brand": "Canon"})
    for r in filtered:
        print(f"  ID: {r['id']} -> {r['document']}")
    print()

    # 删除演示
    print("🗑️  删除 photo_003...")
    store.delete(ids=["photo_003"])
    print(f"✅ 当前集合文档数: {store.count()}")
    print()

    print("📋 最终集合内容（peek）:")
    for r in store.peek(n=5):
        print(f"  {r['id']}: {r['document']}")


if __name__ == "__main__":
    _demo()

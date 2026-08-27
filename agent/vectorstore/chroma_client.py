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
import hashlib


import typing

# 部分系统 sqlite3 版本过低，用 pysqlite3 替代后再导入 chromadb
import sqlite3

if sqlite3.sqlite_version_info < (3, 35, 0):
    import pysqlite3

    sys.modules["sqlite3"] = pysqlite3

import chromadb
import chromadb.config as chroma_config


# 组图检索的三个 Collection 名：全量照片 / 精细连拍组封面 / 模糊连拍组封面
COLLECTION_PHOTOS = "photos"
COLLECTION_BURST_FINE = "photos_burst_fine"
COLLECTION_BURST_COARSE = "photos_burst_coarse"


def description_version(description: str) -> str:
    """返回向量输入描述的稳定版本标识。"""
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


class ChromaPhotoStore:
    """基于 ChromaDB 的照片描述向量存储。"""

    def __init__(
        self,
        persist_dir: str = "./data/chroma",
        collection_name: str = COLLECTION_PHOTOS,
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
            metadatas=metadatas,# type: ignore[arg-type] 
            embeddings=embeddings,# type: ignore[arg-type] 
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
            query_embeddings=query_embeddings, # type: ignore[arg-type]
            n_results=n_results,
            where=where,
            where_document=where_document,
            include=["metadatas", "documents", "distances"],
        )
        return self._format_results(raw) # type: ignore[arg-type] 

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
        return self._format_get_results(raw) # type: ignore[arg-type] 

    def peek(self, n: int = 5) -> list[dict]:
        """查看集合中的前 n 条数据（调试用）。"""
        raw = self.collection.peek(limit=n)
        return self._format_get_results(raw) # type: ignore[arg-type] 

    def count(self) -> int:
        """返回集合中的文档总数。"""
        return self.collection.count()

    def get_photo_embedding_info(self, photo_id: str) -> dict | None:
        """
        获取单张照片的 embedding 详细信息。

        ChromaDB metadata 存 photo_id + chunk_index（关联标识），以及 model + embedded_at
        （向量操作记录，向量生成时所用的模型与时间）。旧数据可能缺后两者，此时返回 None。

        返回:
            {
                "photo_id": "...",
                "chunks": 3,
                "model": "text-embedding-...",   # 向量生成时所用模型（旧数据可能为 null）
                "embedded_at": "2026-...",       # 向量生成时间，ISO 8601 UTC（旧数据可能为 null）
                "chunk_info": [...],             # 各 chunk 的 id/chunk_index/preview
            }
            若该 photo_id 无 embedding 数据则返回 None。
        """
        raw = self.collection.get(
            where={"photo_id": photo_id},
            include=["metadatas", "documents"],
        )
        ids = raw.get("ids", [])
        if not ids:
            return None

        metas = raw.get("metadatas", [])
        docs = raw.get("documents", [])

        # 向量操作记录：同一照片的多个 chunk 在同一次嵌入中生成，model/embedded_at 一致，
        # 取首个 chunk 的 metadata 即可
        first_meta = metas[0] if metas else {}

        # 各 chunk 的 id、chunk_index、内容预览
        chunk_info: list[dict] = []
        for i, doc_id in enumerate(ids):
            meta = metas[i] if i < len(metas) else {}
            doc = docs[i] if i < len(docs) else ""
            chunk_info.append({
                "id": doc_id,
                "chunk_index": (meta or {}).get("chunk_index", 0),
                "preview": doc[:200] if doc else "",
            })

        return {
            "photo_id": photo_id,
            "chunks": len(ids),
            "model": first_meta.get("model"),
            "embedded_at": first_meta.get("embedded_at"),
			"description_version": first_meta.get("description_version"),
            "chunk_info": chunk_info,
        }

    def get_embedded_photo_ids(self) -> set[str]:
        """
        返回所有已嵌入的 photo_id 集合（从 metadata 中提取去重）。

        用于 API 查询某个 photo_id 是否已有 embedding 数据，
        也用于 batch_embed CLI 过滤已嵌入的照片。

        注意：此方法直接从 ChromaDB 提取，不校验 photo_id 在 Go 数据库中是否仍存在。
        调用方如需"有效嵌入数"，应自行与 Go 照片列表交叉比对。
        """
        result = self.collection.get(include=["metadatas"])
        ids: set[str] = set()
        for meta in (result.get("metadatas") or []):
            if meta and "photo_id" in meta:
                ids.add(meta["photo_id"])
        return ids

    def get_photo_embedding_versions(self) -> dict[str, set[str]]:
        """一次读取当前集合中每张照片向量所对应的描述版本。"""
        raw = self.collection.get(include=["metadatas"])
        photo_to_version_set: dict[str, set[str]] = {}
        for meta in raw.get("metadatas") or []:
            if not meta or not meta.get("photo_id"):
                continue
            photo_id = meta["photo_id"]
            photo_to_version_set.setdefault(photo_id, set()).add(meta.get("description_version") or "")
        return photo_to_version_set

    def has_current_photo_embedding(self, photo_id: str, description: str, versions: dict[str, set[str]] | None = None) -> bool:
        """按当前 Chroma 内容判断向量可用性，兼容没有版本标识的旧向量。"""
        version_set = (versions or self.get_photo_embedding_versions()).get(photo_id, set())
        if not version_set:
            return False
        return "" in version_set or description_version(description) in version_set

    def cleanup_orphans(self, valid_photo_ids: set[str]) -> int:
        """
        删除 ChromaDB 中 photo_id 不在 valid_photo_ids 中的孤立文档。

        参数:
            valid_photo_ids: 合法的 photo_id 集合（通常来自 Go 后端全量照片列表）。

        返回:
            删除的 photo_id 数量（非文档数）。
        """
        all_ids = self.get_embedded_photo_ids()
        orphan_ids = all_ids - valid_photo_ids
        for pid in orphan_ids:
            self.delete(where={"photo_id": pid})
        return len(orphan_ids)

    # ------------------------------------------------------------------ #
    # 连拍组集合专用操作（photos_burst_fine / photos_burst_coarse）
    # ------------------------------------------------------------------ #

    def add_group_cover(
        self,
        group_id: str,
        cover_photo_id: str,
        photo_count: int,
        documents: list[str],
        embeddings: list[list[float]],
        model: str = "",
        description_version: str = "",
    ) -> None:
        """
        写入/覆盖一个连拍组的封面描述文档（组集合专用）。

        组集合以 group_id 为文档主键，封面更换或组重建后重嵌入时直接覆盖。
        metadata 额外记录 cover_photo_id 与 photo_count，供检索结果组装组卡片。

        参数:
            group_id: 连拍组 ID（如 burst_fine_xxxx）。
            cover_photo_id: 封面照片 ID。
            photo_count: 组内照片数。
            documents: 封面描述分块后的文本片段。
            embeddings: 与 documents 对应的预计算向量。
            model: 向量生成所用模型名（向量溯源信息）。
        """
        from datetime import datetime, timezone

        ids = [f"{group_id}#{i}" for i in range(len(documents))]
        metadatas = [
            {
                "group_id": group_id,
                "photo_id": cover_photo_id,
                "chunk_index": i,
                "photo_count": photo_count,
                "model": model,
                "embedded_at": datetime.now(timezone.utc).isoformat(),
                "description_version": description_version,
            }
            for i in range(len(documents))
        ]
        self.delete_group(group_id)
        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,  # type: ignore[arg-type]
            embeddings=embeddings,  # type: ignore[arg-type]
        )

    def delete_group(self, group_id: str) -> None:
        """删除组集合中指定组的全部文档。"""
        self.collection.delete(where={"group_id": group_id})

    def add_single_photo(
        self,
        photo_id: str,
        documents: list[str],
        embeddings: list[list[float]],
        source_metadatas: list[dict],
    ) -> None:
        """将未分组照片写入连拍粒度集合，复用全量集合的向量。"""
        self.delete(where={"photo_id": photo_id})
        metadatas = [
            {
                "photo_id": photo_id,
                "chunk_index": index,
                "record_type": "single",
                "model": source_meta.get("model", ""),
                "embedded_at": source_meta.get("embedded_at", ""),
                "description_version": source_meta.get("description_version", ""),
            }
            for index, source_meta in enumerate(source_metadatas)
        ]
        self.collection.add(
            ids=[f"{photo_id}#{index}" for index in range(len(documents))],
            documents=documents,
            metadatas=metadatas,  # type: ignore[arg-type]
            embeddings=embeddings,  # type: ignore[arg-type]
        )

    def get_embedded_group_ids(self) -> set[str]:
        """返回组集合中已嵌入的 group_id 集合（从 metadata 提取去重）。"""
        result = self.collection.get(include=["metadatas"])
        ids: set[str] = set()
        for meta in (result.get("metadatas") or []):
            if meta and "group_id" in meta:
                ids.add(meta["group_id"])
        return ids

    def get_group_cover_photo_ids(self) -> dict[str, str]:
        """返回组集合中 group_id -> 当前记录的封面 photo_id 映射。

        用于差量同步时判断封面是否已更换。
        """
        result = self.collection.get(include=["metadatas"])
        mapping: dict[str, str] = {}
        for meta in (result.get("metadatas") or []):
            if meta and "group_id" in meta and "photo_id" in meta:
                # 同组多个 chunk 的 photo_id 一致，重复赋值无影响
                mapping[meta["group_id"]] = meta["photo_id"]
        return mapping

    def cleanup_group_orphans(self, valid_group_ids: set[str]) -> int:
        """
        删除组集合中 group_id 不在 valid_group_ids 中的孤立文档。

        连拍组重建后组 ID 全部变化，此方法清理旧组残留。
        返回删除的 group_id 数量。
        """
        all_group_ids = self.get_embedded_group_ids()
        orphan_ids = all_group_ids - valid_group_ids
        for gid in orphan_ids:
            self.delete_group(gid)
        return len(orphan_ids)

    def clear_single_photos(self) -> int:
        """清理集合中不属于连拍组的单张记录。"""
        result = self.collection.get(include=["metadatas"])
        photo_ids = {
            meta.get("photo_id", "")
            for meta in (result.get("metadatas") or [])
            if meta and not meta.get("group_id") and meta.get("photo_id")
        }
        for photo_id in photo_ids:
            self.delete(where={"photo_id": photo_id})
        return len(photo_ids)

    def replace_single_photos(
        self,
        entries: list[tuple[str, list[str], list[list[float]], list[dict]]],
    ) -> None:
        """批量重建未分组单张记录，避免按照片逐条写入造成启动阻塞。"""
        self.clear_single_photos()
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        embeddings: list[list[float]] = []
        for photo_id, photo_documents, photo_embeddings, source_metas in entries:
            for index, document in enumerate(photo_documents):
                source_meta = source_metas[index] if index < len(source_metas) else {}
                ids.append(f"{photo_id}#{index}")
                documents.append(document)
                metadatas.append({
                    "photo_id": photo_id,
                    "chunk_index": index,
                    "record_type": "single",
                    "model": source_meta.get("model", ""),
                    "embedded_at": source_meta.get("embedded_at", ""),
                    "description_version": source_meta.get("description_version", ""),
                })
                embeddings.append(photo_embeddings[index])
        if not ids:
            return
        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,  # type: ignore[arg-type]
            embeddings=embeddings,  # type: ignore[arg-type]
        )

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

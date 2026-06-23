"""
    EmbedQueue — 照片 Embedding 异步处理队列。

    仿照 Go 后端 VlmQueue 模式设计，提供 start/stop/enqueue/status 接口，
    由 Python Agent Server 的 /api/embed/* 端点驱动。

    核心流程：
        1. Go API 获取照片描述
        2. chunking 分块
        3. Embedder（通过 Go proxy）生成向量
        4. ChromaDB 写入

    用法（在 server.py 中）:
        from chain.embed_queue import EmbedQueue
        queue = EmbedQueue(cfg, chroma_store)
        app.state.embed_queue = queue
"""

import logging
import queue
import threading
import sys
import pathlib

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import config as cfg_module
import embedding.chunking as chunking
import embedding.embedder as embedder
import vectorstore.chroma_client as chroma_client

logger = logging.getLogger(__name__)

BATCH_SIZE = 10  # embedding 每批文本数量


class EmbedQueue:
    """照片 Embedding 异步处理队列。"""

    def __init__(
        self,
        cfg: cfg_module.Config,
        store: chroma_client.ChromaPhotoStore,
    ):
        self._cfg = cfg
        self._store = store
        self._go_url = cfg.go_backend_url.rstrip("/")
        self._http = httpx.Client(timeout=30.0)
        self._embedder = embedder.Embedder(
            base_url=self._go_url,
            model=cfg.embedding_model,
        )

        self._running = False
        self._total = 0
        self._completed = 0
        self._failed = 0
        self._current = ""
        self._lock = threading.Lock()
        self._pending: queue.Queue[str] = queue.Queue()
        self._workers: list[threading.Thread] = []

    # ------------------------------------------------------------------ #
    # 公开接口
    # ------------------------------------------------------------------ #

    def start(self, force: bool = False) -> dict:
        """启动批量 embedding。

        启动前自动清理 ChromaDB 中孤立文档（Go 中已删除的照片）。

        参数:
            force: 为 True 时对所有有描述的照片重新 embedding（跳过已嵌入检查）。

        返回:
            {"status": "started", "total": N} 或 {"error": "..."}
        """
        with self._lock:
            if self._running:
                return {"error": "embed queue is already running"}

            # 启动前先清理孤立数据
            try:
                removed = self.cleanup_orphans()
                if removed > 0:
                    logger.info("EmbedQueue: 清理了 %d 个孤立 photo_id", removed)
            except Exception as e:
                logger.warning("EmbedQueue: 清理孤立数据失败（非致命）: %s", e)

            # 从 Go API 获取有描述的照片
            try:
                if force:
                    photo_ids = self._fetch_embeddable_ids()
                else:
                    photo_ids = self._fetch_unembedded_ids()
            except Exception as e:
                logger.error("EmbedQueue: 获取照片列表失败: %s", e)
                return {"error": f"获取照片列表失败: {e}"}

            if not photo_ids:
                return {"status": "done", "total": 0, "message": "没有需要 embedding 的照片"}

            # 填充队列
            self._total = len(photo_ids)
            self._completed = 0
            self._failed = 0
            self._current = ""
            self._running = True

            for pid in photo_ids:
                self._pending.put(pid)

            # 启动 worker 线程
            concurrency = getattr(self._cfg, "embed_concurrency", None) or 3
            self._workers = []
            for i in range(concurrency):
                t = threading.Thread(target=self._worker, daemon=True)
                t.start()
                self._workers.append(t)

            logger.info(
                "EmbedQueue started: total=%d, force=%s, concurrency=%d",
                self._total, force, concurrency,
            )
            return {"status": "started", "total": self._total}

    def stop(self) -> dict:
        """中止批量 embedding。"""
        with self._lock:
            if not self._running:
                return {"status": "not_running"}

            self._running = False

            # 排空 pending 队列
            while not self._pending.empty():
                try:
                    self._pending.get_nowait()
                except queue.Empty:
                    break

        logger.info(
            "EmbedQueue stopped: completed=%d, failed=%d",
            self._completed, self._failed,
        )
        return {"status": "stopped"}

    def enqueue_one(self, photo_id: str) -> dict:
        """单张照片入队。队列未运行时自动启动。"""
        with self._lock:
            if not self._running:
                self._total = 1
                self._completed = 0
                self._failed = 0
                self._current = ""
                self._running = True

                t = threading.Thread(target=self._process_one, args=(photo_id,), daemon=True)
                t.start()
                self._workers = [t]
            else:
                self._total += 1
                self._pending.put(photo_id)

        logger.info("EmbedQueue enqueued: photo=%s", photo_id)
        return {"status": "enqueued", "photo_id": photo_id}

    def status(self) -> dict:
        """查询当前队列状态。"""
        with self._lock:
            return {
                "running": self._running,
                "total": self._total,
                "completed": self._completed,
                "failed": self._failed,
                "current_file": self._current,
            }

    def get_embed_stats(self) -> dict:
        """
        获取以 Go 照片为索引源的 embedding 统计。

        与 ChromaDB 原始数据不同，此方法先获取 Go 后端全量照片 ID，
        再与 ChromaDB 交叉比对，只统计"Go 中存在且已嵌入"的照片数。

        返回:
            {"with_embedding": N, "total_documents": N, "total_photos": N}
            total_photos 是 Go 后端照片总数，供前端计算"待 Embed"使用。
            若 Go 后端不可达，返回 {"error": "..."}。
        """
        try:
            go_photos = self._fetch_all_photos()
        except Exception as e:
            logger.warning("EmbedQueue: 获取 Go 照片列表失败: %s", e)
            return {"error": f"获取 Go 照片列表失败: {e}"}

        go_ids = {p["id"] for p in go_photos}
        chroma_ids = self._store.get_embedded_photo_ids()

        # 有效嵌入 = Go 中存在且 Chroma 中有 embedding
        valid_embedded = go_ids & chroma_ids

        # 有效文档数 = Chroma 中属于有效 photo 的文档数（近似：chunks 按比例估算）
        # 直接遍历太慢，这里用 Chroma count 按比例折算
        total_chroma = self._store.count()
        total_chroma_ids = len(chroma_ids)
        if total_chroma_ids > 0:
            valid_docs_ratio = len(valid_embedded) / total_chroma_ids
            valid_documents = int(total_chroma * valid_docs_ratio)
        else:
            valid_documents = 0

        return {
            "with_embedding": len(valid_embedded),
            "total_documents": valid_documents,
            "total_photos": len(go_photos),
        }

    def cleanup_orphans(self) -> int:
        """
        清理 ChromaDB 中孤立文档（photo_id 在 Go 后端中已不存在的）。

        由 start() 自动调用，也可通过 API 手动触发。

        返回:
            删除的 photo_id 数量。
        """
        try:
            go_photos = self._fetch_all_photos()
        except Exception as e:
            logger.warning("EmbedQueue: 无法获取 Go 照片列表，跳过清理: %s", e)
            return 0

        valid_ids = {p["id"] for p in go_photos}
        return self._store.cleanup_orphans(valid_ids)

    # ------------------------------------------------------------------ #
    # Worker 逻辑
    # ------------------------------------------------------------------ #

    def _worker(self) -> None:
        """Worker 消费循环。从 pending 队列取任务并处理。"""
        while True:
            with self._lock:
                if not self._running:
                    return

            try:
                photo_id = self._pending.get(timeout=1.0)
            except queue.Empty:
                # 检查是否所有任务完成
                with self._lock:
                    if self._completed + self._failed >= self._total:
                        self._running = False
                if not self._running:
                    return
                continue

            self._process_one(photo_id)

    def _process_one(self, photo_id: str) -> None:
        """处理单张照片的 embedding。

        流程：Go API 获取照片 → chunk → embed → ChromaDB 写入。
        """
        try:
            # 1. 从 Go API 获取照片数据
            resp = self._http.get(f"{self._go_url}/api/v1/photos/{photo_id}")
            resp.raise_for_status()
            photo = resp.json()

            description = photo.get("description", "") or ""
            if not description.strip():
                logger.warning("EmbedQueue: photo %s has no description, skip", photo_id)
                self._inc_failed()
                return

            # 2. 设置当前文件名
            filename = photo.get("filename", photo_id)
            self._set_current(filename)

            # 3. 清理旧 Chroma 数据
            self._store.delete(where={"photo_id": photo_id})

            # 4. 分块
            chunks, metas = self._prepare_chunks(photo, description)
            if not chunks:
                logger.warning("EmbedQueue: photo %s no chunks produced", photo_id)
                self._inc_failed()
                return

            # 5. 分批 Embedding
            all_ids = [f"{photo_id}#{i}" for i in range(len(chunks))]
            vectors: list[list[float]] = []
            for j in range(0, len(chunks), BATCH_SIZE):
                chunk_batch = chunks[j : j + BATCH_SIZE]
                vecs = self._embedder.embed_texts(chunk_batch)
                vectors.extend(v.tolist() for v in vecs)

            # 6. 写入 Chroma
            self._store.add(
                ids=all_ids,
                documents=chunks,
                metadatas=metas,
                embeddings=vectors,
            )

            self._inc_completed()
            logger.info("EmbedQueue done: photo=%s, chunks=%d", photo_id, len(chunks))

        except Exception as e:
            logger.warning("EmbedQueue failed: photo=%s, err=%s", photo_id, e)
            self._inc_failed()
        finally:
            self._set_current("")

    # ------------------------------------------------------------------ #
    # 分块辅助（复用 AutoEmbed 的逻辑）
    # ------------------------------------------------------------------ #

    def _prepare_chunks(
        self, photo: dict, description: str
    ) -> tuple[list[str], list[dict]]:
        """
        对单张照片描述分片，返回 (chunks, metadatas)。

        metadata 仅保留 photo_id 和 chunk_index，结构化属性由 Go SQLite 统一管理，
        RAG 检索不做 ChromaDB where 过滤（详见 docs/chroma-metadata-design.md）。
        """
        strategy = self._cfg.chunk_strategy
        if strategy == "none":
            chunks = chunking.chunk_text(description, strategy=chunking.Strategy.NONE)
        elif strategy == "fixed_size":
            chunks = chunking.chunk_text(
                description,
                strategy=chunking.Strategy.FIXED_SIZE,
                chunk_size=self._cfg.chunk_size,
                chunk_overlap=self._cfg.chunk_overlap,
            )
        elif strategy == "markdown_heading":
            chunks = chunking.chunk_text(
                description,
                strategy=chunking.Strategy.MARKDOWN_HEADING,
                level=self._cfg.heading_level,
            )
        else:
            raise ValueError(f"未知的分块策略: {strategy}")

        photo_id = photo.get("id", "")
        metadatas: list[dict] = []
        for idx, _ in enumerate(chunks):
            metadatas.append({
                "photo_id": photo_id,
                "chunk_index": idx,
            })

        return chunks, metadatas

    # ------------------------------------------------------------------ #
    # Go API 交互
    # ------------------------------------------------------------------ #

    def _fetch_all_photos(self) -> list[dict]:
        """分页获取 Go 后端全部照片数据。"""
        all_photos: list[dict] = []
        page = 1
        while True:
            resp = self._http.get(
                f"{self._go_url}/api/v1/photos",
                params={"page": page, "page_size": 100},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            all_photos.extend(items)
            if page >= data.get("total_pages", 0):
                break
            page += 1
        return all_photos

    def _fetch_unembedded_ids(self) -> list[str]:
        """获取有描述但未嵌入的照片 ID 列表。"""
        photos = self._fetch_all_photos()
        embedded_ids = self._store.get_embedded_photo_ids()
        result = []
        for p in photos:
            desc = p.get("description", "") or ""
            if desc.strip() and p["id"] not in embedded_ids:
                result.append(p["id"])
        return result

    def _fetch_embeddable_ids(self) -> list[str]:
        """获取所有有描述的照片 ID 列表（force 模式使用）。"""
        photos = self._fetch_all_photos()
        return [p["id"] for p in photos if (p.get("description") or "").strip()]

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #

    def _inc_completed(self) -> None:
        with self._lock:
            self._completed += 1
            if self._completed + self._failed >= self._total:
                self._running = False
                logger.info(
                    "EmbedQueue completed: done=%d, failed=%d",
                    self._completed, self._failed,
                )

    def _inc_failed(self) -> None:
        with self._lock:
            self._failed += 1
            if self._completed + self._failed >= self._total:
                self._running = False

    def _set_current(self, filename: str) -> None:
        with self._lock:
            self._current = filename

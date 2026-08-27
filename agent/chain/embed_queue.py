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
from datetime import datetime, timezone

import utils.backend_sdk as bksdk
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
        self._embedder = embedder.Embedder(
            base_url=self._go_url,
            model=cfg.embedding_model,
        )

        # 连拍组封面集合（精细/模糊两档），封面描述与全量集合共用向量
        chroma_dir = str(cfg.resolve_path("./data/chroma"))
        self._group_stores = {
            "fine": chroma_client.ChromaPhotoStore(
                persist_dir=chroma_dir,
                collection_name=chroma_client.COLLECTION_BURST_FINE,
            ),
            "coarse": chroma_client.ChromaPhotoStore(
                persist_dir=chroma_dir,
                collection_name=chroma_client.COLLECTION_BURST_COARSE,
            ),
        }
        # 封面照片 ID -> [(profile, group_id, photo_count)]，启动批量嵌入时刷新
        self._cover_groups: dict[str, list[tuple[str, str, int]]] = {}

        self._running = False
        self._total = 0
        self._completed = 0
        self._failed = 0
        self._current = ""
        self._lock = threading.Lock()
        self._pending: queue.Queue[str] = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._processing: set[str] = set()
        self._batch_pending: set[str] = set()

    # ------------------------------------------------------------------ #
    # 公开接口
    # ------------------------------------------------------------------ #

    def start(self, force: bool = False) -> dict:
        """启动批量 embedding。

        启动前自动清理三个集合的孤立文档（全量按照片、组集合按组），
        构建封面映射并同步连拍组集合的差量（新增/封面变更的组）。

        参数:
            force: 为 True 时对所有有描述的照片重新 embedding（跳过已嵌入检查）。

        返回:
            {"status": "started", "total": N} 或 {"error": "..."}
        """
        with self._lock:
            if self._running:
                return {"error": "embed queue is already running"}

            # 启动前先清理孤立数据（全量集合 + 两个组集合）
            try:
                removed = self.cleanup_orphans()
                if removed > 0:
                    logger.info("EmbedQueue: 清理了 %d 个孤立 photo_id", removed)
            except Exception as e:
                logger.warning("EmbedQueue: 清理孤立数据失败（非致命）: %s", e)

            # 构建封面映射并同步组集合差量
            try:
                self._sync_group_collections()
            except Exception as e:
                logger.warning("EmbedQueue: 连拍组集合同步失败（非致命）: %s", e)

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

            # 过滤掉正在被单张处理的照片
            photo_ids = [pid for pid in photo_ids if pid not in self._processing]
            if not photo_ids:
                return {"status": "done", "total": 0, "message": "所有照片正在单张处理中"}

            # 记录批量待处理 ID，阻止单张请求冲突
            self._batch_pending = set(photo_ids)

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
            self._batch_pending.clear()

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
        """单张照片入队。队列未运行时自动启动。已在处理中则跳过。"""
        with self._lock:
            if photo_id in self._processing:
                return {"status": "already_processing", "photo_id": photo_id}
            if photo_id in self._batch_pending:
                return {"status": "in_batch_queue", "photo_id": photo_id}
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

    def processing_ids(self) -> list[str]:
        """返回当前正在处理的照片 ID 列表。"""
        with self._lock:
            return list(self._processing)

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

        go_ids = {p.id for p in go_photos}
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
        清理三个集合中的孤立文档：photo_id 在 Go 后端中已不存在的。

        全量集合与两个组集合都以 photo_id 作为 metadata，统一按同一份有效 ID
        清理即可；组被解散导致的组级残留由 _sync_group_collections 处理。

        由 start() 自动调用，也可通过 API 手动触发。

        返回:
            删除的 photo_id 数量（三个集合去重后的照片维度计数）。
        """
        try:
            go_photos = self._fetch_all_photos()
        except Exception as e:
            logger.warning("EmbedQueue: 无法获取 Go 照片列表，跳过清理: %s", e)
            return 0

        valid_ids = {p.id for p in go_photos}
        removed = self._store.cleanup_orphans(valid_ids)
        for profile, store in self._group_stores.items():
            n = store.cleanup_orphans(valid_ids)
            if n > 0:
                logger.info("EmbedQueue: %s 组集合清理了 %d 张已删除照片", profile, n)
        return removed

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
        with self._lock:
            self._processing.add(photo_id)
            self._batch_pending.discard(photo_id)
        try:
            # 1. 从 Go API 获取照片数据（通过 SDK）
            photo_api = bksdk.get_photo_api(self._go_url)
            resp = photo_api.photo_service_get_photo_detail(photo_id)
            photo = resp.photo

            health = bksdk.get_photo_health(self._go_url, photo_id)
            vlm_status = health.get("vlmStatus") or health.get("vlm_status")
            if vlm_status != "healthy":
                self._store.delete(where={"photo_id": photo_id})
                for group_store in self._group_stores.values():
                    group_store.delete(where={"photo_id": photo_id})
                logger.info("EmbedQueue: photo %s skipped, VLM status=%s", photo_id, vlm_status)
                self._inc_failed()
                return

            description = (photo and photo.description) or ""
            if not description.strip():
                logger.warning("EmbedQueue: photo %s has no description, skip", photo_id)
                self._inc_failed()
                return

            # 2. 设置当前文件名
            filename = photo.filename if photo and photo.filename else photo_id
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

            # 7. 封面照片：同一组向量写入对应连拍组集合（无需二次 Embedding）
            self._write_group_covers(photo_id, chunks, vectors)

            bksdk.update_photo_health(
                self._go_url,
                photo_id,
                "healthy",
                description_time=health.get("descriptionTime") or health.get("description_time") or "",
            )

            self._inc_completed()
            logger.info("EmbedQueue done: photo=%s, chunks=%d", photo_id, len(chunks))

        except Exception as e:
            logger.warning("EmbedQueue failed: photo=%s, err=%s", photo_id, e)
            try:
                bksdk.update_photo_health(self._go_url, photo_id, "failed", str(e))
            except Exception as update_error:
                logger.warning("EmbedQueue: 写回失败状态失败: photo=%s, err=%s", photo_id, update_error)
            self._inc_failed()
        finally:
            self._set_current("")
            with self._lock:
                self._processing.discard(photo_id)

    # ------------------------------------------------------------------ #
    # 连拍组集合同步
    # ------------------------------------------------------------------ #

    def sync_group_collections(self) -> dict:
        """对齐两个连拍组集合与 Go 库内当前分组结构，返回各档已入库组数。

        连拍组重建后调用即可更新组集合，无需重跑全量 Embedding：
        封面向量直接从全量集合复用。封面照片尚未嵌入的组会被跳过，
        待该照片嵌入时由 _write_group_covers 自动补上。
        """
        self._sync_group_collections()
        return {
            profile: len(store.get_embedded_group_ids())
            for profile, store in self._group_stores.items()
        }

    def _fetch_burst_groups(self) -> dict[str, dict[str, tuple[str, int]]]:
        """从 Go 后端拉取全部连拍组，按档位归类。

        直接读 photo_groups 表（一次请求拿到 id/封面/张数/档位），
        不走 SearchPhotos：后者按 burst_profile 查询返回的是全量照片，
        只在每条上附带组信息，拿组清单需要翻完整个照片库。

        返回:
            {"fine": {group_id: (cover_photo_id, photo_count)}, "coarse": {...}}
        """
        curd_api = bksdk.get_curd_api(self._go_url)
        resp = curd_api.default_curd_get_photo_group_list()
        groups: dict[str, dict[str, tuple[str, int]]] = {"fine": {}, "coarse": {}}
        for g in (resp.photo_group_list or []):
            profile = g.profile or "fine"
            gid = g.id or ""
            if not gid or profile not in groups:
                continue
            groups[profile][gid] = (g.cover_photo_id or "", int(g.photo_count or 0))
        return groups

    def _sync_group_collections(self) -> None:
        """同步两个连拍组集合与 Go 库内当前分组结构。

        - 清理组集合中已不存在的组（连拍组重建后旧组 ID 残留）
        - 构建封面映射 cover_photo_id -> [(profile, group_id, photo_count)]
        - 差量补嵌：组集合缺失或封面已变更的组，从全量集合取封面向量写入；
          全量集合也没有的（封面照片未嵌入），留给本次批量嵌入的照片处理流程补上
        """
        # Go 库内当前有效组，按档位收集 {group_id: (cover_photo_id, photo_count)}
        current_groups = self._fetch_burst_groups()

        # 清理组集合孤立数据 + 收集集合内现有组的封面
        embedded_covers: dict[str, dict[str, str]] = {}
        for profile, store in self._group_stores.items():
            valid_ids = set(current_groups[profile].keys())
            removed = store.cleanup_group_orphans(valid_ids)
            if removed > 0:
                logger.info("EmbedQueue: %s 组集合清理了 %d 个孤立组", profile, removed)
            embedded_covers[profile] = store.get_group_cover_photo_ids()

        # 差量补嵌：组在 Go 中存在但组集合缺失，或封面照片已更换
        for profile, store in self._group_stores.items():
            for gid, (cover_id, count) in current_groups[profile].items():
                if embedded_covers[profile].get(gid) == cover_id:
                    continue
                vectors, chunks = self._load_cover_vectors(cover_id)
                if vectors is None:
                    continue  # 封面照片未嵌入，批量嵌入该照片时自动写入
                store.add_group_cover(
                    gid, cover_id, count, chunks, vectors,
                    model=self._cfg.embedding_model,
                )

        # 重建封面映射（含本轮新补嵌的组），供照片嵌入流程双写组集合
        self._rebuild_cover_map(current_groups)

    def _rebuild_cover_map(
        self, current_groups: dict[str, dict[str, tuple[str, int]]],
    ) -> None:
        """重建 cover_photo_id -> [(profile, group_id, photo_count)] 映射。"""
        cover_map: dict[str, list[tuple[str, str, int]]] = {}
        for profile, groups in current_groups.items():
            for gid, (cover_id, count) in groups.items():
                cover_map.setdefault(cover_id, []).append((profile, gid, count))
        self._cover_groups = cover_map

    def _load_cover_vectors(
        self, photo_id: str,
    ) -> tuple[list[list[float]] | None, list[str]]:
        """从全量集合读取某照片的全部 chunk 向量与文本（按 chunk_index 排序）。

        照片未被嵌入时返回 (None, [])。
        """
        raw = self._store.collection.get(
            where={"photo_id": photo_id},
            include=["metadatas", "documents", "embeddings"],
        )
        metas = raw.get("metadatas") or []
        docs = raw.get("documents") or []
        # embeddings 是 numpy 二维数组，不能用 `or []` 兜底（数组真值判断会抛异常）
        embs = raw.get("embeddings")
        if embs is None or len(embs) == 0 or not metas:
            return None, []
        order = sorted(
            range(len(metas)),
            key=lambda i: (metas[i] or {}).get("chunk_index", 0),
        )
        # numpy float32 转回 Python float，与新生成向量的类型保持一致
        vectors = [[float(v) for v in embs[i]] for i in order]
        chunks = [docs[i] for i in order]
        if not vectors:
            return None, []
        return vectors, chunks

    def _write_group_covers(
        self, photo_id: str, chunks: list[str], vectors: list[list[float]],
    ) -> None:
        """照片嵌入完成后，若它是组封面则把向量写入对应组集合。"""
        for profile, gid, count in self._cover_groups.get(photo_id, []):
            store = self._group_stores.get(profile)
            if store is None:
                continue
            store.add_group_cover(
                gid, photo_id, count, chunks, vectors,
                model=self._cfg.embedding_model,
            )
            logger.info(
                "EmbedQueue: 封面 %s 写入 %s 组集合 group=%s", photo_id, profile, gid,
            )

    # ------------------------------------------------------------------ #
    # 分块辅助
    # ------------------------------------------------------------------ #

    def _prepare_chunks(
        self, photo, description: str
    ) -> tuple[list[str], list[dict]]:
        """
        对单张照片描述分片，返回 (chunks, metadatas)。

        metadata 保留两类信息：
        - 关联标识：photo_id + chunk_index（去重、清理孤立数据、chunk 排序）
        - 向量操作记录：model + embedded_at（向量生成时所用的模型与时间，属向量溯源信息，
          非图片结构化属性，图片结构化属性仍由 Go SQLite 统一管理）
        RAG 检索不做 ChromaDB where 过滤（详见 docs/design/2026-06-23-chroma-metadata-design.md）。
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

        photo_id = photo.id or ""
        # 向量操作记录：同一照片的多个 chunk 在同一次嵌入中生成，model 与时间一致
        embedded_at = datetime.now(timezone.utc).isoformat()
        model = self._cfg.embedding_model
        metadatas: list[dict] = []
        for idx, _ in enumerate(chunks):
            metadatas.append({
                "photo_id": photo_id,
                "chunk_index": idx,
                "model": model,
                "embedded_at": embedded_at,
            })

        return chunks, metadatas

    # ------------------------------------------------------------------ #
    # Go API 交互
    # ------------------------------------------------------------------ #

    def _fetch_all_photos(self):
        """分页获取 Go 后端全部照片数据（通过 SDK），返回 ApiPhotoItem 列表。"""
        photo_api = bksdk.get_photo_api(self._go_url)
        all_photos = []
        page = 1
        while True:
            resp = photo_api.photo_service_search_photos(page=page, page_size=100)
            items = resp.items or []
            all_photos.extend(items)
            total_pages = resp.total_pages or 0
            if page >= total_pages:
                break
            page += 1
        return all_photos

    def _fetch_unembedded_ids(self) -> list[str]:
        """获取有描述但未嵌入的照片 ID 列表。"""
        photos = self._fetch_all_photos()
        embedded_ids = self._store.get_embedded_photo_ids()
        result = []
        for p in photos:
            desc = p.description or ""
            if desc.strip() and p.id not in embedded_ids and self._is_vlm_healthy(p.id):
                result.append(p.id)
        return result

    def _fetch_embeddable_ids(self) -> list[str]:
        """获取所有有描述的照片 ID 列表（force 模式使用）。"""
        photos = self._fetch_all_photos()
        return [
            p.id for p in photos
            if (p.description or "").strip() and self._is_vlm_healthy(p.id)
        ]

    def _is_vlm_healthy(self, photo_id: str) -> bool:
        """Embedding 只接收通过 VLM 质量闸门的照片。"""
        try:
            health = bksdk.get_photo_health(self._go_url, photo_id)
            return (health.get("vlmStatus") or health.get("vlm_status")) == "healthy"
        except Exception as e:
            logger.warning("EmbedQueue: 获取照片健康状态失败: photo=%s, err=%s", photo_id, e)
            return False

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

"""
    AutoEmbed — 启动时自动同步 Go 后端数据到 Chroma 向量库。

    参考 Go 后端 AutoSync 模式（自动对比 description.json 与 SQLite 增量同步），
    在 Python Agent 启动时自动对比 Go API 照片数据与本地 Chroma，增量完成 Embedding。

    用法（由 photo_agent.py 自动调用）:
        from chain.auto_embed import AutoEmbed
        AutoEmbed(cfg).run()
"""

import hashlib
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import config as cfg_module
import embedding.chunking as chunking
import embedding.embedder as embedder
import vectorstore.chroma_client as chroma_client

BATCH_SIZE = 10  # embedding 每批文本数量
PHOTO_BATCH = 10  # 每批入库照片数量


class AutoEmbed:
    """启动时自动检测并同步 Chroma 向量库。"""

    def __init__(self, config: cfg_module.Config):
        self._cfg = config
        self._go_url = config.go_backend_url.rstrip("/")
        self._http = httpx.Client(timeout=30.0)
        self._manifest_path = config.resolve_path("./data/chroma/embed_manifest.json")

    # ------------------------------------------------------------------ #
    # 公开入口
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """主入口：检测 Go API 健康状态，对比 manifest，增量/全量同步。"""
        if not self._check_go_health():
            print("AutoEmbed: Go 后端未就绪，跳过（将使用现有 Chroma 数据）")
            return

        go_photos = self._fetch_all_photos()
        if not go_photos:
            print("AutoEmbed: Go 后端无照片数据，跳过")
            return

        go_hash = self._compute_hash(go_photos)
        local = self._load_local_manifest()

        if local and local.get("go_hash") == go_hash:
            print(f"AutoEmbed: Chroma 已是最新（{local.get('count', 0)} 张），跳过")
            return

        # 需要同步
        new_ids, del_ids = self._diff(local, go_photos)
        store = chroma_client.ChromaPhotoStore(
            persist_dir=str(self._cfg.resolve_path("./data/chroma")),
            collection_name="photos",
        )

        # 清理已删除的照片
        if del_ids:
            print(f"AutoEmbed: 清理 {len(del_ids)} 张已删除照片...")
            for pid in del_ids:
                store.delete(where={"photo_id": pid})

        # 增量或全量 Embedding
        if new_ids:
            total = len(new_ids)
            label = "增量" if local else "全量"
            print(f"AutoEmbed: {label}同步 {total} 张照片到 Chroma...")
            self._embed_photos(store, go_photos, new_ids, total)
        else:
            print("AutoEmbed: 无新增照片需要索引")

        # 保存 manifest
        self._save_manifest(go_photos, go_hash)
        print(f"AutoEmbed: Chroma 同步完成，共 {store.count()} 条文档")
        print()

    # ------------------------------------------------------------------ #
    # Go API 交互
    # ------------------------------------------------------------------ #

    def _check_go_health(self) -> bool:
        """检查 Go 后端是否就绪。"""
        try:
            resp = self._http.get(f"{self._go_url}/api/v1/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

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

    # ------------------------------------------------------------------ #
    # Manifest 管理
    # ------------------------------------------------------------------ #

    def _compute_hash(self, photos: list[dict]) -> str:
        """计算照片集 hash（基于 id + imported_at），用于增量检测。"""
        h = hashlib.sha256()
        for p in photos:
            h.update(p.get("id", "").encode())
            h.update(p.get("imported_at", "").encode())
        return h.hexdigest()

    def _load_local_manifest(self) -> dict | None:
        """加载本地 embed_manifest.json。"""
        if not self._manifest_path.exists():
            return None
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _save_manifest(self, photos: list[dict], go_hash: str) -> None:
        """保存本地 embed_manifest.json。"""
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "count": len(photos),
            "go_hash": go_hash,
            "embedded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with open(self._manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    def _diff(
        self, local: dict | None, go_photos: list[dict]
    ) -> tuple[list[dict], list[str]]:
        """
        对比本地 manifest 与 Go 数据，返回 (需新增的照片列表, 需删除的 photo_id 列表)。

        当 local 为 None（无 manifest）时，全部 Go 照片标记为新增。
        """
        if local is None:
            return go_photos, []

        local_ids = set(local.get("photos", {}).keys())
        go_ids = {p["id"] for p in go_photos}

        del_ids = list(local_ids - go_ids)

        # 基于 imported_at 判断新增/变更
        local_times = local.get("photos", {})
        new_photos: list[dict] = []
        for p in go_photos:
            pid = p["id"]
            if pid not in local_ids:
                new_photos.append(p)
            elif local_times.get(pid) != p.get("imported_at", ""):
                new_photos.append(p)

        return new_photos, del_ids

    # ------------------------------------------------------------------ #
    # Embedding 核心流程
    # ------------------------------------------------------------------ #

    def _embed_photos(
        self,
        store: chroma_client.ChromaPhotoStore,
        go_photos: list[dict],
        new_ids: list[dict],
        total: int,
    ) -> None:
        """分批完成 chunk → embed → Chroma 入库，显示进度条。"""
        emb = embedder.Embedder(
            base_url=self._cfg.go_backend_url,
            model=self._cfg.embedding_model,
        )

        # 建立 id → photo 映射
        photo_map = {p["id"]: p for p in go_photos}

        processed = 0
        for i in range(0, len(new_ids), PHOTO_BATCH):
            batch = new_ids[i : i + PHOTO_BATCH]

            # 清理旧数据（增量更新）
            for p in batch:
                store.delete(where={"photo_id": p["id"]})

            # 准备 chunks
            all_ids: list[str] = []
            all_chunks: list[str] = []
            all_metas: list[dict] = []

            for p in batch:
                photo = photo_map.get(p["id"], p)
                desc = photo.get("description", "") or ""
                if not desc.strip():
                    continue
                chunks, metas = self._prepare_chunks(photo, desc)
                for idx, (chunk, meta) in enumerate(zip(chunks, metas)):
                    all_ids.append(f"{photo['id']}#{idx}")
                    all_chunks.append(chunk)
                    all_metas.append(meta)

            if all_chunks:
                # 分批 Embedding
                vectors: list[list[float]] = []
                for j in range(0, len(all_chunks), BATCH_SIZE):
                    chunk_batch = all_chunks[j : j + BATCH_SIZE]
                    vecs = emb.embed_texts(chunk_batch)
                    vectors.extend(v.tolist() for v in vecs)

                store.add(
                    ids=all_ids,
                    documents=all_chunks,
                    metadatas=all_metas,
                    embeddings=vectors,
                )

            processed += len(batch)
            self._print_progress(processed, total)

        # 最终换行
        print()

    def _prepare_chunks(self, photo: dict, description: str) -> tuple[list[str], list[dict]]:
        """
        对单张照片描述分片，返回 (chunks, metadatas)。

        复用 chunking 模块的分片逻辑，metadata 包含 6 个结构化属性字段。
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

        file_path = photo.get("file_path", "")
        shot_at = photo.get("shot_at", "")
        if shot_at:
            # shot_at 可能是 ISO 格式字符串
            shot_at = str(shot_at)

        metadatas: list[dict] = []
        for idx, _ in enumerate(chunks):
            meta: dict = {
                "photo_id": photo.get("id", ""),
                "file_path": f"/photos/{file_path}" if file_path else "",
                "chunk_index": idx,
            }
            if shot_at:
                meta["shot_at"] = shot_at
            # 结构化属性写入 metadata，支持 Chroma where 过滤
            for key in ("objects", "colors", "scene", "lighting", "mood", "composition"):
                val = photo.get(key)
                if val:
                    meta[key] = val
            metadatas.append(meta)

        return chunks, metadatas

    @staticmethod
    def _print_progress(current: int, total: int) -> None:
        """打印简单进度条（不依赖 tqdm，避免额外依赖）。"""
        pct = current / total if total > 0 else 0
        bar_len = 30
        filled = int(bar_len * pct)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r  Embedding: [{bar}] {current}/{total} ({pct*100:.0f}%)", end="")
        if current >= total:
            print()  # 换行

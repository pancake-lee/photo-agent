"""
    阶段六：照片描述批量入库脚本（支持增量索引）。

    从 data/descriptions.json 读取所有照片描述，分块生成 Embedding，
    批量写入 Chroma 向量库。

    增量索引机制：
        - 维护 index_manifest.json，记录每张照片的描述 hash 和分块策略
        - 内容未变更的照片跳过处理，避免浪费 Embedding Token
        - descriptions.json 中删除的照片，同步从 Chroma 中清理

    用法:
        cd agent
        python scripts/index_photos.py -c /path/to/config.yaml

    分块策略:
        - 短描述（<=500 字）整块存储
        - 长描述按字数分片（500 字/片，重叠 50 字）

    Metadata:
        - photo_id:  照片文件名（如 DSC_0009.JPG）
        - file_path: 照片完整路径（由 photo_id 推导）
        - chunk_index: 分片序号（整块为 0）
"""

import hashlib
import json
import sys
import pathlib
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import numpy as np

import config
import embedding.chunking as chunking
import embedding.embedder as embedder
import vectorstore.chroma_client as chroma_client


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

CHUNK_MAX_CHARS = 500
CHUNK_OVERLAP = 50
BATCH_SIZE = 16


def _strategy_label() -> str:
    """返回当前分块策略的标识字符串，用于 manifest 对比。"""
    return f"chars:{CHUNK_MAX_CHARS}:{CHUNK_OVERLAP}"


def _content_hash(text: str) -> str:
    """计算文本的 SHA256 hash，作为内容指纹。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Manifest 管理
# --------------------------------------------------------------------------- #

def _load_manifest(manifest_path: pathlib.Path) -> dict:
    """加载 manifest 文件，不存在则返回空字典。"""
    if not manifest_path.exists():
        return {}
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(manifest_path: pathlib.Path, data: dict) -> None:
    """保存 manifest 到磁盘。"""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# 分块
# --------------------------------------------------------------------------- #

def _prepare_chunks(photo_id: str, description: str) -> tuple[list[str], list[dict]]:
    """
    对单条照片描述进行分片，返回 chunk 文本列表和对应的 metadata 列表。

    参数:
        photo_id:    照片文件名
        description: 照片描述文本

    返回:
        (chunks, metadatas) 两个等长列表
    """
    text = description.strip()
    if not text:
        return [], []

    if len(text) <= CHUNK_MAX_CHARS:
        chunks = chunking.chunk_text(text, strategy=chunking.Strategy.NONE)
    else:
        chunks = chunking.chunk_text(
            text,
            strategy=chunking.Strategy.CHARS,
            max_chars=CHUNK_MAX_CHARS,
            overlap=CHUNK_OVERLAP,
        )

    metadatas = []
    for idx, chunk in enumerate(chunks):
        metadatas.append({
            "photo_id": photo_id,
            "file_path": f"/photos/{photo_id}",
            "chunk_index": idx,
        })

    return chunks, metadatas


# --------------------------------------------------------------------------- #
# Embedding
# --------------------------------------------------------------------------- #

def _batch_embed(
    embedder_instance: embedder.Embedder,
    chunks: list[str],
    batch_size: int = BATCH_SIZE,
) -> list[np.ndarray]:
    """
    分批调用 Embedding 接口，避免单请求过大。

    参数:
        embedder_instance: embedder.Embedder 实例
        chunks:     待编码文本列表
        batch_size: 每批数量

    返回:
        与输入顺序一致的向量列表
    """
    all_vectors: list[np.ndarray] = []

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        vectors = embedder_instance.embed_texts(batch)
        all_vectors.extend(vectors)

        print(f"  ✅ 已编码 {min(i + batch_size, len(chunks))}/{len(chunks)} 条")

    return all_vectors


def _vectors_to_list(vectors: list[np.ndarray]) -> list[list[float]]:
    """将 numpy 数组列表转换为 Python 原生 float 列表。"""
    return [v.tolist() for v in vectors]


# --------------------------------------------------------------------------- #
# 增量索引核心逻辑
# --------------------------------------------------------------------------- #

def _classify_photos(
    data: dict,
    manifest: dict,
) -> tuple[list[str], list[str], list[str]]:
    """
    将照片分为三类：跳过、待处理、已删除。

    参数:
        data:     descriptions.json 的内容
        manifest: 当前 manifest

    返回:
        (skip_ids, update_ids, deleted_ids)
        - skip_ids:    内容未变更，跳过处理
        - update_ids:  新增或内容变更，需要重新索引
        - deleted_ids: manifest 中有但 data 中已消失，需要清理
    """
    current_strategy = _strategy_label()
    skip_ids: list[str] = []
    update_ids: list[str] = []

    for photo_id, info in data.items():
        description = info.get("description", "") if isinstance(info, dict) else str(info)
        text_hash = _content_hash(description)
        record = manifest.get(photo_id)

        if (
            record
            and record.get("hash") == text_hash
            and record.get("strategy") == current_strategy
        ):
            skip_ids.append(photo_id)
        else:
            update_ids.append(photo_id)

    data_ids = set(data.keys())
    deleted_ids = [pid for pid in manifest if pid not in data_ids]

    return skip_ids, update_ids, deleted_ids


def _index_photos(
    store: chroma_client.ChromaPhotoStore,
    embedder_instance: embedder.Embedder,
    data: dict,
    photo_ids: list[str],
) -> dict:
    """
    对指定照片列表执行索引：分块 → Embedding → 入库。

    返回:
        更新后的 manifest 记录字典，key 为 photo_id
    """
    all_chunks: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []
    photo_id_to_chunk_count: dict[str, int] = {}

    for photo_id in photo_ids:
        info = data[photo_id]
        description = info.get("description", "") if isinstance(info, dict) else str(info)
        chunks, metadatas = _prepare_chunks(photo_id, description)
        photo_id_to_chunk_count[photo_id] = len(chunks)

        for idx, chunk in enumerate(chunks):
            chunk_id = f"{photo_id}#{idx}"
            all_ids.append(chunk_id)
            all_chunks.append(chunk)
            all_metadatas.append(metadatas[idx])

    if all_chunks:
        print(f"🔮 生成 Embedding（共 {len(all_chunks)} 个 chunk，批量大小: {BATCH_SIZE}）...")
        vectors = _batch_embed(embedder_instance, all_chunks, batch_size=BATCH_SIZE)
        print()

        print("💾 写入 Chroma...")
        store.add(
            ids=all_ids,
            documents=all_chunks,
            metadatas=all_metadatas,
            embeddings=_vectors_to_list(vectors),
        )
        print()

    now = datetime.now(timezone.utc).isoformat()
    new_records = {}
    for photo_id in photo_ids:
        info = data[photo_id]
        description = info.get("description", "") if isinstance(info, dict) else str(info)
        new_records[photo_id] = {
            "hash": _content_hash(description),
            "chunk_count": photo_id_to_chunk_count[photo_id],
            "indexed_at": now,
            "strategy": _strategy_label(),
        }

    return new_records


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def main() -> None:
    """主流程：增量索引。"""
    cfg = config.load_config()

    descriptions_path = cfg.resolve_path(cfg.descriptions_path)
    print(f"📖 读取描述文件: {descriptions_path}")

    with open(descriptions_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_photos = len(data)
    print(f"📸 共 {total_photos} 张照片")
    print()

    persist_dir = cfg.resolve_path("./data/chroma")
    manifest_path = persist_dir / "index_manifest.json"
    manifest = _load_manifest(manifest_path)

    skip_ids, update_ids, deleted_ids = _classify_photos(data, manifest)

    print(f"⏭️  跳过（未变更）: {len(skip_ids)} 张")
    print(f"🔄 待处理（新增/变更）: {len(update_ids)} 张")
    print(f"🗑️  待清理（已删除）: {len(deleted_ids)} 张")
    print()

    store = chroma_client.ChromaPhotoStore(
        persist_dir=str(persist_dir),
        collection_name="photos",
    )

    embedder_instance = embedder.Embedder(
        base_url=cfg.go_backend_url,
        model=cfg.embedding_model,
    )

    # 1. 清理已删除的照片
    if deleted_ids:
        print("🗑️  清理已删除的照片...")
        for photo_id in deleted_ids:
            store.delete(where={"photo_id": photo_id})
            manifest.pop(photo_id, None)
            print(f"  ✅ 已删除: {photo_id}")
        print()

    # 2. 删除需要更新的照片的旧 chunk
    if update_ids:
        print("🧹 删除旧 chunk（内容变更需重新索引）...")
        for photo_id in update_ids:
            if photo_id in manifest:
                store.delete(where={"photo_id": photo_id})
                print(f"  ✅ 已清理旧数据: {photo_id}")
        print()

    # 3. 重新索引待处理的照片
    if update_ids:
        print(f"🔪 分片处理（{len(update_ids)} 张照片）...")
        new_records = _index_photos(store, embedder_instance, data, update_ids)
        manifest.update(new_records)

    # 4. 保存 manifest
    _save_manifest(manifest_path, manifest)

    total_count = store.count()
    print(f"✅ 索引完成！Chroma 集合文档数: {total_count}")
    print()

    print("📋 确认入库内容（抽样第 1 条）:")
    first = store.peek(n=1)
    if first:
        item = first[0]
        meta = item.get("metadata", {})
        doc = item.get("document") or ""
        print(f"  ID        : {item['id']}")
        print(f"  Photo     : {meta.get('photo_id')}")
        print(f"  Chunk     : {meta.get('chunk_index')}")
        print(f"  FilePath  : {meta.get('file_path')}")
        print(f"  Content   : {doc[:200]}{'...' if len(doc) > 200 else ''}")
    print()

    print("📋 抽样查看（前 3 条）:")
    for item in store.peek(n=3):
        meta = item.get("metadata", {})
        doc_preview = (item.get("document") or "")[:60]
        print(f"  ID: {item['id']}")
        print(f"  Photo: {meta.get('photo_id')} | Chunk: {meta.get('chunk_index')}")
        print(f"  Doc: {doc_preview}...")
        print("-" * 50)


if __name__ == "__main__":
    main()

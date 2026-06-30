#!/usr/bin/env python3
"""
    batch_embed — 批量照片 Embedding CLI 工具。

    从 Go 后端获取有 VLM 描述的照片，生成 Embedding 向量并写入 ChromaDB。

    用法:
        cd agent
        .venv/bin/python scripts/batch_embed.py -c config.yaml
        .venv/bin/python scripts/batch_embed.py -c config.yaml --dry-run
        .venv/bin/python scripts/batch_embed.py -c config.yaml --force -n 10
        .venv/bin/python scripts/batch_embed.py -c config.yaml --go-url http://localhost:8080

    flag 风格对齐 batch_vlm：
        -c/--config     配置文件路径（必需）
        --go-url        Go 后端地址（默认从配置读取）
        -n/--limit      最大处理数（0=不限制）
        --force         强制重新 embedding
        --dry-run       仅显示将要处理的照片数，不实际执行
        --concurrency   并发数（默认 3）
"""

import argparse
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import utils.http_client as http_utils

import config as cfg_module
import embedding.chunking as chunking
import embedding.embedder as embedder_mod
import vectorstore.chroma_client as chroma_client

BATCH_SIZE = 10  # embedding 每批文本数量


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="批量照片 Embedding CLI — 从 Go 后端获取照片描述，生成向量写入 ChromaDB",
    )
    p.add_argument("-c", "--config", required=True, help="Agent 配置文件路径（必需）")
    p.add_argument("--go-url", default="", help="Go 后端地址（默认从配置读取 go_backend_url）")
    p.add_argument("-n", "--limit", type=int, default=0, help="最大处理数，0=不限制")
    p.add_argument("--force", action="store_true", help="强制重新 embedding（跳过已嵌入检查）")
    p.add_argument("--dry-run", action="store_true", help="仅显示将要处理的照片数，不实际执行")
    p.add_argument("--concurrency", type=int, default=3, help="并发数（默认 3）")
    return p


def fetch_all_photos(http: httpx.Client, go_url: str) -> list[dict]:
    """分页获取 Go 后端全部照片数据。"""
    all_photos: list[dict] = []
    page = 1
    while True:
        resp = http.get(
            f"{go_url}/api/v1/photos",
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


def prepare_chunks(photo: dict, description: str, cfg: cfg_module.Config) -> tuple[list[str], list[dict]]:
    """
    对单张照片描述分片，返回 (chunks, metadatas)。

    metadata 仅保留 photo_id 和 chunk_index，结构化属性由 Go SQLite 统一管理。
    """
    strategy = cfg.chunk_strategy
    if strategy == "none":
        chunks = chunking.chunk_text(description, strategy=chunking.Strategy.NONE)
    elif strategy == "fixed_size":
        chunks = chunking.chunk_text(
            description,
            strategy=chunking.Strategy.FIXED_SIZE,
            chunk_size=cfg.chunk_size,
            chunk_overlap=cfg.chunk_overlap,
        )
    elif strategy == "markdown_heading":
        chunks = chunking.chunk_text(
            description,
            strategy=chunking.Strategy.MARKDOWN_HEADING,
            level=cfg.heading_level,
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


def embed_one_photo(
    photo_id: str,
    http: httpx.Client,
    go_url: str,
    cfg: cfg_module.Config,
    store: chroma_client.ChromaPhotoStore,
    embedder_inst: embedder_mod.Embedder,
) -> tuple[bool, str]:
    """
    嵌入单张照片。返回 (success, filename_or_error)。
    """
    try:
        # 获取照片数据
        resp = http.get(f"{go_url}/api/v1/photos/{photo_id}")
        resp.raise_for_status()
        photo = resp.json()

        description = photo.get("description", "") or ""
        if not description.strip():
            return False, photo.get("filename", photo_id)

        filename = photo.get("filename", photo_id)

        # 清理旧数据
        store.delete(where={"photo_id": photo_id})

        # 分块
        chunks, metas = prepare_chunks(photo, description, cfg)
        if not chunks:
            return False, filename

        # 分批 Embedding
        all_ids = [f"{photo_id}#{i}" for i in range(len(chunks))]
        vectors: list[list[float]] = []
        for j in range(0, len(chunks), BATCH_SIZE):
            chunk_batch = chunks[j : j + BATCH_SIZE]
            vecs = embedder_inst.embed_texts(chunk_batch)
            vectors.extend(v.tolist() for v in vecs)

        # 写入 Chroma
        store.add(
            ids=all_ids,
            documents=chunks,
            metadatas=metas,
            embeddings=vectors,
        )

        return True, filename

    except Exception as e:
        return False, str(e)


def print_progress(current: int, total: int) -> None:
    """打印简单进度条（不依赖 tqdm）。"""
    pct = current / total if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * pct)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] {current}/{total} ({pct*100:.0f}%)", end="")
    if current >= total:
        print()


def main() -> None:
    args = build_parser().parse_args()

    # 加载配置
    cfg = cfg_module.Config(args.config)
    go_url = (args.go_url or cfg.go_backend_url).rstrip("/")

    print(f"Go Backend: {go_url}")
    print(f"Embedding Model: {cfg.embedding_model}")
    print()

    http = http_utils.create_client(timeout=30.0)

    # 获取全部照片
    print("正在获取照片列表...")
    all_photos = fetch_all_photos(http, go_url)
    print(f"Go 后端共有 {len(all_photos)} 张照片")

    # 仅保留有描述的照片
    described = [p for p in all_photos if (p.get("description") or "").strip()]
    print(f"其中 {len(described)} 张有 VLM 描述")
    if not described:
        print("没有可 embedding 的照片（需要先运行 VLM 描述），退出")
        return

    # 检查已嵌入状态
    store = chroma_client.ChromaPhotoStore(
        persist_dir=str(cfg.resolve_path("./data/chroma")),
        collection_name="photos",
    )
    embedded_ids = store.get_embedded_photo_ids()
    print(f"已嵌入: {len(embedded_ids)} 张")

    # 过滤
    if args.force:
        targets = described
        print("Force 模式: 将重新 embedding 所有有描述的照片")
    else:
        targets = [p for p in described if p["id"] not in embedded_ids]

    if args.limit > 0 and len(targets) > args.limit:
        targets = targets[:args.limit]
        print(f"限制 -n {args.limit}: 实际处理 {len(targets)} 张")

    print(f"待处理: {len(targets)} 张")
    print()

    if args.dry_run:
        print("--dry-run 模式，不实际执行")
        return

    if not targets:
        print("没有需要 embedding 的照片")
        return

    # 初始化 Embedder（全流程共用）
    embedder_inst = embedder_mod.Embedder(
        base_url=go_url,
        model=cfg.embedding_model,
    )

    # 并发处理
    concurrency = args.concurrency
    print(f"开始处理，并发数: {concurrency}")
    print()

    start_time = time.time()
    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(
                embed_one_photo,
                p["id"],
                http,
                go_url,
                cfg,
                store,
                embedder_inst,
            ): (i, p)
            for i, p in enumerate(targets)
        }

        for future in as_completed(futures):
            idx, photo = futures[future]
            try:
                ok, info = future.result()
            except Exception as e:
                ok, info = False, str(e)

            if ok:
                success += 1
            else:
                failed += 1

            total_processed = success + failed
            status = "OK" if ok else "FAIL"
            print(f"[{total_processed}/{len(targets)}] {status}: {info}")
            print_progress(total_processed, len(targets))

    elapsed = time.time() - start_time
    print()
    print(f"Batch Embed done: success={success}, failed={failed}, total={len(targets)}, "
          f"elapsed={elapsed:.1f}s")
    print(f"Token 用量: {embedder_inst.total_tokens}")
    print()


if __name__ == "__main__":
    main()

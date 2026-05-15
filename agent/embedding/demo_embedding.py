"""
    Embedding 演示脚本 —— 阶段四初版。

    从 descriptions.json 中取头尾两条照片描述，
    经过分片处理后调用 Embedding API，输出向量维度和示例值。

    用法：
        venv/bin/python embedding/demo_embedding.py -c ../.local/my-config.yaml
"""

import sys
import pathlib
import json

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import config
import embedding.chunking as chunking
import embedding.embedder as embedder


def load_descriptions(descriptions_path: str) -> dict[str, dict]:
    """加载 descriptions.json 文件。"""
    path = pathlib.Path(descriptions_path)
    if not path.exists():
        raise FileNotFoundError(f"描述文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_head_tail(data: dict, count: int = 1) -> list[tuple[str, dict]]:
    """
    从字典中取头部和尾部各 count 条数据。

    返回列表元素为 (文件名, 数据字典) 的元组。
    """
    keys = list(data.keys())
    selected_keys = keys[:count] + keys[-count:]
    return [(k, data[k]) for k in selected_keys]


def describe_photo(item: dict) -> str:
    """
    从照片数据中提取用于 embedding 的文本描述。

    当前仅支持 description 字段（字符串），后续可扩展为
    处理多种文本结构（如 keywords、tags 列表等）。
    """
    raw = item.get("description", "")
    if isinstance(raw, str):
        return raw
    # TODO: 处理其他结构（如 list、dict）
    return str(raw)


def main(cfg: config.Config) -> None:
    """主流程：加载数据 → 分片 → Embedding → 输出结果。"""

    # 1. 加载 descriptions.json
    descriptions_path = str(cfg.resolve_path(cfg.descriptions_path))
    descriptions = load_descriptions(descriptions_path)
    print(f"📂 加载描述文件: {cfg.descriptions_path}")
    print(f"   总照片数: {len(descriptions)}")
    print()

    # 2. 取头尾各 1 条（共 2 条）
    samples = pick_head_tail(descriptions, count=1)
    print(f"📝 选取样本数: {len(samples)}（头部 1 条 + 尾部 1 条）")
    print()

    # 3. 初始化 Embedder（通过 go-server 代理）
    embedder_instance = embedder.Embedder(
        base_url=cfg.go_backend_url,
        model=cfg.embedding_model,
    )
    print(f"🤖 Embedding 模型: {cfg.embedding_model}")
    print(f"   代理地址: {cfg.go_backend_url}/v1/embeddings")
    print()

    # 4. 逐条处理：提取文本 → 分片 → Embedding
    all_chunks: list[tuple[str, str]] = []  # (文件名, 分片文本)
    chunk_counts: list[int] = []

    for filename, item in samples:
        text = describe_photo(item)
        text_len = len(text)
        print(f"  📷 {filename}")
        print(f"     原始文本长度: {text_len} 字符")

        # 分片
        chunks = chunking.chunk_text(
            text, strategy=chunking.Strategy.CHARS, max_chars=500, overlap=50
        )
        chunk_counts.append(len(chunks))
        print(f"     分片数量: {len(chunks)}")

        for idx, chunk in enumerate(chunks):
            print(f"       片段[{idx}]: {chunk[:60]}...")
            all_chunks.append((filename, chunk))

        print()

    # 5. 批量 Embedding
    print("🔄 正在调用 Embedding API...")
    texts_to_embed = [chunk for _, chunk in all_chunks]
    vectors = embedder_instance.embed_texts(texts_to_embed)
    print(f"✅ 完成！共生成 {len(vectors)} 个向量")
    print()

    # 6. 输出结果
    print("📊 结果概览")
    print("-" * 40)

    vec_idx = 0
    for (filename, item), count in zip(samples, chunk_counts):
        print(f"  📷 {filename}")
        for i in range(count):
            vec = vectors[vec_idx]
            vec_idx += 1
            print(f"     向量[{i}] 维度: {vec.shape[0]}, 前5个值: {vec[:5].tolist()}")
        print()


if __name__ == "__main__":
    cfg = config.load_config()
    main(cfg)

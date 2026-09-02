"""一次性清理历史 NEF 照片记录与其向量；不会删除任何原始 .nef 文件。

默认仅输出将要删除的数量。确认无误后，显式传 --apply 才会写入 SQLite 和 Chroma。
运行示例：
    cd agent && uv run python cli/cleanup_nef_records.py -c ../.local/my-config.yaml
    cd agent && uv run python cli/cleanup_nef_records.py -c ../.local/my-config.yaml --apply
"""

import argparse
import pathlib
import sqlite3
import sys
import typing

import yaml


COLLECTION_NAMES = ("photos", "photos_burst_fine", "photos_burst_coarse")


def load_paths(config_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """从项目配置读取后端 SQLite 和 Agent Chroma 路径，不加载任何模型配置。"""
    with config_path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    project_root = pathlib.Path(config["Storage"]["ProjectRoot"])
    database = pathlib.Path(config["Sqlite"]["Path"])
    agent_data = pathlib.Path(config["Agent"]["DataDir"])
    if not database.is_absolute():
        database = project_root / database
    if not agent_data.is_absolute():
        agent_data = project_root / agent_data
    return database.resolve(), (agent_data / "chroma").resolve()


def find_nef_records(db_path: pathlib.Path) -> list[dict[str, str]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, filename FROM photos WHERE LOWER(COALESCE(file_type, '')) = 'nef' ORDER BY filename"
        ).fetchall()
    return [{"id": row["id"], "filename": row["filename"]} for row in rows]


def delete_database_records(db_path: pathlib.Path, photo_ids: list[str]) -> None:
    """以一个事务清除照片行和直接依赖的 AI 处理历史。"""
    if not photo_ids:
        return
    placeholders = ",".join("?" for _ in photo_ids)
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "ai_processing_history" in tables:
            conn.execute(f"DELETE FROM ai_processing_history WHERE photo_id IN ({placeholders})", photo_ids)
        conn.execute(f"DELETE FROM photos WHERE id IN ({placeholders})", photo_ids)


def _collection_names(client: typing.Any) -> set[str]:
    collections = client.list_collections()
    return {item if isinstance(item, str) else item.name for item in collections}


def chroma_document_counts(chroma_dir: pathlib.Path, photo_ids: list[str]) -> dict[str, int]:
    """统计三个检索集合中由这些照片产生的向量文档数。"""
    if not photo_ids or not chroma_dir.exists():
        return {name: 0 for name in COLLECTION_NAMES}
    from infra import chroma_client

    client = chroma_client.chromadb.PersistentClient(path=str(chroma_dir))
    available = _collection_names(client)
    counts: dict[str, int] = {}
    for name in COLLECTION_NAMES:
        if name not in available:
            counts[name] = 0
            continue
        collection = client.get_collection(name=name)
        counts[name] = sum(len(collection.get(where={"photo_id": photo_id}, include=[]).get("ids", [])) for photo_id in photo_ids)
    return counts


def delete_chroma_documents(chroma_dir: pathlib.Path, photo_ids: list[str]) -> None:
    if not photo_ids or not chroma_dir.exists():
        return
    from infra import chroma_client

    client = chroma_client.chromadb.PersistentClient(path=str(chroma_dir))
    available = _collection_names(client)
    for name in COLLECTION_NAMES:
        if name not in available:
            continue
        collection = client.get_collection(name=name)
        for photo_id in photo_ids:
            collection.delete(where={"photo_id": photo_id})


def parse_args() -> argparse.Namespace:
    project_root = pathlib.Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="清理历史 NEF 数据库/向量记录（默认 dry-run）")
    parser.add_argument("-c", "--config", type=pathlib.Path, default=project_root / ".local" / "my-config.yaml")
    parser.add_argument("--db-path", type=pathlib.Path, help="覆盖配置中的 SQLite 路径")
    parser.add_argument("--chroma-dir", type=pathlib.Path, help="覆盖配置中的 Chroma 目录")
    parser.add_argument("--apply", action="store_true", help="确认执行删除；未提供时只预览")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path, chroma_dir = load_paths(args.config)
    db_path = args.db_path.resolve() if args.db_path else db_path
    chroma_dir = args.chroma_dir.resolve() if args.chroma_dir else chroma_dir
    records = find_nef_records(db_path)
    photo_ids = [record["id"] for record in records]
    vector_counts = chroma_document_counts(chroma_dir, photo_ids)

    print(f"NEF 照片记录：{len(records)}")
    for record in records:
        print(f"  - {record['id']}  {record['filename']}")
    print("待清理向量：" + "，".join(f"{name}={count}" for name, count in vector_counts.items()))
    print("原始 .nef 文件：不会删除")
    if not args.apply:
        print("dry-run 完成；确认后加 --apply 执行。")
        return 0

    delete_chroma_documents(chroma_dir, photo_ids)
    delete_database_records(db_path, photo_ids)
    print("已清理历史 NEF 数据库记录和向量文档；原始 .nef 文件未改动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

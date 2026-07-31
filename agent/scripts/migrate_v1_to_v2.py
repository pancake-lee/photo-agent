"""一次性迁移脚本：将 suggest_history.json (v1) 全部记录转为 v2 格式并合并到 suggest_history_v2.json。

用法：cd agent && .venv/bin/python3 migrate_v1_to_v2.py
"""

import json
import pathlib
import sys
import traceback

# 将 agent 目录加入 sys.path 以导入 chain 模块
AGENT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_DIR))

from chain.trace_replay import replay_trace

PROJECT_ROOT = AGENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
V1_PATH = DATA_DIR / "suggest_history.json"
V2_PATH = DATA_DIR / "suggest_history_v2.json"
V1_BAK_PATH = DATA_DIR / "suggest_history.json.bak"


def migrate_one(v1_item: dict) -> dict | None:
    """将单条 v1 记录迁移为 v2 格式。逻辑与 server.py _migrate_to_v2 一致。"""
    v2_id = v1_item.get("id", "")
    if not v2_id:
        print(f"  ⚠ 跳过：缺少 id 字段")
        return None

    trace_id = v1_item.get("trace_id", "")

    # 尝试从 trace 重建步骤
    steps: list[dict] = []
    trace_expired = True
    if trace_id:
        try:
            replayed, expired = replay_trace(str(PROJECT_ROOT), trace_id)
            trace_expired = expired
            if not expired:
                steps = [
                    {
                        "event": s.event,
                        "label": s.label,
                        "group": s.group,
                        "stage": s.stage,
                        "timestamp": s.timestamp,
                        "data": s.data,
                        "payload_content": s.payload_content,
                        "payload_ref": s.payload_ref,
                    }
                    for s in replayed
                ]
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            print(f"    trace 重放失败 ({type(e).__name__}: {e})")
            trace_expired = True

    v0_version = {
        "version_id": f"{v2_id}-v0",
        "parent_version_id": None,
        "created_at": v1_item.get("generated_at", ""),
        "created_from": "auto",
        "modified_step": None,
        "trace_id": trace_id,
        "trace_expired": trace_expired,
        "steps": steps,
    }

    return {
        "id": v2_id,
        "generated_at": v1_item.get("generated_at", ""),
        "pipeline": v1_item.get("pipeline", ""),
        "total_photos": v1_item.get("total_photos", 0),
        "cluster_count": v1_item.get("cluster_count", 0),
        "rating": v1_item.get("rating", 0),
        "title": v1_item.get("title", ""),
        "angle": v1_item.get("angle", ""),
        "rationale": v1_item.get("rationale", ""),
        "category": v1_item.get("category", ""),
        "photo_ids": v1_item.get("photo_ids", []),
        "photo_sequence": v1_item.get("photo_sequence", []),
        "intuition_source": v1_item.get("intuition_source", []),
        "error": v1_item.get("error", ""),
        "versions": [v0_version],
        "current_version_id": f"{v2_id}-v0",
    }


def main():
    # 1. 读取 v1
    if not V1_PATH.exists():
        print(f"❌ v1 文件不存在: {V1_PATH}")
        sys.exit(1)

    with open(V1_PATH, "r", encoding="utf-8") as f:
        v1_data = json.load(f)
    print(f"📖 v1: {len(v1_data)} 条记录")

    # 2. 读取现有 v2（可能已有部分记录）
    existing_ids: set[str] = set()
    if V2_PATH.exists():
        with open(V2_PATH, "r", encoding="utf-8") as f:
            v2_data = json.load(f)
        existing_ids = {item["id"] for item in v2_data}
        print(f"📖 v2: {len(v2_data)} 条记录（已有 {len(existing_ids)} 个 id）")
    else:
        v2_data = []
        print("📖 v2: 文件不存在，从零创建")

    # 3. 逐条迁移
    migrated = 0
    skipped = 0
    for i, v1_item in enumerate(v1_data):
        vid = v1_item.get("id", "?")
        title = v1_item.get("title", "?")
        trace_id = v1_item.get("trace_id", "")

        if vid in existing_ids:
            print(f"  [{i}] ✅ 已存在: \"{title}\" (id={vid})")
            skipped += 1
            continue

        try:
            v2_item = migrate_one(v1_item)
            if v2_item is None:
                skipped += 1
                continue
        except Exception as e:
            print(f"  [{i}] ❌ 迁移失败: \"{title}\" (id={vid}) — {e}")
            traceback.print_exc()
            skipped += 1
            continue

        v2_data.append(v2_item)
        existing_ids.add(vid)
        trace_status = "✅ trace" if (trace_id and not v2_item["versions"][0]["trace_expired"]) else "⏳ 无/过期"
        step_count = len(v2_item["versions"][0]["steps"])
        print(f"  [{i}] ➕ 已迁移: \"{title}\" (id={vid}) {trace_status} steps={step_count}")
        migrated += 1

    # 4. 按 generated_at 倒序排列
    v2_data.sort(key=lambda x: x.get("generated_at", ""), reverse=True)

    # 5. 备份 v1 → v2 写入
    V1_PATH.rename(V1_BAK_PATH)
    print(f"\n💾 v1 已备份: {V1_BAK_PATH}")

    with open(V2_PATH, "w", encoding="utf-8") as f:
        json.dump(v2_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"💾 v2 已写入: {V2_PATH} ({len(v2_data)} 条记录)")

    print(f"\n✅ 完成：迁移 {migrated} 条，跳过 {skipped} 条（已存在），共 {len(v2_data)} 条")


if __name__ == "__main__":
    main()

"""无 LLM、无浏览器的评估回归入口。

用法（在 agent 目录执行）：
    python scripts/eval_regression.py -c ../.local/pancake.yaml
    python scripts/eval_regression.py -c ../.local/pancake.yaml --level L1

L0 检查 Go 图库与本地 Chroma 的数据态，L1 直接调用检索函数，
L2 只验证 Python HTTP 服务契约。每一层都复用 data/eval_seed_cases.json。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass
from typing import Any

import httpx

# 允许从 agent 目录直接运行 `python scripts/eval_regression.py`。
AGENT_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = AGENT_DIR.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import config  # noqa: E402
import chain.photo_rag as photo_rag  # noqa: E402
import vectorstore.chroma_client as chroma_client  # noqa: E402


GRANULARITIES = ("photo", "fine", "coarse")


@dataclass
class Failure:
    level: str
    case: str
    assertion: str
    detail: str


def _normalize_filename(value: str) -> str:
    return pathlib.Path(value or "").stem


def _load_cases(path: pathlib.Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"种子用例文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"种子用例 JSON 无法解析: {path}: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"种子用例为空或格式错误: {path}")
    return data


def _get(obj: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in obj:
            return obj[name]
    return default


def _fetch_photos(cfg: config.Config, burst_profile: str = "fine") -> dict[str, dict[str, Any]]:
    """读取当前图库，返回文件名（无扩展名）到照片详情的映射。"""
    result: dict[str, dict[str, Any]] = {}
    page = 1
    with httpx.Client(base_url=cfg.go_backend_url, timeout=10.0, trust_env=False) as client:
        while True:
            try:
                response = client.get(
                    "/api/v1/photos",
                    params={"page": page, "page_size": 100, "burst_profile": burst_profile},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"L0 无法访问 Go 服务 {cfg.go_backend_url}/api/v1/photos: {exc}"
                ) from exc
            payload = response.json()
            items = payload.get("items", []) if isinstance(payload, dict) else payload
            if not items:
                break
            for item in items:
                name = _normalize_filename(_get(item, "filename"))
                if name:
                    result[name] = item
            if len(items) < 100:
                break
            page += 1
    if not result:
        raise RuntimeError("L0 从 Go 服务读取到 0 张照片，无法执行种子用例")
    return result


def _run_l0(cfg: config.Config, cases: list[dict[str, Any]]) -> list[Failure]:
    photos = _fetch_photos(cfg)
    photos_coarse = _fetch_photos(cfg, burst_profile="coarse")
    failures: list[Failure] = []
    chroma_path = cfg.resolve_path("./data/chroma")
    stores = {
        g: chroma_client.ChromaPhotoStore(
            persist_dir=str(chroma_path),
            collection_name=photo_rag.GRANULARITY_COLLECTIONS[g],
        )
        for g in GRANULARITIES
    }
    for case in cases:
        name = case["name"]
        data = case["levels"]["L0"]
        for photo_id in data.get("photo_ids", []):
            if photo_id not in photos:
                failures.append(Failure("L0", name, "目标照片存在", photo_id))
        for granularity, cover_id in data.get("covers", {}).items():
            profile_photos = photos_coarse if granularity == "coarse" else photos
            item = profile_photos.get(cover_id)
            actual = _get(item or {}, "id", default="")
            if not item:
                failures.append(Failure("L0", name, f"{granularity} 封面存在", cover_id))
                continue
            # Go API 按 burst_profile 选择档位，但响应统一使用 burst_group_id。
            group_id = _get(item, "burst_group_id", "burstGroupId")
            is_cover = _get(item, "burst_cover", "burstCover", default=False)
            if not group_id or not is_cover:
                failures.append(Failure("L0", name, f"{granularity} 封面有连拍组", actual))
        for granularity, store in stores.items():
            if store.count() == 0:
                failures.append(Failure("L0", name, f"{granularity} Collection 非空", "count=0"))
    return failures


def _filename_map(cfg: config.Config) -> dict[str, str]:
    return {
        str(_get(item, "id")): name
        for name, item in _fetch_photos(cfg).items()
        if _get(item, "id")
    }


def _run_l1(cfg: config.Config, cases: list[dict[str, Any]]) -> list[Failure]:
    failures: list[Failure] = []
    id_to_filename = _filename_map(cfg)
    for case in cases:
        name = case["name"]
        data = case["levels"]["L1"]
        if "top_photo_ids" in data:
            results = photo_rag._retrieve(cfg, case["question"], 10, data["granularity"])
            ids = [_normalize_filename(id_to_filename.get(str(_get(r.get("metadata") or {}, "photo_id")), "")) for r in results]
            for expected in data["top_photo_ids"]:
                if expected not in ids[: len(data["top_photo_ids"])]:
                    failures.append(Failure("L1", name, "目标照片在预期排序位置", f"expected={expected}, actual={ids[:5]}"))
        for granularity, expected_ids in data.get("expected_top_photo_ids", {}).items():
            results = photo_rag._retrieve(cfg, case["question"], 10, granularity)
            ids = [_normalize_filename(id_to_filename.get(str(_get(r.get("metadata") or {}, "photo_id")), "")) for r in results]
            expected = expected_ids[0]
            if not ids or ids[0] != expected:
                failures.append(Failure("L1", name, f"{granularity} 首位命中", f"expected={expected}, actual={ids[:5]}"))
        for granularity, expected_ids in data.get("expected_photo_ids", {}).items():
            results = photo_rag._retrieve(cfg, case["question"], 10, granularity)
            ids = [_normalize_filename(id_to_filename.get(str(_get(r.get("metadata") or {}, "photo_id")), "")) for r in results]
            for expected in expected_ids:
                if expected not in ids:
                    failures.append(Failure("L1", name, f"{granularity} 召回未分组照片", f"expected={expected}, actual={ids[:10]}"))
        for granularity, group_id in data.get("expected_group_ids", {}).items():
            results = photo_rag._retrieve(cfg, case["question"], 10, granularity)
            actual_group_ids = [
                (result.get("metadata") or {}).get("group_id", "")
                for result in results
            ]
            if group_id not in actual_group_ids:
                failures.append(Failure("L1", name, f"{granularity} 结果包含目标连拍组", f"expected={group_id}, actual={actual_group_ids}"))
    return failures


def _run_l2(agent_url: str, cases: list[dict[str, Any]]) -> list[Failure]:
    failures: list[Failure] = []
    try:
        with httpx.Client(base_url=agent_url, timeout=5.0, trust_env=False) as client:
            health = client.get("/api/chat/health")
            health.raise_for_status()
            payload = health.json()
            if payload.get("status") != "ok":
                raise RuntimeError(f"health.status={payload.get('status')!r}")
            golden = client.get("/api/golden-queries")
            golden.raise_for_status()
            if not isinstance(golden.json(), list):
                raise RuntimeError("/api/golden-queries 返回值不是数组")

            for case in cases:
                expected_by_granularity = case["levels"]["L2"].get("expected_chat_filenames", {})
                if not expected_by_granularity:
                    continue
                session = client.post("/api/chat/sessions", json={"title": "评估回归临时会话"})
                session.raise_for_status()
                session_id = session.json().get("session_id", "")
                if not session_id:
                    raise RuntimeError("创建临时会话未返回 session_id")
                try:
                    for granularity, expected_names in expected_by_granularity.items():
                        response = client.post(
                            f"/api/chat/sessions/{session_id}/messages",
                            json={"question": case["question"], "granularity": granularity},
                            timeout=120.0,
                        )
                        response.raise_for_status()
                        payload = response.json()
                        actual_names = [
                            _normalize_filename(photo.get("filename", ""))
                            for photo in payload.get("photos", [])
                        ]
                        for expected_name in expected_names:
                            if expected_name not in actual_names:
                                failures.append(Failure(
                                    "L2", case["name"], f"{granularity} 对话召回未分组照片",
                                    f"expected={expected_name}, actual={actual_names}, trace_id={payload.get('trace_id', '')}",
                                ))
                finally:
                    client.delete(f"/api/chat/sessions/{session_id}")
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        for case in cases:
            failures.append(Failure("L2", case["name"], "HTTP 服务契约可用", str(exc)))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Photo Agent 三层评估回归")
    parser.add_argument("-c", "--config", required=True, help="Python Agent YAML 配置文件")
    parser.add_argument("--level", choices=("all", "L0", "L1", "L2"), default="all")
    parser.add_argument("--case", choices=("all", "retrieval", "burst"), default="all")
    parser.add_argument("--agent-url", default="http://127.0.0.1:10005", help="L2 Python Agent 地址")
    args = parser.parse_args()
    try:
        cfg = config.Config(args.config)
        cases = _load_cases(PROJECT_ROOT / "data/eval_seed_cases.json")
        if args.case != "all":
            prefix = "retrieval-" if args.case == "retrieval" else "burst-"
            cases = [case for case in cases if case["id"].startswith(prefix)]
        if not cases:
            raise RuntimeError(f"没有匹配的种子用例: {args.case}")
        levels = ("L0", "L1", "L2") if args.level == "all" else (args.level,)
        runners = {"L0": _run_l0, "L1": _run_l1}
        failures: list[Failure] = []
        for level in levels:
            try:
                if level == "L2":
                    level_failures = _run_l2(args.agent_url, cases)
                else:
                    level_failures = runners[level](cfg, cases)
                failures.extend(level_failures)
                if not level_failures:
                    print(f"PASS [{level}] {len(cases)} 条种子用例")
            except Exception as exc:
                for case in cases:
                    failures.append(Failure(level, case["name"], "层级执行成功", str(exc)))
        if failures:
            for failure in failures:
                print(f"FAIL [{failure.level}] {failure.case}: {failure.assertion} ({failure.detail})")
            print(f"回归失败: {len(failures)} 条断言")
            return 1
        print(f"PASS: {len(cases)} 条种子用例通过 {', '.join(levels)}")
        return 0
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

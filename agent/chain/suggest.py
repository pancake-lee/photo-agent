"""
    潜在主题识别模块 — 编辑视角提案。

    三阶段工作流：
        1. 随机采样 → LLM 生成主题直觉（不暴露日期信息）
        2. RAG + 多样性约束 → 扩展选片
        3. LLM 沉淀完整选题提案（标题 + 角度 + 照片序列 + 理由）

    用法:
        import chain.suggest as suggest_mod

        suggestions = suggest_mod.run_suggest(cfg, go_backend_url, cluster_dir)
        for s in suggestions:
            print(s.title, s.angle)
"""

import sys
import time
import pathlib
import json
import logging
import datetime
import dataclasses
import typing
import collections
import random
import re
import itertools

import langchain_core.messages as lc_messages

import utils.backend_sdk as bksdk
import chain.cluster as cluster_mod
import utils.llm_factory as llm_factory
import chain.tracer as tracer_mod

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构
# ============================================================================

@dataclasses.dataclass
class TopicIntuition:
    """Stage 1 输出：LLM 基于随机采样的主题直觉。"""
    title: str
    angle: str
    rationale: str
    inspired_indices: list[int]  # 启发该直觉的采样照片索引
    inspired_photo_ids: list[str] = dataclasses.field(default_factory=list)  # 实际 photo_id


@dataclasses.dataclass
class TopicProposal:
    """Stage 3 输出：结构化选题提案。"""
    title: str
    angle: str
    rationale: str
    photo_sequence: list[dict]   # [{"photo_id": "...", "role_in_narrative": "..."}]
    category: str                # "editorial_proposal"


@dataclasses.dataclass
class TopicSuggestion:
    """最终选题建议（统一对外输出格式）。"""
    title: str
    angle: str
    rationale: str
    candidate_index: int
    photo_ids: list[str]
    category: str
    photo_sequence: list[dict] = dataclasses.field(default_factory=list)  # [{photo_id, role_in_narrative}]
    trace_id: str = ""
    intuition_source: list[str] = dataclasses.field(default_factory=list)  # Stage 1 启发照片 ID


# ============================================================================
# 常量
# ============================================================================

_STAGE1_SAMPLE_MIN = 3
_STAGE1_SAMPLE_MAX = 3
_STAGE2_MIN_PHOTOS = 3
_STAGE3_MIN_POOL = 6   # Stage 3 最少候选数：少于此数量难以独立发现选题
_STAGE3_TARGET_MIN = 9
_STAGE3_TARGET_MAX = 18
_STAGE2_MAX_PER_DATE = 2
_STAGE2_RAG_TOP_N = 45


def _parse_shot_date(shot_at: str) -> datetime.date | None:
    """将 shot_at 字符串解析为日期，兼容 Unix 时间戳和 ISO 日期格式。

    Go 后端 API 返回的 shotAt 是 Unix 时间戳字符串（如 "1780733203"），
    但代码历史上有按 ISO 日期字符串（如 "2025-05-02"）处理的假设。
    此函数统一处理两种格式。
    """
    if not shot_at or not shot_at.strip():
        return None
    val = shot_at.strip()
    # Unix 时间戳（纯数字字符串）
    if val.isdigit():
        try:
            return datetime.datetime.fromtimestamp(int(val)).date()
        except (ValueError, OSError):
            pass
    # ISO 日期格式（YYYY-MM-DD...）
    try:
        return datetime.date.fromisoformat(val[:10])
    except (ValueError, TypeError):
        pass
    return None


# ============================================================================
# Stage 1: 随机采样 → 主题直觉
# ============================================================================

_STAGE1_SYSTEM_PROMPT = (
    "你是一位摄影编辑和策展人，正在浏览一位摄影师图库中的随机照片。"
    "你的任务是从这些照片中挖掘有意义的选题视角，发现值得讲述的故事或值得分享的观察。\n\n"
    "核心原则：\n"
    "- 每一张照片都可能蕴含一个独特的视角，你不需要在随机照片之间寻找共同点\n"
    "- 从单张照片中获得灵感就足够了（inspired_indices 可以是 [3]），选题和组图是两个独立的步骤\n"
    "- 选题的关键不在于'找到了不常见的组合'，而在于这个视角本身是否有价值\n"
    "- 我没有给你拍摄日期和地点信息，请不要按时间线或地点归类\n\n"
    "选题质量标准（按重要性排序）：\n"
    "1. 能引发思考：让观众看到照片后产生新的想法、疑问或认知 shift\n"
    "2. 有趣味性：视角新颖、幽默、出人意料，能抓住注意力\n"
    "3. 有美学价值：对构图、光影、色彩等方面的独特审美发现\n"
    "4. 有情感共鸣：能唤起普遍的人类情感、记忆或体验\n\n"
    "输出 1 个最有价值的选题直觉，包含：\n"
    "- title: 标题 6-12 字，精炼有记忆点\n"
    "- angle: 角度描述 20-40 字，说明这个选题的独特视角和发布价值\n"
    "- rationale: 选题理由 20-40 字，说明这个视角为什么有意义（而非仅仅描述照片里有什么）\n"
    "- inspired_indices: 启发该直觉的照片索引编号列表，可以是单元素数组如 [3]\n\n"
    "你必须严格返回一行合法 JSON 数组，不得包含任何其他文字、注释或 markdown 标记：\n"
    '[{"title":"...","angle":"...","rationale":"...","inspired_indices":[3]}]'
)


def _random_sample_photos(
    photos,
    min_n: int = _STAGE1_SAMPLE_MIN,
    max_n: int = _STAGE1_SAMPLE_MAX,
) -> list:
    """随机采样照片，优先保证拍摄日期多样性。

    先按日期分组，从每个日期随机取 1 张。若不足 min_n，从剩余照片补充。
    若超过 max_n，随机截断。
    """
    if len(photos) <= max_n:
        sampled = list(photos)
        random.shuffle(sampled)
        return sampled

    date_groups: dict[str, list] = collections.defaultdict(list)
    for p in photos:
        shot_date = _parse_shot_date(getattr(p, "shot_at", "") or "")
        date_key = shot_date.isoformat() if shot_date else "__unknown__"
        date_groups[date_key].append(p)

    dates = list(date_groups.keys())
    random.shuffle(dates)

    sampled: list = []
    sampled_ids: set[str] = set()

    # 第一轮：每个日期取 1 张
    for date_key in dates:
        if len(sampled) >= max_n:
            break
        group = date_groups[date_key]
        pick = random.choice(group)
        pid = getattr(pick, "id", "")
        if pid not in sampled_ids:
            sampled.append(pick)
            sampled_ids.add(pid)

    logger.info(
        "随机采样第一轮: %d 个日期 → %d 张 (%d 个不同日期)",
        len(dates), len(sampled), len({_parse_shot_date(getattr(p, "shot_at", "") or "") for p in sampled}),
    )

    # 第二轮：不足 min_n 则从剩余补充
    if len(sampled) < min_n:
        remaining = [p for p in photos if getattr(p, "id", "") not in sampled_ids]
        needed = min(min_n - len(sampled), len(remaining))
        if needed > 0:
            extra = random.sample(remaining, needed)
            for p in extra:
                sampled.append(p)
                sampled_ids.add(getattr(p, "id", ""))

    random.shuffle(sampled)
    result = sampled[:max_n]

    logger.info("Stage 1 随机采样: %d 张照片（共 %d 个不同日期）",
                 len(result),
                 len({_parse_shot_date(getattr(p, "shot_at", "") or "") for p in result}))
    return result


def _build_stage1_prompt(photos) -> str:
    """构建 Stage 1 的 LLM prompt：展示随机采样的照片描述，不包含日期信息。"""
    lines: list[str] = []
    lines.append("以下是摄影师图库中随机抽取的照片，请以编辑视角浏览：\n")

    for i, p in enumerate(photos):
        desc = (getattr(p, "description", "") or "").strip()
        filename = (getattr(p, "filename", "") or getattr(p, "id", "") or f"photo_{i}")
        if desc:
            # 截取前 300 字，避免 prompt 过长
            desc_short = desc[:300] + ("..." if len(desc) > 300 else "")
            lines.append(f"### 照片 {i}")
            lines.append(f"文件名: {filename}")
            lines.append(f"描述: {desc_short}")
            lines.append("")
        else:
            lines.append(f"### 照片 {i}")
            lines.append(f"文件名: {filename}")
            lines.append(f"描述: （无描述）")
            lines.append("")

    lines.append("请基于以上照片，输出 1 个最有价值的选题直觉。")
    return "\n".join(lines)


def _parse_llm_json_response(raw: str, context_label: str = "") -> list[dict]:
    """通用 LLM JSON 响应解析：直接解析 → 去 markdown → 正则提取数组 → 逐对象提取。"""
    raw = raw.strip()

    attempts: list[str] = [raw]
    if raw.startswith("```"):
        lines_raw = raw.split("\n")
        lines_raw = [ln for ln in lines_raw if not ln.startswith("```")]
        attempts.append("\n".join(lines_raw).strip())

    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and "title" in parsed:
                return [parsed]
        except (json.JSONDecodeError, TypeError):
            pass

    # 正则提取 JSON 数组
    m = re.search(r'\[\s*\{.*?\}\s*\]', raw, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group())
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # 逐对象提取
    objects = re.findall(r'\{[^{}]*\}', raw)
    if objects:
        results: list[dict] = []
        for obj_str in objects:
            try:
                obj = json.loads(obj_str)
                if isinstance(obj, dict) and "title" in obj:
                    results.append(obj)
            except (json.JSONDecodeError, TypeError):
                continue
        if results:
            return results

    prefix = f"{context_label} " if context_label else ""
    logger.warning("无法解析 %sLLM 响应: %s", prefix, raw[:300])
    return []


def _parse_intuitions_response(raw: str) -> list[dict]:
    """解析 Stage 1 LLM 返回的主题直觉 JSON。"""
    return _parse_llm_json_response(raw, "Stage 1 主题直觉")


def _stage1_generate_intuitions(
    cfg, photos, tracer: tracer_mod.Tracer | None = None,
    photo_ids_override: list[str] | None = None,
    prompt_override: str | None = None,
    intuitions_override: list[dict] | None = None,
) -> list[TopicIntuition]:
    """Stage 1: 随机采样照片 → LLM 以编辑视角生成主题直觉。

    重入参数:
        photo_ids_override: 替换随机采样，使用指定的 photo_id 列表
        prompt_override: 替换自动构建的 prompt 文本
        intuitions_override: 直接使用提供的直觉列表，跳过 LLM 调用。
            格式: [{"title", "angle", "rationale", "inspired_indices"}]
    """
    # 如果提供了直觉覆盖，直接返回
    if intuitions_override is not None:
        intuitions: list[TopicIntuition] = []
        for item in intuitions_override:
            intuitions.append(TopicIntuition(
                title=item.get("title", "未命名选题"),
                angle=item.get("angle", ""),
                rationale=item.get("rationale", ""),
                inspired_indices=item.get("inspired_indices", []),
                inspired_photo_ids=item.get("inspired_photo_ids", []),
            ))
        if tracer:
            tracer.emit("suggest.stage1.intuitions", {
                "count": len(intuitions),
                "source": "override",
                "intuitions": [
                    {"title": it.title, "angle": it.angle, "rationale": it.rationale}
                    for it in intuitions
                ],
            }, module="suggest")
        logger.info("Stage 1: 使用提供的 %d 个直觉（跳过 LLM）", len(intuitions))
        return intuitions

    if len(photos) < _STAGE1_SAMPLE_MIN and not photo_ids_override:
        logger.warning(
            "照片数量不足 %d 张（当前 %d），跳过 Stage 1 随机采样",
            _STAGE1_SAMPLE_MIN, len(photos),
        )
        return []

    # 使用指定的照片 或 随机采样
    if photo_ids_override:
        photo_by_id: dict[str, any] = {}
        for p in photos:
            pid = getattr(p, "id", "")
            if pid:
                photo_by_id[pid] = p
        sampled = [photo_by_id[pid] for pid in photo_ids_override if pid in photo_by_id]
        logger.info("Stage 1: 使用指定照片 %d/%d 张", len(sampled), len(photo_ids_override))
    else:
        sampled = _random_sample_photos(photos)

    # trace: suggest.stage1.sample
    sample_photo_ids: list[str] = []
    sample_photo_descs: list[str] = []
    for p in sampled:
        pid = getattr(p, "id", "")
        desc = (getattr(p, "description", "") or "").strip()[:120]
        sample_photo_ids.append(pid)
        sample_photo_descs.append(desc)
    if tracer:
        tracer.emit("suggest.stage1.sample", {
            "sample_size": len(sampled),
            "date_count": len({_parse_shot_date(getattr(p, "shot_at", "") or "") for p in sampled}),
            "photo_ids": sample_photo_ids,
            "photo_descs": sample_photo_descs,
        }, module="suggest")

    prompt_text = prompt_override if prompt_override else _build_stage1_prompt(sampled)

    llm = llm_factory.create_llm(cfg, temperature=0.8)
    messages = [
        lc_messages.SystemMessage(content=_STAGE1_SYSTEM_PROMPT),
        lc_messages.HumanMessage(content=prompt_text),
    ]

    # trace: suggest.stage1.llm.start
    if tracer:
        payload_ref = tracer.save_payload(f"s1-prompt.txt", _STAGE1_SYSTEM_PROMPT + "\n\n" + prompt_text)
        tracer.emit("suggest.stage1.llm.start", {
            "model": getattr(cfg, "llm_model", "unknown"),
            "temperature": 0.8,
            "prompt_chars": len(prompt_text),
            "payload_ref": payload_ref,
        }, module="suggest")

    t_start = time.time()
    try:
        resp = llm.invoke(messages)
        raw = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as e:
        logger.exception("Stage 1 LLM 调用失败")
        return []
    llm_duration_ms = int((time.time() - t_start) * 1000)

    # trace: suggest.stage1.llm.end
    token_usage: dict = {}
    if hasattr(resp, "response_metadata"):
        usage = resp.response_metadata.get("token_usage", {})
        token_usage = {
            "prompt": usage.get("prompt_tokens", 0),
            "completion": usage.get("completion_tokens", 0),
        }
    if tracer:
        resp_ref = tracer.save_payload(f"s1-response.txt", raw)
        tracer.emit("suggest.stage1.llm.end", {
            "model": getattr(cfg, "llm_model", "unknown"),
            "duration_ms": llm_duration_ms,
            "token_usage": token_usage,
            "response_chars": len(raw),
            "payload_ref": resp_ref,
        }, module="suggest")

    parsed = _parse_intuitions_response(raw)
    if not parsed:
        return []

    intuitions: list[TopicIntuition] = []
    for item in parsed[:4]:
        indices = item.get("inspired_indices", [])
        # 映射索引到实际 photo_id
        photo_ids: list[str] = []
        for idx in indices:
            try:
                i = int(idx)
                if 0 <= i < len(sampled):
                    pid = getattr(sampled[i], "id", "")
                    # noqa: SIM102 — 待修复
                    if pid:
                        photo_ids.append(pid)
            except (ValueError, TypeError):
                continue

        intuitions.append(TopicIntuition(
            title=item.get("title", "未命名选题"),
            angle=item.get("angle", ""),
            rationale=item.get("rationale", ""),
            inspired_indices=indices if isinstance(indices, list) else [],
            inspired_photo_ids=photo_ids,
        ))

    # trace: suggest.stage1.intuitions
    if tracer:
        tracer.emit("suggest.stage1.intuitions", {
            "count": len(intuitions),
            "intuitions": [
                {
                    "title": it.title,
                    "angle": it.angle,
                    "rationale": it.rationale,
                    "inspired_photo_ids": [
                        sample_photo_ids[i] for i in it.inspired_indices
                        if isinstance(i, int) and 0 <= i < len(sample_photo_ids)
                    ],
                }
                for it in intuitions
            ],
        }, module="suggest")

    logger.info("Stage 1 生成 %d 个主题直觉", len(intuitions))
    return intuitions


# ============================================================================
# Stage 2: 主题 → 扩展选片
# ============================================================================

# noqa: E501 — 行长度豁免
def _stage2_expand_selection(
    cfg,
    intuition: TopicIntuition,
    all_photos,
    tracer: tracer_mod.Tracer | None = None,
) -> list:
    """Stage 2: 围绕主题直觉，通过 RAG + 多样性约束扩展候选照片。

    返回按多样性约束过滤后的照片列表（ApiPhotoItem 对象）。
    """
    import chain.photo_rag as photo_rag

    # 用标题 + 角度作为 RAG 检索查询
    query = f"{intuition.title} {intuition.angle}"
    logger.info("Stage 2 RAG 检索: %s", query[:80])

    # trace: suggest.stage2.rag.start
    if tracer:
        tracer.emit("suggest.stage2.rag.start", {
            "query": query,
            "intuition_title": intuition.title,
            "n_results": _STAGE2_RAG_TOP_N,
        }, module="suggest")

    try:
        rag_result = photo_rag.retrieve_photo_ids(
            cfg, query,
            n_results=_STAGE2_RAG_TOP_N,
            auto_distance_ratio=2.5,
            with_details=bool(tracer),
        )
    except Exception as e:
        logger.warning("Stage 2 RAG 检索失败: %s", e)
        rag_ids = []
        rag_details: list[dict] = []
    else:
        if isinstance(rag_result, tuple):
            rag_ids, rag_details = rag_result
        else:
            rag_ids = rag_result
            rag_details = []

    if not rag_ids:
        logger.warning("Stage 2: RAG 检索 '%s' 无结果", intuition.title)
        if tracer:
            tracer.emit("suggest.stage2.rag.end", {
                "matched_count": 0,
                "total_retrieved": 0,
                "photo_ids": [],
                "distances": [],
            }, module="suggest")
        return []

    # 从全量照片中匹配 RAG 结果
    photo_by_id: dict[str, any] = {}
    for p in all_photos:
        pid = getattr(p, "id", "")
        if pid:
            photo_by_id[pid] = p

    matched: list = []
    matched_distances: list[float] = []
    for pid in rag_ids:
        if pid in photo_by_id:
            matched.append(photo_by_id[pid])
            # 查找对应距离
            dist = None
            for rd in rag_details:
                meta = rd.get("metadata") or {}
                if meta.get("photo_id") == pid:
                    dist = rd.get("distance")
                    break
            if dist is not None:
                matched_distances.append(dist)

    if not matched:
        if tracer:
            tracer.emit("suggest.stage2.rag.end", {
                "matched_count": 0,
                "total_retrieved": len(rag_ids),
                "photo_ids": [],
                "distances": [],
            }, module="suggest")
        return []

    logger.info("Stage 2: RAG 匹配 %d/%d 张照片", len(matched), len(rag_ids))

    # trace: suggest.stage2.rag.end (before diversity filter)
    if tracer:
        # 计算相邻距离比值序列
        dists = matched_distances if matched_distances else [float("inf")] * len(matched)
        ratio_gaps: list[float] = []
        for i in range(len(dists) - 1):
            if dists[i] and dists[i] > 0 and dists[i + 1]:
                ratio_gaps.append(round(dists[i + 1] / dists[i], 2))
        tracer.emit("suggest.stage2.rag.end", {
            "matched_count": len(matched),
            "total_retrieved": len(rag_ids),
            "photo_ids": [getattr(p, "id", "") for p in matched],
            "distances": [round(d, 4) if d else None for d in matched_distances],
            "ratio_gaps": ratio_gaps,
        }, module="suggest")

    # ═══ 多样性采样：按日期分组，每组至多选 _STAGE2_MAX_PER_DATE 张 ═══
    date_groups: dict[str, list] = collections.defaultdict(list)
    for p in matched:
        shot_date = _parse_shot_date(getattr(p, "shot_at", "") or "")
        date_key = shot_date.isoformat() if shot_date else "__unknown__"
        date_groups[date_key].append(p)

    diverse: list = []
    # 记录每个日期组的保留/移除详情，用于前端展示因果关系
    diversity_details: list[dict] = []
    for date_key in sorted(date_groups.keys()):
        group = date_groups[date_key]
        take = min(len(group), _STAGE2_MAX_PER_DATE)
        kept = group[:take]
        removed = group[take:]
        diverse.extend(kept)
        detail = {
            "date": date_key if date_key != "__unknown__" else "未知日期",
            "kept_photo_ids": [getattr(p, "id", "") for p in kept],
        }
        if removed:
            detail["removed_photo_ids"] = [getattr(p, "id", "") for p in removed]
            detail["reason"] = (
                f"同一日期已有 {len(kept)} 张入选，移除 {len(removed)} 张"
            )
        diversity_details.append(detail)

    before_diverse = len(matched)
    removed_ids: list[str] = []

    # 如果筛选后不足 _STAGE2_MIN_PHOTOS 张，从被过滤掉的补充
    if len(diverse) < _STAGE2_MIN_PHOTOS:
        existing_ids = {getattr(p, "id", "") for p in diverse}
        for p in matched:
            if len(diverse) >= _STAGE2_MIN_PHOTOS:
                break
            if getattr(p, "id", "") not in existing_ids:
                diverse.append(p)
                existing_ids.add(getattr(p, "id", ""))
    else:
        diverse_ids = {getattr(p, "id", "") for p in diverse}
        for p in matched:
            pid = getattr(p, "id", "")
            if pid and pid not in diverse_ids:
                removed_ids.append(pid)

    # 验证时间跨度
    dates = []
    for p in diverse:
        shot_date = _parse_shot_date(getattr(p, "shot_at", "") or "")
        if shot_date:
            dates.append(shot_date)

    date_span = 0
    if len(dates) >= 2:
        dates.sort()
        date_span = (dates[-1] - dates[0]).days

    # trace: suggest.stage2.diversity
    if tracer:
        tracer.emit("suggest.stage2.diversity", {
            "before_count": before_diverse,
            "after_count": len(diverse),
            "date_count": len(date_groups),
            "removed_photo_ids": removed_ids,
            "kept_photo_ids": [getattr(p, "id", "") for p in diverse],
            "diversity_details": diversity_details,
        }, module="suggest")

    logger.info(
        "Stage 2 扩展选片: %d 张（%d 个日期）, 时间跨度 %d 天",
        len(diverse), len(date_groups), date_span,
    )

    return diverse


# ============================================================================
# Stage 3: 主题沉淀 → 完整选题提案
# ============================================================================

_STAGE3_SYSTEM_PROMPT = (
    "你是一位摄影编辑和策展人。"
    "给你一组通过语义检索聚合的照片，请从中独立发现有意义的选题，策划一组可以发布的照片专题。\n\n"
    "核心原则：\n"
    "- 这些照片因语义相关性被聚在一起，但你的任务不是描述它们的共同点\n"
    "- 你需要从中发现一个值得讲述的故事或值得分享的观察，选题要有独立的价值判断\n"
    "- 选题标准（按重要性排序）：能引发思考 > 有趣味性 > 有美学发现 > 有情感共鸣\n"
    "- 不要按时间线或地点归类，也不要简单按拍摄对象分类（如'建筑照片集'、'花卉合集'）\n\n"
    "输出要求：\n"
    "- title: 标题 6-12 字，精炼有记忆点\n"
    "- angle: 叙事角度 30-60 字，说明这组照片的故事线和发布价值\n"
    "- rationale: 发布理由 20-40 字，说明这个选题为什么有意义（而非仅仅描述照片内容或时间跨度）\n"
    "- photo_sequence: 照片序列数组，按叙事逻辑排列（不按时间或相似度）\n"
    "  - photo_id: 照片 ID\n"
    "  - role_in_narrative: 这张照片在叙事中扮演什么角色（8-15 字）\n"
    "- 从候选照片中选择 9-18 张来构建完整的叙事弧线，优先选择不同场景的照片\n"
    "- 尽量覆盖更多照片以呈现主题的丰富性，但不要为了凑数而纳入不相关的照片\n"
    "- 如果候选照片内容过于分散、确实难以形成有意义的选题，可以返回空 photo_sequence\n"
    "- 时间跨度不做硬性要求\n\n"
    "你必须严格返回一行合法 JSON，不得包含任何其他文字、注释或 markdown 标记：\n"
    '{"title":"...","angle":"...","rationale":"...",'
    '"photo_sequence":[{"photo_id":"...","role_in_narrative":"..."}]}'
)


def _build_stage3_prompt(expanded_photos) -> str:
    """构建 Stage 3 的 LLM prompt：仅展示候选照片，不预设选题方向。"""
    lines: list[str] = []
    lines.append("## 候选照片\n")
    lines.append(f"共 {len(expanded_photos)} 张照片，请从中独立发现有意义的选题视角，策划一组照片专题。\n")
    lines.append("")

    for i, p in enumerate(expanded_photos):
        pid = getattr(p, "id", f"unknown_{i}")
        shot_date = _parse_shot_date(getattr(p, "shot_at", "") or "")
        date_str = shot_date.isoformat() if shot_date else "未知日期"
        desc = (getattr(p, "description", "") or "").strip()
        if desc:
            desc_short = desc[:250] + ("..." if len(desc) > 250 else "")
        else:
            desc_short = "（无描述）"
        lines.append(f"### 候选 {i}")
        lines.append(f"ID: {pid}")
        lines.append(f"日期: {date_str}")
        lines.append(f"描述: {desc_short}")
        lines.append("")

    lines.append("请基于以上候选照片，独立挖掘选题并输出完整选题提案。")
    return "\n".join(lines)


def _parse_proposal_response(raw: str) -> dict | None:
    """解析 Stage 3 LLM 返回的选题提案 JSON。"""
    raw = raw.strip()

    attempts: list[str] = [raw]
    if raw.startswith("```"):
        lines_raw = raw.split("\n")
        lines_raw = [ln for ln in lines_raw if not ln.startswith("```")]
        attempts.append("\n".join(lines_raw).strip())

    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict) and "title" in parsed:
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # 正则提取
    m = re.search(r'\{.*"title".*\}', raw, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group())
            if isinstance(parsed, dict) and "title" in parsed:
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    logger.warning("无法解析 Stage 3 LLM 选题提案响应: %s", raw[:300])
    return None


def _stage3_generate_proposals(
    cfg,
    intuitions: list[TopicIntuition],
    all_photos,
    tracer: tracer_mod.Tracer | None = None,
    expanded_photos_override: dict[int, list] | None = None,
    prompt_overrides: dict[int, str] | None = None,
    proposal_overrides: dict[int, dict] | None = None,
) -> list[TopicSuggestion]:
    """Stage 3: 为每个主题直觉生成完整选题提案。

    重入参数:
        expanded_photos_override: {intuition_index: [photo_objects]}, 跳过 RAG
        prompt_overrides: {intuition_index: prompt_string}, 替换 prompt
        proposal_overrides: {intuition_index: {title, angle, rationale, photo_sequence}},
            跳过 LLM，直接使用提供的提案
    """
    proposals: list[TopicSuggestion] = []

    for idx, intuition in enumerate(intuitions):
        # 如果有 proposal override，直接构造结果跳过所有 LLM 流程
        if proposal_overrides and idx in proposal_overrides:
            po = proposal_overrides[idx]
            photo_ids = po.get("photo_ids", [])
            proposals.append(TopicSuggestion(
                title=po.get("title", intuition.title),
                angle=po.get("angle", intuition.angle),
                rationale=po.get("rationale", intuition.rationale),
                candidate_index=idx,
                photo_ids=photo_ids,
                category="editorial_proposal",
                photo_sequence=po.get("photo_sequence", []),
                trace_id=tracer.trace_id if tracer else "",
                intuition_source=intuition.inspired_photo_ids,
            ))
            if tracer:
                tracer.emit("suggest.stage3.proposal", {
                    "title": po.get("title", ""),
                    "angle": po.get("angle", ""),
                    "rationale": po.get("rationale", ""),
                    "photo_sequence": po.get("photo_sequence", []),
                    "source": "override",
                }, module="suggest")
            logger.info("Stage 3: 选题 '%s' 使用提供的提案（跳过 LLM）", po.get("title", ""))
            continue

        # 扩展选片（使用覆盖 或 RAG）
        if expanded_photos_override and idx in expanded_photos_override:
            expanded = expanded_photos_override[idx]
            logger.info("Stage 3: 选题 '%s' 使用提供的扩展照片 %d 张", intuition.title, len(expanded))
        else:
            expanded = _stage2_expand_selection(cfg, intuition, all_photos, tracer=tracer)

        if len(expanded) < _STAGE3_MIN_POOL:
            logger.warning(
                "Stage 3: 选题 '%s' 候选池仅 %d 张（需 ≥%d），不足以独立发现选题，跳过",
                intuition.title, len(expanded), _STAGE3_MIN_POOL,
            )
            if tracer:
                tracer.emit("suggest.decision.skip", {
                    "intuition_title": intuition.title,
                    "reason": f"expanded_count={len(expanded)} < min={_STAGE3_MIN_POOL}",
                    "expanded_count": len(expanded),
                    "min_required": _STAGE3_MIN_POOL,
                }, module="suggest")
            continue

        # 构建 prompt（使用覆盖 或 默认）
        if prompt_overrides and idx in prompt_overrides:
            prompt_text = prompt_overrides[idx]
        else:
            prompt_text = _build_stage3_prompt(expanded)

        # trace: suggest.stage3.llm.start
        prompt_idx = idx
        if tracer:
            payload_ref = tracer.save_payload(
                f"s3-prompt-{prompt_idx}.txt",
                _STAGE3_SYSTEM_PROMPT + "\n\n" + prompt_text,
            )
            tracer.emit("suggest.stage3.llm.start", {
                "intuition_title": intuition.title,
                "candidate_count": len(expanded),
                "prompt_chars": len(prompt_text),
                "payload_ref": payload_ref,
            }, module="suggest")

        llm = llm_factory.create_llm(cfg, temperature=0.7)
        messages = [
            lc_messages.SystemMessage(content=_STAGE3_SYSTEM_PROMPT),
            lc_messages.HumanMessage(content=prompt_text),
        ]

        t_start = time.time()
        try:
            resp = llm.invoke(messages)
            raw = resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            logger.exception("Stage 3 LLM 调用失败: %s", intuition.title)
            continue
        llm_duration_ms = int((time.time() - t_start) * 1000)

        # trace: suggest.stage3.llm.end
        token_usage: dict = {}
        if hasattr(resp, "response_metadata"):
            usage = resp.response_metadata.get("token_usage", {})
            token_usage = {
                "prompt": usage.get("prompt_tokens", 0),
                "completion": usage.get("completion_tokens", 0),
            }
        if tracer:
            resp_ref = tracer.save_payload(f"s3-response-{prompt_idx}.txt", raw)
            tracer.emit("suggest.stage3.llm.end", {
                "model": getattr(cfg, "llm_model", "unknown"),
                "duration_ms": llm_duration_ms,
                "token_usage": token_usage,
                "response_chars": len(raw),
                "payload_ref": resp_ref,
            }, module="suggest")

        parsed = _parse_proposal_response(raw)
        if not parsed:
            continue

        # ═══ 提取 LLM 返回的 photo_sequence ═══
        sequence = parsed.get("photo_sequence", [])
        if isinstance(sequence, list):
            raw_ids = [s.get("photo_id", "") for s in sequence if s.get("photo_id")]
            # 保存完整的 photo_sequence（含 role_in_narrative）
            clean_sequence: list[dict] = [
                {"photo_id": s.get("photo_id", ""),
                 "role_in_narrative": s.get("role_in_narrative", "")}
                for s in sequence if s.get("photo_id")
            ]
        else:
            raw_ids = []
            clean_sequence = []

        # LLM 判定候选照片无法形成有意义的选题（空 photo_sequence）
        if not clean_sequence:
            logger.info(
                "Stage 3: 选题 '%s' LLM 判定候选池（%d 张）无法形成有意义的选题，跳过",
                parsed.get("title", ""), len(expanded),
            )
            if tracer:
                tracer.emit("suggest.stage3.skip_empty", {
                    "title": parsed.get("title", ""),
                    "candidate_count": len(expanded),
                    "reason": "llm_returned_empty_photo_sequence",
                }, module="suggest")
            continue

        # trace: suggest.stage3.proposal (before validation)
        if tracer:
            tracer.emit("suggest.stage3.proposal", {
                "title": parsed.get("title", intuition.title),
                "angle": parsed.get("angle", ""),
                "rationale": parsed.get("rationale", ""),
                "photo_sequence": clean_sequence,
            }, module="suggest")

        # ═══ B8: 校验 photo_id 有效性，过滤幻觉/截断 ID ═══
        valid_ids: set[str] = {getattr(p, "id", "") for p in all_photos}
        valid_ids.update(getattr(p, "id", "") for p in expanded)
        valid_ids.discard("")

        expanded_ids = [getattr(p, "id", "") for p in expanded if getattr(p, "id", "")]
        used_ids: set[str] = set()
        photo_ids: list[str] = []
        hallucinated = 0
        replacements: list[dict] = []  # trace 用

        for pid in raw_ids:
            if pid in valid_ids and pid not in used_ids:
                photo_ids.append(pid)
                used_ids.add(pid)
            else:
                hallucinated += 1
                replaced = False
                for alt_id in expanded_ids:
                    if alt_id not in used_ids and alt_id in valid_ids:
                        photo_ids.append(alt_id)
                        used_ids.add(alt_id)
                        replaced = True
                        replacements.append({
                            "from_id": pid,
                            "to_id": alt_id,
                            "reason": "不存在" if pid not in valid_ids else "重复",
                        })
                        logger.warning(
                            "Stage 3: photo_id '%s' 无效（%s），替换为 '%s'",
                            pid,
                            "不存在" if pid not in valid_ids else "重复",
                            alt_id,
                        )
                        break
                if not replaced:
                    logger.warning(
                        "Stage 3: 选题 '%s' photo_id '%s' 无效且无可用替换",
                        parsed.get("title", ""), pid,
                    )

        if hallucinated:
            logger.warning(
                "Stage 3: 选题 '%s' 共 %d 个 photo_id 无效，已替换",
                parsed.get("title", ""), hallucinated,
            )

        # 校验后不足最低张数则从扩展列表补充
        if len(photo_ids) < _STAGE2_MIN_PHOTOS:
            for alt_id in expanded_ids:
                if alt_id not in used_ids and alt_id in valid_ids:
                    photo_ids.append(alt_id)
                    used_ids.add(alt_id)
                    if len(photo_ids) >= _STAGE2_MIN_PHOTOS:
                        break
        if not photo_ids:
            photo_ids = expanded_ids[:_STAGE2_MIN_PHOTOS]

        # trace: suggest.stage3.validation
        if tracer:
            tracer.emit("suggest.stage3.validation", {
                "hallucinated_count": hallucinated,
                "replaced": replacements,
                "final_photo_count": len(photo_ids),
            }, module="suggest")

        # ═══ 记录时间跨度（建议性，不做强制替换） ═══
        date_map: dict[str, datetime.date] = {}
        for p in itertools.chain(expanded, all_photos):
            pid = getattr(p, "id", "")
            shot_date = _parse_shot_date(getattr(p, "shot_at", "") or "")
            if pid and shot_date:
                date_map[pid] = shot_date

        selected_dates = [date_map[pid] for pid in photo_ids if pid in date_map]
        span_days = 0
        if len(selected_dates) >= 2:
            selected_dates.sort()
            span_days = (selected_dates[-1] - selected_dates[0]).days

        if span_days < 3 and len(selected_dates) >= 2:
            logger.info(
                "Stage 3: 选题 '%s' 时间跨度仅 %d 天（照片可能集中在相近日期）",
                parsed.get("title", ""), span_days,
            )

        if tracer:
            tracer.emit("suggest.stage3.time_span", {
                "span_days": span_days,
                "photo_count": len(photo_ids),
                "dated_count": len(selected_dates),
            }, module="suggest")

        proposals.append(TopicSuggestion(
            title=parsed.get("title", intuition.title),
            angle=parsed.get("angle", intuition.angle),
            rationale=parsed.get("rationale", intuition.rationale),
            candidate_index=idx,
            photo_ids=photo_ids,
            category="editorial_proposal",
            photo_sequence=clean_sequence,
            trace_id=tracer.trace_id if tracer else "",
            intuition_source=intuition.inspired_photo_ids,
        ))

        logger.info(
            "Stage 3: 选题 '%s' 生成成功，%d 张照片",
            parsed.get("title", ""), len(photo_ids),
        )

    return proposals


# ============================================================================
# 数据采集
# ============================================================================

def _fetch_all_photos(go_backend_url: str):
    """从 Go 后端分页获取全部照片数据（通过 SDK），返回 ApiPhotoItem 列表。"""
    photo_api = bksdk.get_photo_api(go_backend_url)
    all_photos = []
    page = 1
    while True:
        resp = photo_api.photo_service_search_photos(page=page, page_size=100)
        items = resp.items or []
        if not items:
            break
        all_photos.extend(items)
        total_pages = resp.total_pages or 0
        if page >= total_pages:
            break
        page += 1

    logger.info("从 Go 后端获取 %d 张照片", len(all_photos))
    return all_photos


def _fetch_stats(go_backend_url: str):
    """获取照片库统计信息（通过 SDK）。"""
    photo_api = bksdk.get_photo_api(go_backend_url)
    return photo_api.photo_service_get_photo_stats()


def _load_cluster_results(cluster_dir: pathlib.Path) -> list[cluster_mod.ClusterResult]:
    """加载所有聚类结果（含主题标签）。"""
    results: list[cluster_mod.ClusterResult] = []
    if not cluster_dir.exists():
        logger.info("聚类目录不存在: %s", cluster_dir)
        return results

    for fp in sorted(cluster_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
            r = cluster_mod._dict_to_result(d)
            results.append(r)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("跳过损坏的聚类结果文件 %s: %s", fp.name, e)

    logger.info("加载 %d 个聚类结果", len(results))
    return results


# ============================================================================
# 主入口
# ============================================================================

def run_suggest(
    cfg,
    go_backend_url: str,
    cluster_dir: pathlib.Path | None = None,
    tracer: tracer_mod.Tracer | None = None,
) -> tuple[list[TopicSuggestion], dict]:
    """
    执行潜在主题识别，返回选题建议列表和元信息。

    三阶段编辑视角提案（随机采样 → RAG 扩展 → LLM 提案）。

    参数:
        cfg: Config 对象
        go_backend_url: Go 后端地址
        cluster_dir: 聚类结果目录，为 None 时尝试默认路径
        tracer: 可选的结构化追踪器，为 None 时内部创建

    返回:
        (suggestions, meta): 建议列表和元信息字典
    """
    t_start = time.time()

    # 内部创建 tracer（如果调用方未传入）
    if tracer is None:
        try:
            tracer = tracer_mod.Tracer(cfg.project_root)
        except Exception:
            tracer = None

    meta: dict = {
        "total_photos": 0,
        "cluster_count": 0,
        "candidates_found": 0,
        "generated_at": datetime.datetime.now().isoformat(),
        "pipeline": "unknown",
        "trace_id": tracer.trace_id if tracer else "",
    }

    # 1. 数据采集
    logger.info("开始数据采集...")
    try:
        photos = _fetch_all_photos(go_backend_url)
    except Exception as e:
        logger.error("获取照片数据失败: %s", e)
        return [], {**meta, "error": f"获取照片数据失败: {e}"}

    if not photos:
        logger.warning("照片库为空，无法生成选题建议")
        return [], {**meta, "error": "照片库为空"}

    meta["total_photos"] = len(photos)

    try:
        stats = _fetch_stats(go_backend_url)
    except Exception as e:
        logger.warning("获取统计信息失败: %s，将跳过时间线分析", e)
        stats = {}

    if cluster_dir is None:
        cluster_dir = cfg.resolve_path("./data/clusters")

    cluster_results = _load_cluster_results(cluster_dir)
    meta["cluster_count"] = len(cluster_results)

    # ════════════════════════════════════════════════════════════════════
    # 三阶段编辑视角提案
    # ════════════════════════════════════════════════════════════════════

    logger.info("=== 三阶段编辑视角提案 ===")

    if tracer:
        tracer.emit("suggest.decision.pipeline", {
            "pipeline": "editorial_three_stage",
        }, module="suggest")

    # Stage 1: 随机采样 → LLM 主题直觉
    intuitions = _stage1_generate_intuitions(cfg, photos, tracer=tracer)

    if not intuitions:
        logger.error("Stage 1 未产出主题直觉")
        return [], {**meta, "error": "Stage 1 未产出主题直觉"}

    # Stage 2+3: 扩展选片 → 完整选题提案
    proposals = _stage3_generate_proposals(cfg, intuitions, photos, tracer=tracer)

    if not proposals:
        logger.error("Stage 3 未产出有效提案")
        return [], {**meta, "error": "Stage 3 未产出有效提案"}

    meta["pipeline"] = "editorial_three_stage"
    meta["candidates_found"] = len(proposals)
    total_duration_ms = int((time.time() - t_start) * 1000)
    if tracer:
        tracer.emit("suggest.complete", {
            "pipeline": "editorial_three_stage",
            "total_suggestions": len(proposals),
            "total_duration_ms": total_duration_ms,
            "stage1_count": len(intuitions),
            "stage3_count": len(proposals),
        }, module="suggest")
    logger.info("生成 %d 个选题建议", len(proposals))
    return proposals, meta


# ============================================================================
# 格式化输出
# ============================================================================

_CATEGORY_LABELS = {
    "editorial_proposal": "📝 编辑视角提案",
}


def format_suggestions(
    suggestions: list[TopicSuggestion],
    meta: dict,
    go_backend_url: str = "",
) -> str:
    """将选题建议格式化为可读的 Markdown 文本。"""
    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("📋 PhotoAgent 选题建议")
    lines.append("=" * 60)
    lines.append(f"生成时间: {meta.get('generated_at', '')}")
    lines.append(f"照片总数: {meta.get('total_photos', 0)}")
    lines.append(f"已有聚类: {meta.get('cluster_count', 0)} 个")
    pipeline = meta.get("pipeline", "")
    if pipeline:
        lines.append(f"生成路径: 编辑视角三阶段")
    lines.append("")

    if not suggestions:
        lines.append("⚠️ 未发现合适的选题建议。")
        if meta.get("error"):
            lines.append(f"原因: {meta['error']}")
        return "\n".join(lines)

    for i, s in enumerate(suggestions, 1):
        cat_label = _CATEGORY_LABELS.get(s.category, s.category)
        lines.append(f"## 建议 {i}: {s.title}")
        lines.append(f"分类: {cat_label}")
        lines.append(f"发布角度: {s.angle}")
        lines.append(f"选题理由: {s.rationale}")
        lines.append(f"推荐照片: {len(s.photo_ids)} 张")
        if go_backend_url and s.photo_ids:
            lines.append("")
            for pid in s.photo_ids[:6]:
                lines.append(f"  ![]({go_backend_url}/api/v1/photos/{pid}/image)")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)

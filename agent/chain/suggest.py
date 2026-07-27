"""
    潜在主题识别模块。

    定期扫描照片库，通过数据分析 + LLM 生成选题建议。
    识别三类潜在主题：
        - 高频未成组：出现频繁但未被已有聚类覆盖的属性
        - 时间线规律：跨年份的季节性拍摄模式，当年缺失的提醒
        - 稀缺优质：出现少但照片质量较高的题材，建议发展

    用法:
        import chain.suggest as suggest_mod

        suggestions = suggest_mod.run_suggest(cfg, go_backend_url, cluster_dir)
        for s in suggestions:
            print(s.title, s.angle)
"""

import sys
import pathlib


import json
import logging
import datetime
import dataclasses
import typing
import collections

import langchain_core.messages as lc_messages

import utils.backend_sdk as bksdk
import chain.cluster as cluster_mod
import utils.llm_factory as llm_factory

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构
# ============================================================================

@dataclasses.dataclass
class CandidateGroup:
    """分析出的候选选题方向（含具体照片）。"""
    category: str          # "high_freq_ungrouped" | "temporal_pattern" | "scarce_quality"
    photo_ids: list[str]
    photo_count: int
    attributes_summary: str   # 属性摘要文本，供 LLM 理解
    analysis_rationale: str   # 分析依据，供 LLM 参考
    sample_descriptions: list[str]  # 代表照片的 VLM 描述（最多 5 条）
    score: float


@dataclasses.dataclass
class TopicSuggestion:
    """LLM 生成的选题建议。"""
    title: str
    angle: str
    rationale: str
    candidate_index: int
    photo_ids: list[str]
    category: str


# ============================================================================
# LLM Prompt
# ============================================================================

_SUGGEST_SYSTEM_PROMPT = (
    "你是一位摄影选题策划专家。用户照片库经过数据分析，发现了一些潜在选题方向。"
    "请从中选出 3-5 个最有价值的选题，为每个选题生成标题和发布角度。\n\n"
    "选题原则：\n"
    "- 优先选择有故事性、有时间感的选题\n"
    "- 标题 6-12 字，精炼有记忆点（如\"春日花语系列\"\"蓝调时刻合集\"）\n"
    "- 发布角度 30-60 字，说明为什么值得发、怎么发\n"
    "- 选题理由 20-40 字，说明基于什么分析得出\n\n"
    "你必须严格返回一行合法 JSON 数组，不得包含任何其他文字、注释或 markdown 标记。\n"
    '输出格式：[{"title":"...","angle":"...","rationale":"...","candidate_index":0}]'
)


# ============================================================================
# 数据采集
# ============================================================================

def _fetch_all_photos(go_backend_url: str):
    """从 Go 后端分页获取全部照片数据（通过 SDK），返回 ApiPhotoItem 列表。"""
    photo_api = bksdk.get_photo_api(go_backend_url)
    all_photos = []
    page = 1
    while True:
        resp = photo_api.photo_service_search_photos(page=page, page_size=500)
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
    """获取照片库统计信息（通过 SDK），返回 ApiGetPhotoStatsResponse。"""
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
# 分析逻辑
# ============================================================================

def _parse_attr_values(value_str: str) -> list[str]:
    """解析逗号分隔的属性值字符串，返回清洗后的值列表。"""
    if not value_str:
        return []
    return [v.strip() for v in value_str.split(",") if v.strip()]


def _count_attribute_frequencies(photos) -> dict[str, dict[str, int]]:
    """统计各属性维度的值频率。

    返回: {dimension: {value: count}}
    dimensions: objects, colors, scene, lighting, mood
    """
    dims = ["objects", "colors", "scene", "lighting", "mood"]
    freq: dict[str, dict[str, int]] = {d: collections.defaultdict(int) for d in dims}

    for p in photos:
        for dim in dims:
            raw = (getattr(p, dim, "") or "").strip()
            if dim in ("objects", "colors"):
                values = _parse_attr_values(raw)
            else:
                values = [raw] if raw else []

            for v in values:
                if v and len(v) >= 2:  # 过滤过短的无意义值
                    freq[dim][v] += 1

    return {d: dict(f) for d, f in freq.items()}


def _collect_cluster_keywords(cluster_results: list[cluster_mod.ClusterResult]) -> set[str]:
    """从聚类主题标签中提取关键词集合，用于判断属性是否已被覆盖。"""
    keywords: set[str] = set()
    for r in cluster_results:
        for c in r.clusters:
            label = c.label or ""
            desc = c.theme_description or ""
            # 提取中文词汇（2-4 字片段）作为关键词
            text = label + desc
            for i in range(len(text)):
                for length in (2, 3, 4):
                    if i + length <= len(text):
                        keywords.add(text[i:i + length])
    return keywords


def _find_high_freq_ungrouped(
    freq: dict[str, dict[str, int]],
    cluster_keywords: set[str],
    photos,
    min_frequency: int = 3,
) -> list[CandidateGroup]:
    """找出高频但未被聚类覆盖的属性值，构建候选组。"""
    candidates: list[CandidateGroup] = []

    for dim, values in freq.items():
        for value, count in sorted(values.items(), key=lambda x: -x[1]):
            if count < min_frequency:
                continue

            # 检查是否被已有聚类覆盖
            covered = any(kw in value or value in kw for kw in cluster_keywords)
            if covered:
                continue

            # 找出具有此属性的照片
            matching = []
            for p in photos:
                raw = (getattr(p, dim, "") or "").strip()
                if dim in ("objects", "colors"):
                    pvals = _parse_attr_values(raw)
                else:
                    pvals = [raw] if raw else []

                if value in pvals:
                    matching.append(p)

            if len(matching) < 2:
                continue

            # 按质量排序：有描述优先
            matching.sort(key=lambda p: (1 if (p.description or "") else 0), reverse=True)

            photo_ids = [p.id for p in matching[:15]]
            sample_descs = [
                (p.description or "无描述")[:120]
                for p in matching[:5]
            ]

            dim_labels = {
                "objects": "主体", "colors": "色调", "scene": "场景",
                "lighting": "光线", "mood": "情绪",
            }
            score = count / max(freq[dim].values())  # 归一化频率

            candidates.append(CandidateGroup(
                category="high_freq_ungrouped",
                photo_ids=photo_ids,
                photo_count=len(matching),
                attributes_summary=f"{dim_labels.get(dim, dim)}={value}（共 {count} 张）",
                analysis_rationale=f"'{value}' 出现 {count} 次，频率较高但未被现有主题覆盖",
                sample_descriptions=sample_descs,
                score=score,
            ))

    # 按 score 降序，取前 10
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:10]


def _find_temporal_patterns(
    photos,
    stats,
    freq: dict[str, dict[str, int]],
) -> list[CandidateGroup]:
    """发现时间线规律：跨年份的季节性拍摄模式。"""
    candidates: list[CandidateGroup] = []

    # 按月份分组照片
    monthly_photos: dict[int, list] = collections.defaultdict(list)
    for p in photos:
        shot_at = p.shot_at or ""
        if not shot_at:
            continue
        try:
            dt = datetime.datetime.fromisoformat(shot_at.replace("Z", "+00:00"))
            monthly_photos[dt.month].append(p)
        except (ValueError, TypeError):
            continue

    if not monthly_photos:
        return candidates

    current_year = datetime.datetime.now().year

    # 对每个月，检查是否有跨年份的规律
    for month in sorted(monthly_photos.keys()):
        month_pics = monthly_photos[month]
        if len(month_pics) < 3:
            continue

        # 统计该月的属性频率
        month_freq = _count_attribute_frequencies(month_pics)
        total_freq = freq

        # 找出该月相对突出的属性（占比显著高于全局）
        for dim, mf in month_freq.items():
            for value, mcount in mf.items():
                if mcount < 2:
                    continue
                global_count = total_freq.get(dim, {}).get(value, 0)
                if global_count == 0:
                    continue

                # 检查是否有跨年份规律
                years_with_attr: set[int] = set()
                all_years: set[int] = set()
                for p in month_pics:
                    shot_at = p.shot_at or ""
                    if not shot_at:
                        continue
                    try:
                        dt = datetime.datetime.fromisoformat(shot_at.replace("Z", "+00:00"))
                        all_years.add(dt.year)
                        raw = (getattr(p, dim, "") or "").strip()
                        if dim in ("objects", "colors"):
                            pvals = _parse_attr_values(raw)
                        else:
                            pvals = [raw] if raw else []
                        if value in pvals:
                            years_with_attr.add(dt.year)
                    except (ValueError, TypeError):
                        continue

                # 需要至少 2 个不同年份才有规律
                if len(years_with_attr) < 2:
                    continue

                # 检查当前年份是否缺失
                missing_current_year = current_year not in years_with_attr

                month_name = f"{month}月"
                month_ratio = mcount / len(month_pics)
                global_ratio = global_count / max(len(photos), 1)
                lift = month_ratio / max(global_ratio, 0.001)

                if lift < 1.5 and not missing_current_year:
                    continue

                dim_labels = {
                    "objects": "主体", "colors": "色调", "scene": "场景",
                    "lighting": "光线", "mood": "情绪",
                }

                matching = [p for p in month_pics if _photo_has_attr(p, dim, value)]
                matching.sort(
                    key=lambda p: (1 if (p.description or "") else 0),
                    reverse=True,
                )

                photo_ids = [p.id for p in matching[:15]]
                sample_descs = [
                    (p.description or "无描述")[:120]
                    for p in matching[:5]
                ]

                if missing_current_year:
                    rationale = (
                        f"{', '.join(str(y) for y in sorted(years_with_attr))} 年"
                        f"的 {month_name} 都拍了 '{value}'，{current_year} 年尚未出现"
                    )
                    score = lift * 1.5  # 缺失当年加权
                else:
                    rationale = (
                        f"{', '.join(str(y) for y in sorted(years_with_attr))} 年"
                        f"的 {month_name} 都出现了 '{value}'，有季节性规律"
                    )
                    score = lift

                candidates.append(CandidateGroup(
                    category="temporal_pattern",
                    photo_ids=photo_ids,
                    photo_count=len(matching),
                    attributes_summary=(
                        f"{month_name} | {dim_labels.get(dim, dim)}={value}"
                        f"（该月 {mcount} 张，全局 {global_count} 张）"
                    ),
                    analysis_rationale=rationale,
                    sample_descriptions=sample_descs,
                    score=score,
                ))

    # 去重并排序
    seen_keys: set[str] = set()
    deduped: list[CandidateGroup] = []
    for c in sorted(candidates, key=lambda x: x.score, reverse=True):
        key = c.attributes_summary
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(c)

    return deduped[:10]


def _photo_has_attr(photo, dim: str, value: str) -> bool:
    """检查照片是否具有指定属性值。"""
    raw = (getattr(photo, dim, "") or "").strip()
    if dim in ("objects", "colors"):
        return value in _parse_attr_values(raw)
    return raw == value


def _find_scarce_quality(
    freq: dict[str, dict[str, int]],
    cluster_results: list[cluster_mod.ClusterResult],
    photos,
    max_frequency: int = 5,
) -> list[CandidateGroup]:
    """找出现频率低但可能在聚类中凝聚度较高的属性，建议发展。"""
    candidates: list[CandidateGroup] = []

    # 构建 cluster 中的 photo_id → coherence 映射
    photo_coherence: dict[str, float] = {}
    for r in cluster_results:
        for c in r.clusters:
            for p in c.photos:
                if p.photo_id not in photo_coherence:
                    photo_coherence[p.photo_id] = c.coherence_score

    for dim, values in freq.items():
        for value, count in values.items():
            if count < 2 or count > max_frequency:
                continue

            # 找出具有此属性的照片
            matching = [p for p in photos if _photo_has_attr(p, dim, value)]
            if len(matching) < 2:
                continue

            # 计算平均质量分：有描述 +1，在聚类中按凝聚度加分
            quality_scores: list[float] = []
            for p in matching:
                score = 0.0
                if (p.description or "").strip():
                    score += 0.3
                pid = p.id or ""
                if pid in photo_coherence:
                    score += photo_coherence[pid]
                quality_scores.append(score)

            avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0

            # 需要一定的平均质量
            if avg_quality < 0.2:
                continue

            # 按质量排序
            paired = list(zip(matching, quality_scores))
            paired.sort(key=lambda x: x[1], reverse=True)
            matching_sorted = [p for p, _ in paired]

            photo_ids = [p.id for p in matching_sorted[:15]]
            sample_descs = [
                (p.description or "无描述")[:120]
                for p in matching_sorted[:5]
            ]

            dim_labels = {
                "objects": "主体", "colors": "色调", "scene": "场景",
                "lighting": "光线", "mood": "情绪",
            }

            rarity_score = 1.0 / max(count, 1)
            score = avg_quality * rarity_score

            candidates.append(CandidateGroup(
                category="scarce_quality",
                photo_ids=photo_ids,
                photo_count=len(matching),
                attributes_summary=(
                    f"{dim_labels.get(dim, dim)}={value}"
                    f"（仅 {count} 张，质量分 {avg_quality:.2f}）"
                ),
                analysis_rationale=(
                    f"'{value}' 仅出现 {count} 次，稀有但照片质量不错，"
                    f"可考虑作为差异化选题"
                ),
                sample_descriptions=sample_descs,
                score=score,
            ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:10]


# ============================================================================
# LLM 生成
# ============================================================================

def _build_suggest_prompt(
    total_photos: int,
    cluster_summary: str,
    candidates: list[CandidateGroup],
) -> str:
    """构建选题建议的 LLM prompt。"""
    parts: list[str] = []

    parts.append(f"## 照片库概况\n- 总照片数：{total_photos}\n- 已有聚类主题：{cluster_summary}\n")

    parts.append("## 候选选题方向\n")
    for i, c in enumerate(candidates):
        parts.append(f"### 候选 {i}（{c.category}）")
        parts.append(f"- 属性特征：{c.attributes_summary}")
        parts.append(f"- 照片数量：{c.photo_count}")
        parts.append(f"- 分析依据：{c.analysis_rationale}")
        if c.sample_descriptions:
            parts.append("- 代表照片描述：")
            for desc in c.sample_descriptions[:3]:
                parts.append(f"  - {desc}")
        parts.append("")

    return "\n".join(parts)


def _parse_suggest_response(raw: str) -> list[dict]:
    """解析 LLM 返回的选题建议 JSON。"""
    import re

    raw = raw.strip()

    # 1. 尝试直接解析
    attempts: list[str] = [raw]
    # 去掉可能的 markdown 代码块
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        attempts.append("\n".join(lines).strip())

    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and "title" in parsed:
                return [parsed]
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. 尝试正则提取 JSON 数组
    m = re.search(r'\[\s*\{.*\}\s*\]', raw, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group())
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. 尝试提取单个对象再组装
    objects = re.findall(r'\{[^}]+\}', raw)
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

    logger.warning("无法解析 LLM 选题建议响应: %s", raw[:300])
    return []


# ============================================================================
# 主入口
# ============================================================================

def run_suggest(
    cfg,
    go_backend_url: str,
    cluster_dir: pathlib.Path | None = None,
) -> tuple[list[TopicSuggestion], dict]:
    """
    执行潜在主题识别，返回选题建议列表和元信息。

    参数:
        cfg: Config 对象
        go_backend_url: Go 后端地址
        cluster_dir: 聚类结果目录，为 None 时尝试默认路径

    返回:
        (suggestions, meta): 建议列表和元信息字典
    """
    meta: dict = {
        "total_photos": 0,
        "cluster_count": 0,
        "candidates_found": 0,
        "generated_at": datetime.datetime.now().isoformat(),
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

    # 解析 cluster_dir
    if cluster_dir is None:
        cluster_dir = cfg.resolve_path("./data/clusters")

    cluster_results = _load_cluster_results(cluster_dir)
    meta["cluster_count"] = len(cluster_results)

    # 2. 分析
    logger.info("开始数据分析...")
    freq = _count_attribute_frequencies(photos)
    # 诊断日志：统计各维度属性值分布
    for dim, values in freq.items():
        if values:
            top3 = sorted(values.items(), key=lambda x: -x[1])[:3]
            logger.info("属性维度 [%s]: %d 个不同值, top3=%s", dim, len(values), top3)
        else:
            logger.warning("属性维度 [%s]: 无数据", dim)
    cluster_keywords = _collect_cluster_keywords(cluster_results)

    all_candidates: list[CandidateGroup] = []

    # 2a. 高频未成组
    high_freq = _find_high_freq_ungrouped(freq, cluster_keywords, photos)
    all_candidates.extend(high_freq)
    if high_freq:
        logger.info("高频未成组候选: %d 个", len(high_freq))
    else:
        logger.warning("高频未成组: 无候选，可能原因：属性值为空、频率不足 min_frequency=3、或均被已有聚类覆盖")

    # 2b. 时间线规律
    temporal = _find_temporal_patterns(photos, stats, freq)
    all_candidates.extend(temporal)
    if temporal:
        logger.info("时间线规律候选: %d 个", len(temporal))
    else:
        logger.warning("时间线规律: 无候选，可能原因：缺少 shot_at 时间信息、月份照片不足 3 张、或无跨年份规律")

    # 2c. 稀缺优质
    scarce = _find_scarce_quality(freq, cluster_results, photos)
    all_candidates.extend(scarce)
    if scarce:
        logger.info("稀缺优质候选: %d 个", len(scarce))
    else:
        logger.warning("稀缺优质: 无候选，可能原因：属性值为空、频率不在 [2, max_frequency=5] 范围、或照片质量分不足 0.2")

    # 合并去重，选 top 15 送给 LLM
    all_candidates.sort(key=lambda c: c.score, reverse=True)
    top_candidates = all_candidates[:15]
    meta["candidates_found"] = len(top_candidates)

    if not top_candidates:
        logger.warning("未发现候选选题方向")
        return [], {**meta, "error": "未发现候选选题方向"}

    # 3. LLM 生成
    logger.info("调用 LLM 生成选题建议...")

    # 构建聚类摘要
    cluster_labels: list[str] = []
    for r in cluster_results:
        for c in r.clusters:
            if c.label and c.label != f"聚类 {c.cluster_id}":
                cluster_labels.append(f"{c.label}（{c.size}张）")
    cluster_summary = ", ".join(cluster_labels[:20]) if cluster_labels else "暂无"

    prompt_text = _build_suggest_prompt(len(photos), cluster_summary, top_candidates)

    llm = llm_factory.create_llm(cfg, temperature=0.7)
    messages = [
        lc_messages.SystemMessage(content=_SUGGEST_SYSTEM_PROMPT),
        lc_messages.HumanMessage(content=prompt_text),
    ]

    try:
        resp = llm.invoke(messages)
        raw = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as e:
        logger.exception("LLM 调用失败")
        return [], {**meta, "error": f"LLM 调用失败: {e}"}

    parsed = _parse_suggest_response(raw)
    if not parsed:
        return [], {**meta, "error": "LLM 未返回有效选题建议"}

    # 4. 组装结果
    suggestions: list[TopicSuggestion] = []
    for item in parsed[:5]:  # 最多 5 个
        idx = item.get("candidate_index", 0)
        try:
            idx = int(idx)
        except (ValueError, TypeError):
            idx = 0

        if 0 <= idx < len(top_candidates):
            candidate = top_candidates[idx]
        else:
            candidate = top_candidates[0] if top_candidates else None

        if candidate is None:
            continue

        suggestions.append(TopicSuggestion(
            title=item.get("title", "未命名选题"),
            angle=item.get("angle", ""),
            rationale=item.get("rationale", ""),
            candidate_index=idx,
            photo_ids=candidate.photo_ids[:10],
            category=candidate.category,
        ))

    logger.info("生成 %d 个选题建议", len(suggestions))
    return suggestions, meta


# ============================================================================
# 格式化输出
# ============================================================================

_CATEGORY_LABELS = {
    "high_freq_ungrouped": "🔍 高频未成组",
    "temporal_pattern": "📅 时间线规律",
    "scarce_quality": "💎 稀缺优质",
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

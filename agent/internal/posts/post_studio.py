"""
    图文工坊文案生成模块。

    把照片的 VLM 描述组织成四层提示词，交给 LLM 生成/润色帖子文案：

        L1 系统提示词（后端固定）
        L2 风格层（下拉选择/自定义）
        L3 照片上下文层（后端拼接，提取式摘要）
        L4 用户要求层（前端输入，可留空）

    用法:
        import internal.posts.post_studio as post_studio

        photos = post_studio.fetch_photos(go_backend_url, photo_ids)
        title, content, warnings = post_studio.generate_post(cfg, photos, style, prompt)
"""

import json
import re
import logging

import langchain_core.messages as lc_messages

import infra.backend_sdk as bksdk
import infra.llm_factory as llm_factory
import internal.topics.suggest as suggest_mod

logger = logging.getLogger(__name__)


# ============================================================================
# L1 系统提示词 + L2 风格层
# ============================================================================

SYSTEM_PROMPT_GENERATE = (
    "你是一位专业的摄影帖子文案创作者。\n"
    "你会收到一组按发布顺序排列的照片客观描述。这些描述来自视觉模型，是事实记录，不是可以直接照抄的文案素材。\n\n"
    "写作要求：\n"
    "- 语言为中文，面向社交媒体发布\n"
    "- 标题 10 到 20 字\n"
    "- 正文 150 到 400 字，段落短，每段 2 到 4 句\n"
    "- 可用少量 emoji，但不要堆砌\n\n"
    "防幻觉约束：\n"
    "- 只能基于照片描述和用户要求写作，不得虚构描述中不存在的地点、人物、事件\n"
    "- 地名、店名、具体日期若描述中没有，就不要编造，用模糊表述带过\n"
    "- 不要用「照片1」「图2」这类编号指代，把画面自然融入叙事\n"
    "- 照片的排列顺序就是叙事顺序，按这个顺序推进\n\n"
    "反寒暄约束：不要输出「以下是为您生成的文案」之类的开场白或结尾说明。\n\n"
    "输出契约：严格输出一个 JSON 对象 {\"title\": \"...\", \"content\": \"...\"}，"
    "不要加代码围栏，content 内用 \\n 分段。"
)

SYSTEM_PROMPT_REFINE = (
    "你是一位专业的文案编辑。\n"
    "你会收到一篇待润色的草稿，以及这篇草稿的配图照片描述。\n"
    "请在保留原文结构、段落数和核心意图的基础上润色优化，只改善表达，不要大幅改动。\n\n"
    "写作要求：\n"
    "- 语言为中文，面向社交媒体发布\n"
    "- 标题 10 到 20 字\n"
    "- 正文段落短，每段 2 到 4 句\n\n"
    "防幻觉约束：\n"
    "- 可参考照片画面细节改善表达，但不要新增草稿里没有的事实\n"
    "- 地名、店名、具体日期若草稿和照片描述中都没有，就不要编造\n\n"
    "反寒暄约束：不要输出「以下是为您润色的文案」之类的开场白或结尾说明。\n\n"
    "输出契约：严格输出一个 JSON 对象 {\"title\": \"...\", \"content\": \"...\"}，"
    "不要加代码围栏，content 内用 \\n 分段。"
)

# 风格 → 可执行的语气指令。用户自定义文本原样透传。
STYLE_MAP = {
    "literary": "文艺：语言优美细腻，多用意象和通感，重意境与情绪流动，少用感叹号",
    "documentary": "纪实：客观克制，重细节和事件本身，按时间或空间线索推进，不抒情",
    "casual": "轻松：口语化，像跟朋友分享，可用网络语和 emoji，节奏跳脱",
    "guide": "攻略：实用优先，给出可复用的信息，如机位、时段、光线条件、注意事项",
}

# 摘要字段的渲染顺序（拍摄时间由 shot_at + time_of_day 单独拼装）
_FIELD_ORDER = ("主体", "动作", "场景", "天气", "光线", "色调", "氛围", "画面文字", "概述")
_BRIEF_FIELDS = ("主体", "概述")
_MAX_FULL_PHOTOS = 20


# ============================================================================
# 数据获取
# ============================================================================

def fetch_photos(go_backend_url: str, photo_ids: list[str]):
    """通过 SDK 逐张获取照片详情，返回 ApiPhotoItem 列表（顺序与 photo_ids 一致）。"""
    api = bksdk.get_photo_api(go_backend_url)
    photos = []
    for pid in photo_ids:
        detail = api.photo_service_get_photo_detail(pid)
        photo = detail.photo
        if photo is not None:
            photos.append(photo)
    return photos


# ============================================================================
# L3 照片上下文层：VLM JSON → 提取式摘要
# ============================================================================

def _extract_json_block(text: str) -> dict | None:
    """从带 markdown 围栏的文本中提取首个 JSON 对象，失败返回 None。"""
    text = (text or "").strip()
    if not text:
        return None

    attempts = [text]
    if text.startswith("```"):
        lines = [ln for ln in text.split("\n") if not ln.strip().startswith("```")]
        attempts.append("\n".join(lines).strip())

    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group())
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _join_nonempty(parts: list[str], sep: str) -> str:
    return sep.join(p for p in parts if p)


def _summarize_vlm_description(desc: str) -> dict:
    """把 VLM 原始 JSON 解析为摘要字段字典。

    返回字典的 key 与渲染标签一致，额外含 "time_of_day" 供拍摄时间拼接。
    非 JSON（老数据/换过 VLM 提示词）时降级为原始文本截断 300 字。
    """
    data = _extract_json_block(desc)
    if data is None:
        return {"概述": (desc or "").strip()[:300]}

    subject = data.get("subject") or {}
    scene = data.get("scene") or {}
    lighting = data.get("lighting") or {}
    palette = data.get("color_palette") or {}

    main_objects = subject.get("main_objects")
    if isinstance(main_objects, list):
        subject_text = "、".join(str(x).strip() for x in main_objects if x)
    elif main_objects:
        subject_text = str(main_objects).strip()
    else:
        subject_text = ""

    attrs = subject.get("attributes") or {}
    action = (attrs.get("pose/action") or "").strip()

    env = (scene.get("environment") or "").strip()
    setting = (scene.get("setting") or "").strip()
    scene_text = _join_nonempty([env, setting], "，")
    weather = (scene.get("weather") or "").strip()
    time_of_day = (scene.get("time_of_day") or "").strip()

    light_source = (lighting.get("source") or "").strip()
    brightness = (lighting.get("brightness") or "").strip()
    light_text = _join_nonempty([light_source, brightness], "，")

    tone = (palette.get("overall_tone") or "").strip()
    mood = (data.get("mood") or "").strip()
    text_sym = (data.get("text_and_symbols") or "").strip()
    summary = (data.get("overall_summary") or "").strip()

    fields = {
        "time_of_day": time_of_day,
        "主体": subject_text,
        "动作": action,
        "场景": scene_text,
        "天气": weather,
        "光线": light_text,
        "色调": tone,
        "氛围": mood,
        "画面文字": text_sym,
        "概述": summary,
    }
    return {k: v for k, v in fields.items() if v}


def _render_exif(photo) -> str:
    """攻略风格附加的相机参数行，无参数时返回空字符串。"""
    cam = _join_nonempty(
        [(getattr(photo, "brand", "") or "").strip(), (getattr(photo, "model", "") or "").strip()],
        " ",
    )
    parts = [cam]
    for attr in ("lens", "focal_length", "aperture"):
        parts.append((getattr(photo, attr, "") or "").strip())
    iso = getattr(photo, "iso", 0) or 0
    if iso:
        parts.append(f"ISO {iso}")
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return "参数：" + " / ".join(parts)


def _render_photo_block(idx: int, photo, style: str, brief: bool) -> str:
    """渲染单张照片段落。brief 模式只保留 拍摄时间 / 主体 / 概述。"""
    desc = (getattr(photo, "description", "") or "").strip()
    fields = _summarize_vlm_description(desc)

    lines = [f"### 照片 {idx}"]

    time_of_day = fields.get("time_of_day", "")
    shot_date = suggest_mod._parse_shot_date(getattr(photo, "shot_at", "") or "")
    if shot_date or time_of_day:
        date_part = shot_date.isoformat() if shot_date else ""
        lines.append("拍摄时间：" + _join_nonempty([date_part, time_of_day], " "))

    labels = _BRIEF_FIELDS if brief else _FIELD_ORDER
    for label in labels:
        val = fields.get(label, "")
        if val:
            lines.append(f"{label}：{val}")

    if not brief and style == "guide":
        exif = _render_exif(photo)
        if exif:
            lines.append(exif)

    return "\n".join(lines)


def build_photo_context(photos, style: str) -> str:
    """拼接 L3：列表前置时间跨度汇总 + 每张照片摘要段落。"""
    if not photos:
        return ""

    brief = len(photos) > _MAX_FULL_PHOTOS
    header = [f"## 照片素材（共 {len(photos)} 张，按发布顺序排列）"]

    shot_dates = []
    for p in photos:
        d = suggest_mod._parse_shot_date(getattr(p, "shot_at", "") or "")
        if d:
            shot_dates.append(d)
    dates = sorted(set(shot_dates))
    if len(dates) == 1:
        header.append(f"拍摄日期：{dates[0].isoformat()}")
    elif len(dates) >= 2:
        span = (dates[-1] - dates[0]).days + 1
        header.append(f"拍摄时间跨度：{dates[0].isoformat()} 至 {dates[-1].isoformat()}，跨 {span} 天")

    blocks = ["\n".join(header)]
    for i, p in enumerate(photos, 1):
        blocks.append(_render_photo_block(i, p, style, brief))
    return "\n\n".join(blocks)


# ============================================================================
# L4 用户要求层 + 输出解析
# ============================================================================

def _build_user_requirement(user_prompt: str) -> str:
    p = (user_prompt or "").strip()
    if not p:
        return ""
    return f"## 本次的额外要求\n{p}"


def _repair_truncated_json(raw: str) -> dict | None:
    """LLM 偶发漏掉收尾大括号，补齐 1 到 3 个后重试解析，失败返回 None。

    不放大容错范围：只修「对象少了结尾 }」这一种已观察到的输出漂移，
    其余格式问题仍交由 _parse_post_response 抛错暴露。
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = [ln for ln in text.split("\n") if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    if not text.startswith("{"):
        return None
    for _ in range(3):
        text += "}"
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _parse_post_response(raw: str) -> tuple[str, str] | None:
    """解析 LLM 返回的 JSON 契约，复用 suggest 的容错解析，失败返回 None。"""
    items = suggest_mod._parse_llm_json_response(raw, "图文工坊")
    if not items:
        repaired = _repair_truncated_json(raw)
        if repaired is not None:
            items = [repaired]
    if not items:
        return None
    item = items[0]
    title = (item.get("title") or "").strip()
    content = (item.get("content") or "").strip()
    if not title and not content:
        return None
    return title, content


# ============================================================================
# 主流程
# ============================================================================

def _split_described(photos) -> tuple[list, int]:
    """拆分有描述/无描述照片，返回 (有描述照片列表, 缺描述数量)。"""
    described = []
    missing = 0
    for p in photos:
        desc = (getattr(p, "description", "") or "").strip()
        if desc:
            described.append(p)
        else:
            missing += 1
    return described, missing


def _style_hint(style: str) -> str:
    if not style:
        return ""
    return STYLE_MAP.get(style, style)


def _build_system_msg(base: str, style: str) -> str:
    hint = _style_hint(style)
    if hint:
        return base + f"\n\n风格要求：{hint}"
    return base


def _invoke_llm(cfg, system_msg: str, user_msg: str, temperature: float) -> str:
    llm = llm_factory.create_llm(cfg, temperature=temperature)
    resp = llm.invoke([
        lc_messages.SystemMessage(content=system_msg),
        lc_messages.HumanMessage(content=user_msg),
    ])
    return (resp.content if hasattr(resp, "content") else str(resp)) or ""


def generate_post(cfg, photos, style: str, user_prompt: str) -> tuple[str, str, list[str]]:
    """生成模式主流程。返回 (title, content, warnings)。

    全部照片无描述时抛 ValueError，AI 返回格式异常时抛 RuntimeError。
    """
    described, missing = _split_described(photos)
    if not described:
        raise ValueError(
            f"所选 {len(photos)} 张照片都还没有 AI 描述，请先在图片管理中生成描述后再来生成文案"
        )
    warnings = [f"{missing} 张照片缺少 AI 描述，未参与文案生成"] if missing else []

    photo_context = build_photo_context(described, style)
    requirement = _build_user_requirement(user_prompt)

    system_msg = _build_system_msg(SYSTEM_PROMPT_GENERATE, style)
    user_parts = [photo_context]
    if requirement:
        user_parts.append(requirement)
    user_msg = "\n\n".join(user_parts)

    logger.info(
        "图文工坊生成：照片 %d 张，缺描述 %d 张，提示词 %d 字符",
        len(described), missing, len(system_msg) + len(user_msg),
    )
    logger.debug("图文工坊生成提示词：\n%s\n\n%s", system_msg, user_msg)

    raw = _invoke_llm(cfg, system_msg, user_msg, temperature=0.7).strip()
    result = _parse_post_response(raw)
    if result is None:
        logger.warning("图文工坊生成 AI 返回格式异常: %s", raw[:300])
        raise RuntimeError("AI 返回格式异常，请重试")
    title, content = result
    return title, content, warnings


def refine_post(cfg, photos, style: str, content: str) -> tuple[str, str, list[str]]:
    """润色模式主流程。返回 (title, content, warnings)。

    photo_ids 为空时不带照片上下文，仅按草稿润色。
    """
    described, missing = _split_described(photos)
    if photos and not described:
        raise ValueError(
            f"所选 {len(photos)} 张照片都还没有 AI 描述，请先在图片管理中生成描述后再来生成文案"
        )
    warnings = [f"{missing} 张照片缺少 AI 描述，未参与文案生成"] if missing else []

    system_msg = _build_system_msg(SYSTEM_PROMPT_REFINE, style)

    user_parts = []
    photo_context = build_photo_context(described, style)
    if photo_context:
        user_parts.append(
            "以下照片是这篇草稿的配图，润色时可参考画面细节，但不要新增草稿里没有的事实。\n\n"
            + photo_context
        )
    user_parts.append(f"## 待润色的草稿\n{content}")
    user_msg = "\n\n".join(user_parts)

    logger.info(
        "图文工坊润色：照片 %d 张，缺描述 %d 张，提示词 %d 字符",
        len(described), missing, len(system_msg) + len(user_msg),
    )
    logger.debug("图文工坊润色提示词：\n%s\n\n%s", system_msg, user_msg)

    raw = _invoke_llm(cfg, system_msg, user_msg, temperature=0.5).strip()
    result = _parse_post_response(raw)
    if result is None:
        logger.warning("图文工坊润色 AI 返回格式异常: %s", raw[:300])
        raise RuntimeError("AI 返回格式异常，请重试")
    title, content_out = result
    return title, content_out, warnings

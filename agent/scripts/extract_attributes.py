"""
    VLM 描述结构化提取脚本。

    从 descriptions.json 读取照片描述，使用 LLM 提取结构化属性：
    objects / colors / scene / lighting / mood / composition，
    存入 attributes.json，供 index_photos.py 写入 Chroma metadata。

    用法:
        cd agent
        python scripts/extract_attributes.py -c /path/to/config.yaml
        python scripts/extract_attributes.py -c /path/to/config.yaml --force  # 强制重新提取全部
"""

import argparse
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import langchain_core.prompts as lc_prompts
import langchain_openai as lc_openai

import config
import utils.token_tracker as token_tracker


EXTRACT_PROMPT = (
    "你是一位摄影分析专家。根据以下照片描述文本，提取 6 个维度的结构化标签。\n\n"
    "规则:\n"
    "- objects: 画面中的主体物体/人物，逗号分隔，如 \"猫,沙发,窗户\"\n"
    "- colors: 主色调，逗号分隔，如 \"暖黄色,深蓝\"\n"
    "- scene: 场景类型，选一个: indoor/outdoor/urban/nature/water/mountain/street/night/studio\n"
    "- lighting: 光线特征，选一个: bright/dim/soft/harsh/golden_hour/backlit/artificial\n"
    "- mood: 情感氛围，选一个: warm/calm/dramatic/melancholy/joyful/serious/mysterious\n"
    "- composition: 构图特点，逗号分隔，如 \"三分法,浅景深,前景遮挡\"\n\n"
    "请严格按照以下 JSON 格式输出，不要包含任何额外文字:\n"
    '{{"objects": "...", "colors": "...", "scene": "...", "lighting": "...", "mood": "...", "composition": "..."}}\n\n'
    "描述文本:\n{description}\n\n"
    "JSON:"
)


def _extract_attributes(
    llm: lc_openai.ChatOpenAI,
    description: str,
) -> dict:
    """对单条描述提取结构化属性。"""
    prompt = lc_prompts.ChatPromptTemplate.from_messages([
        ("human", EXTRACT_PROMPT),
    ])
    chain = prompt | llm

    # 截断过长的描述，LLM 不需要完整文本也能提取属性
    truncated = description[:3000] if len(description) > 3000 else description
    response = chain.invoke({"description": truncated})
    raw = str(response.content).strip()

    # 清理 markdown 代码块包裹
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        attrs = json.loads(raw)
    except json.JSONDecodeError:
        # 容错：尝试提取第一个 JSON 对象
        import re
        match = re.search(r'\{[^}]+\}', raw)
        if match:
            try:
                attrs = json.loads(match.group())
            except json.JSONDecodeError:
                return {}
        else:
            return {}

    # 确保所有字段存在
    for key in ("objects", "colors", "scene", "lighting", "mood", "composition"):
        attrs.setdefault(key, "")

    return attrs


def _load_attributes(attr_path: pathlib.Path) -> dict:
    """加载已有属性文件，不存在则返回空字典。"""
    if not attr_path.exists():
        return {}
    with open(attr_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_attributes(attr_path: pathlib.Path, data: dict) -> None:
    """保存属性到磁盘。"""
    attr_path.parent.mkdir(parents=True, exist_ok=True)
    with open(attr_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="VLM 描述结构化属性提取")
    parser.add_argument(
        "-c", "--config", required=True, help="配置文件路径"
    )
    parser.add_argument(
        "--force", action="store_true", help="强制重新提取全部照片属性"
    )
    args = parser.parse_args()

    cfg = config.Config(args.config)
    cfg.check_api_key()

    # 读取 descriptions.json
    desc_path = cfg.resolve_path(cfg.descriptions_path)
    if not desc_path.exists():
        print(f"❌ 描述文件不存在: {desc_path}")
        return

    with open(desc_path, "r", encoding="utf-8") as f:
        descriptions = json.load(f)

    print(f"📖 已加载 {len(descriptions)} 张照片描述")

    # 属性文件路径
    attr_path = cfg.resolve_path("./data/attributes.json")
    existing = _load_attributes(attr_path)

    # 确定需要处理的照片
    to_process: list[str] = []
    if args.force:
        to_process = list(descriptions.keys())
    else:
        to_process = [pid for pid in descriptions if pid not in existing]

    skip_count = len(descriptions) - len(to_process)
    print(f"⏭️  跳过（已有属性）: {skip_count} 张")
    print(f"🔄 待提取: {len(to_process)} 张")
    print()

    if not to_process:
        print("✅ 所有照片属性已是最新")
        return

    # 初始化 LLM（低 temperature 保证一致性）
    llm = lc_openai.ChatOpenAI(
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,  # type: ignore[arg-type]
        base_url=cfg.llm_base_url,
        temperature=0.1,
        streaming=False,
    )

    tracker = token_tracker.TokenTracker(":memory:")
    cb = token_tracker.TokenCallback(tracker)

    for i, photo_id in enumerate(to_process, 1):
        info = descriptions[photo_id]
        desc = info.get("description", "") if isinstance(info, dict) else str(info)
        if not desc:
            continue

        print(f"[{i}/{len(to_process)}] 提取: {photo_id}")

        try:
            attrs = _extract_attributes(llm, desc)
            if attrs:
                existing[photo_id] = attrs
                # 每 10 张保存一次
                if i % 10 == 0:
                    _save_attributes(attr_path, existing)
                    print(f"  💾 已保存中间结果")
        except Exception as e:
            print(f"  ⚠️ 提取失败: {e}")
            continue

    # 最终保存
    _save_attributes(attr_path, existing)
    print()
    print(f"✅ 属性提取完成，共 {len(existing)} 张")
    print(f"📁 输出: {attr_path}")

    # Token 统计
    summary = tracker.summary(days=0)
    if summary:
        total_input = sum(r["total_input"] for r in summary)
        total_output = sum(r["total_output"] for r in summary)
        print(f"💰 Token 用量: {total_input:,} 入 / {total_output:,} 出")


if __name__ == "__main__":
    main()

"""Smoke test for post_studio.py — verifies core logic functions work correctly."""
from types import SimpleNamespace

import chain.post_studio as ps


VLM_JSON = """```json
{
  "image_type": "photograph",
  "subject": {
    "main_objects": ["一只橘猫", "一个毛线球"],
    "count": 2,
    "attributes": {"color": "橘色", "pose/action": "猫用爪子拨弄毛线球"}
  },
  "scene": {"environment": "室内", "setting": "客厅", "time_of_day": "白天", "weather": null},
  "lighting": {"source": "自然光", "brightness": "明亮", "contrast": "中等"},
  "color_palette": {"dominant_colors": ["橘色"], "overall_tone": "暖色"},
  "composition": {"focus": "中心", "depth": "浅景深", "symmetry": "非对称"},
  "background": {"description": "模糊沙发", "blur": "模糊"},
  "foreground": {"description": "木地板", "overlaps_main": false},
  "text_and_symbols": null,
  "mood": "活泼",
  "overall_summary": "一只橘猫在客厅玩毛线球"
}
```"""


def _photo(shot_at="2025-05-02", description=VLM_JSON, brand="Nikon", model="Z6", lens="35mm", focal_length="35mm", aperture="f/1.8", iso=200):
    return SimpleNamespace(
        id="p1", filename="a.jpg", description=description, shot_at=shot_at,
        brand=brand, model=model, lens=lens, focal_length=focal_length,
        aperture=aperture, iso=iso,
    )


def test_extract_json_block():
    assert ps._extract_json_block(VLM_JSON)["mood"] == "活泼"
    assert ps._extract_json_block('{"a": 1}') == {"a": 1}
    assert ps._extract_json_block("not json") is None
    print("  ✓ _extract_json_block")


def test_summarize_vlm_description():
    fields = ps._summarize_vlm_description(VLM_JSON)
    assert fields["主体"] == "一只橘猫、一个毛线球"
    assert fields["动作"] == "猫用爪子拨弄毛线球"
    assert fields["场景"] == "室内，客厅"
    assert fields["光线"] == "自然光，明亮"
    assert fields["色调"] == "暖色"
    assert fields["氛围"] == "活泼"
    assert fields["概述"] == "一只橘猫在客厅玩毛线球"
    assert fields["time_of_day"] == "白天"
    # 天气为 null，不应出现
    assert "天气" not in fields
    # 丢弃技术字段
    assert "composition" not in fields and "contrast" not in fields

    # 非 JSON 降级为原始文本
    fallback = ps._summarize_vlm_description("这是一段纯文本描述")
    assert fallback["概述"] == "这是一段纯文本描述"
    print("  ✓ _summarize_vlm_description")


def test_render_photo_block():
    block = ps._render_photo_block(1, _photo(), "casual", brief=False)
    assert "### 照片 1" in block
    assert "拍摄时间：2025-05-02 白天" in block
    assert "主体：一只橘猫、一个毛线球" in block
    assert "概述：一只橘猫在客厅玩毛线球" in block
    assert "参数：" not in block  # casual 不含 EXIF

    guide_block = ps._render_photo_block(1, _photo(), "guide", brief=False)
    assert "参数：Nikon Z6 / 35mm / 35mm / f/1.8 / ISO 200" in guide_block

    brief_block = ps._render_photo_block(1, _photo(), "casual", brief=True)
    assert "主体：" in brief_block
    assert "动作：" not in brief_block  # brief 模式只保留主体/概述
    print("  ✓ _render_photo_block")


def test_build_photo_context():
    ctx = ps.build_photo_context([_photo("2025-05-02"), _photo("2025-05-03")], "casual")
    assert "## 照片素材（共 2 张，按发布顺序排列）" in ctx
    assert "拍摄时间跨度：2025-05-02 至 2025-05-03，跨 2 天" in ctx

    same_day = ps.build_photo_context([_photo("2025-05-02")], "casual")
    assert "拍摄日期：2025-05-02" in same_day
    print("  ✓ build_photo_context")


def test_parse_post_response():
    assert ps._parse_post_response('{"title":"标题","content":"正文"}') == ("标题", "正文")
    fenced = '```json\n{"title":"标题","content":"正文第一段\\n第二段"}\n```'
    assert ps._parse_post_response(fenced)[0] == "标题"
    assert ps._parse_post_response("好的，以下是为您生成的文案") is None
    assert ps._parse_post_response('{"title":"","content":""}') is None
    # LLM 偶发漏掉收尾大括号，补齐后仍能解析
    truncated = '{"title":"标题","content":"正文缺结尾"'
    assert ps._parse_post_response(truncated) == ("标题", "正文缺结尾")
    print("  ✓ _parse_post_response")


def test_split_described():
    described, missing = ps._split_described([_photo(), SimpleNamespace(id="p2", description="")])
    assert len(described) == 1 and missing == 1
    print("  ✓ _split_described")


if __name__ == "__main__":
    print("Running post_studio smoke tests...")
    test_extract_json_block()
    test_summarize_vlm_description()
    test_render_photo_block()
    test_build_photo_context()
    test_parse_post_response()
    test_split_described()
    print()
    print("All tests passed!")

"""Smoke test for suggest.py — verifies core logic functions work correctly."""
import sys, pathlib

import chain.suggest as suggest_mod


def test_parse_attr_values():
    assert suggest_mod._parse_attr_values("a, b, c") == ["a", "b", "c"]
    assert suggest_mod._parse_attr_values("") == []
    assert suggest_mod._parse_attr_values("single") == ["single"]
    assert suggest_mod._parse_attr_values(", ,") == []
    print("  ✓ _parse_attr_values")


def test_count_attribute_frequencies():
    photos = [
        {"objects": "人物, 雪山", "colors": "蓝色, 白色", "scene": "户外", "lighting": "自然光", "mood": "宁静"},
        {"objects": "人物, 花卉", "colors": "红色, 绿色", "scene": "户外", "lighting": "逆光", "mood": "温暖"},
        {"objects": "雪山, 水面", "colors": "蓝色, 绿色", "scene": "户外", "lighting": "自然光", "mood": "宁静"},
        {"objects": "建筑", "colors": "灰色", "scene": "城市", "lighting": "夜景", "mood": "冷峻"},
    ]
    freq = suggest_mod._count_attribute_frequencies(photos)
    assert freq["scene"]["户外"] == 3
    assert freq["scene"]["城市"] == 1
    assert freq["mood"]["宁静"] == 2
    assert freq["objects"]["人物"] == 2
    assert freq["colors"]["蓝色"] == 2
    print("  ✓ _count_attribute_frequencies")


def test_photo_has_attr():
    p = {"objects": "人物, 雪山", "colors": "蓝色", "scene": "户外", "lighting": "自然光", "mood": "宁静"}
    assert suggest_mod._photo_has_attr(p, "objects", "人物")
    assert suggest_mod._photo_has_attr(p, "scene", "户外")
    assert not suggest_mod._photo_has_attr(p, "objects", "猫咪")
    assert not suggest_mod._photo_has_attr(p, "mood", "温暖")
    print("  ✓ _photo_has_attr")


def test_collect_cluster_keywords():
    from chain.cluster import ClusterResult, ClusterInfo, ClusterPhoto, ClusterStats
    cluster = ClusterResult(
        id="test1", created_at="2024-01-01", params={},
        stats=ClusterStats(total_photos=10, clustered_photos=8, noise_photos=2, num_clusters=1, duration_seconds=1.0),
        clusters=[ClusterInfo(cluster_id=0, label="雪山风光", theme_description="高原雪山自然景观", size=5, coherence_score=0.8, photos=[])]
    )
    keywords = suggest_mod._collect_cluster_keywords([cluster])
    assert "雪山" in keywords
    assert "风光" in keywords
    print("  ✓ _collect_cluster_keywords")


def test_parse_suggest_response():
    # Valid JSON array
    valid = '[{"title":"春日花语","angle":"角度描述","rationale":"理由","candidate_index":0}]'
    parsed = suggest_mod._parse_suggest_response(valid)
    assert len(parsed) == 1
    assert parsed[0]["title"] == "春日花语"

    # With markdown wrapping
    md = '```json\n[{"title":"测试","angle":"描述","rationale":"理由","candidate_index":1}]\n```'
    parsed2 = suggest_mod._parse_suggest_response(md)
    assert len(parsed2) == 1
    assert parsed2[0]["title"] == "测试"

    # Invalid input
    invalid = "just some text"
    parsed3 = suggest_mod._parse_suggest_response(invalid)
    assert parsed3 == []
    print("  ✓ _parse_suggest_response")


def test_build_suggest_prompt():
    cands = [
        suggest_mod.CandidateGroup(
            category="high_freq_ungrouped",
            photo_ids=["p1", "p2"],
            photo_count=5,
            attributes_summary="场景=户外",
            analysis_rationale="测试理由",
            sample_descriptions=["蓝天白云", "青山绿水"],
            score=0.9,
        )
    ]
    prompt = suggest_mod._build_suggest_prompt(10, "无", cands)
    assert "户外" in prompt
    assert "测试理由" in prompt
    print("  ✓ _build_suggest_prompt")


def test_format_suggestions():
    suggestions = [
        suggest_mod.TopicSuggestion(
            title="测试选题", angle="测试角度", rationale="测试理由",
            candidate_index=0, photo_ids=["p1"], category="high_freq_ungrouped",
        )
    ]
    output = suggest_mod.format_suggestions(
        suggestions, {"total_photos": 10, "cluster_count": 2, "generated_at": "2024-01-01"},
    )
    assert "测试选题" in output
    assert "高频未成组" in output
    print("  ✓ format_suggestions")


if __name__ == "__main__":
    print("Running smoke tests...")
    test_parse_attr_values()
    test_count_attribute_frequencies()
    test_photo_has_attr()
    test_collect_cluster_keywords()
    test_parse_suggest_response()
    test_build_suggest_prompt()
    test_format_suggestions()
    print()
    print("All tests passed!")

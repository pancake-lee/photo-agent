from chain.photo_agent import _collapse_compose_candidates


def test_compose_collapses_burst_group_to_cover():
    result = _collapse_compose_candidates([
        {"id": "a", "burst_group_id": "g"},
        {"id": "b", "burst_group_id": "g", "is_burst_cover": True},
        {"id": "c"},
    ])
    assert [item["id"] for item in result] == ["b", "c"]
    assert result[0]["_group_count"] == 2

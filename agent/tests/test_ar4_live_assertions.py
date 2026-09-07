"""AR4-5 live 回归脚本断言纯函数的离线单测（不触发任何 LLM 调用）。"""

import json
import unittest

import scripts.regression.live.ar4_multiturn_followup as ar4_live


def _summary(**overrides) -> dict:
    base = {
        "turn": 1,
        "question": "找山西旅游第一天的照片并生成发布文案",
        "followup": False,
        "query_type": "runtime",
        "affected": [],
        "answer": "# 山西第一天\n正文",
        "selected_ids": ["b", "c"],
        "clarification": False,
        "terminal_reason": "",
    }
    base.update(overrides)
    return base


class SelectedIdsFromDumpTest(unittest.TestCase):
    def test_extracts_selected_ids(self):
        dump = json.dumps({"artifacts": {"selected_ids": ["b", "c"]}})
        self.assertEqual(ar4_live.selected_ids_from_dump(dump), ["b", "c"])

    def test_empty_and_missing_field(self):
        self.assertEqual(ar4_live.selected_ids_from_dump(""), [])
        self.assertEqual(ar4_live.selected_ids_from_dump(json.dumps({"artifacts": {}})), [])
        self.assertEqual(ar4_live.selected_ids_from_dump(json.dumps({})), [])


class SummarizeTurnTest(unittest.TestCase):
    def test_compresses_route_result(self):
        result = {
            "followup": True,
            "query_type": "runtime",
            "runtime_affected": ["copy"],
            "answer": "改写后的文案",
            "runtime_task_dump": json.dumps({"artifacts": {"selected_ids": ["b", "c"]}}),
            "runtime_clarification": {},
            "runtime_terminal_reason": "",
        }
        summary = ar4_live.summarize_turn(2, "不要那么文艺", result)
        self.assertTrue(summary["followup"])
        self.assertEqual(summary["affected"], ["copy"])
        self.assertEqual(summary["selected_ids"], ["b", "c"])
        self.assertFalse(summary["clarification"])

    def test_missing_keys_default_safely(self):
        summary = ar4_live.summarize_turn(1, "问题", {})
        self.assertFalse(summary["followup"])
        self.assertEqual(summary["query_type"], "")
        self.assertEqual(summary["selected_ids"], [])


class FirstTurnAssertionTest(unittest.TestCase):
    def test_good_first_turn_passes(self):
        self.assertEqual(ar4_live.assert_first_turn(_summary()), [])

    def test_bad_routing_and_empty_selection_fail(self):
        failures = ar4_live.assert_first_turn(_summary(query_type="rag", selected_ids=[]))
        self.assertTrue(any("runtime" in item for item in failures))
        self.assertTrue(any("选片集合" in item for item in failures))

    def test_followup_misfire_and_terminal_fail(self):
        failures = ar4_live.assert_first_turn(_summary(followup=True, terminal_reason="cost_exceeded"))
        self.assertTrue(any("跟进" in item for item in failures))
        self.assertTrue(any("cost_exceeded" in item for item in failures))

    def test_clarification_fails(self):
        failures = ar4_live.assert_first_turn(_summary(clarification=True))
        self.assertTrue(any("澄清" in item for item in failures))


class CopyFollowupAssertionTest(unittest.TestCase):
    def test_good_copy_turn_passes(self):
        prev = _summary(turn=1)
        current = _summary(
            turn=2, question="不要那么文艺", followup=True,
            affected=["copy"], answer="# 山西第一天\n平实正文",
        )
        self.assertEqual(ar4_live.assert_copy_followup(prev, current), [])

    def test_not_followup_fails(self):
        failures = ar4_live.assert_copy_followup(_summary(), _summary(turn=2, answer="不同文案"))
        self.assertTrue(any("跟进" in item for item in failures))

    def test_selection_affected_and_changed_ids_fail(self):
        prev = _summary(turn=1)
        current = _summary(
            turn=2, followup=True, affected=["copy", "selection"],
            selected_ids=["c"], answer="不同文案",
        )
        failures = ar4_live.assert_copy_followup(prev, current)
        self.assertTrue(any("selection" in item for item in failures))
        self.assertTrue(any("选片集合应不变" in item for item in failures))

    def test_identical_answer_fails(self):
        prev = _summary(turn=1)
        current = _summary(turn=2, followup=True, affected=["copy"], answer=prev["answer"])
        failures = ar4_live.assert_copy_followup(prev, current)
        self.assertTrue(any("文案" in item for item in failures))

    def test_missing_copy_in_affected_fails(self):
        failures = ar4_live.assert_copy_followup(
            _summary(), _summary(turn=2, followup=True, affected=["report"], answer="不同文案"),
        )
        self.assertTrue(any("copy" in item for item in failures))


class SelectionAddAssertionTest(unittest.TestCase):
    def test_good_add_turn_passes(self):
        prev = _summary(turn=2)
        current = _summary(
            turn=3, question="再补两张不同场景的照片", followup=True,
            affected=["selection_add", "copy"], selected_ids=["b", "c", "a"],
        )
        self.assertEqual(ar4_live.assert_selection_add(prev, current), [])

    def test_reselect_instead_of_add_fails(self):
        prev = _summary(turn=2)
        current = _summary(
            turn=3, followup=True, affected=["selection", "copy"], selected_ids=["a", "d"],
        )
        failures = ar4_live.assert_selection_add(prev, current)
        self.assertTrue(any("selection_add" in item for item in failures))
        self.assertTrue(any("丢失" in item for item in failures))

    def test_preserved_but_no_growth_fails(self):
        prev = _summary(turn=2)
        current = _summary(turn=3, followup=True, affected=["selection_add"], selected_ids=["b", "c"])
        failures = ar4_live.assert_selection_add(prev, current)
        self.assertTrue(any("未新增" in item for item in failures))

    def test_scope_affected_fails(self):
        prev = _summary(turn=2)
        current = _summary(
            turn=3, followup=True, affected=["scope", "selection_add"], selected_ids=["b", "c", "a"],
        )
        failures = ar4_live.assert_selection_add(prev, current)
        self.assertTrue(any("范围" in item for item in failures))


class NegativeSqlAssertionTest(unittest.TestCase):
    def test_good_negative_turn_passes(self):
        current = _summary(
            turn=4, question="2026 年 5 月我拍了多少张照片",
            query_type="sql", selected_ids=[], answer="共 42 张",
        )
        self.assertEqual(ar4_live.assert_negative_sql(current), [])

    def test_followup_misfire_fails(self):
        current = _summary(turn=4, followup=True, query_type="sql", affected=["scope"])
        failures = ar4_live.assert_negative_sql(current)
        self.assertTrue(any("误判为跟进" in item for item in failures))

    def test_wrong_route_fails(self):
        failures = ar4_live.assert_negative_sql(_summary(turn=4, query_type="rag"))
        self.assertTrue(any("sql" in item for item in failures))


if __name__ == "__main__":
    unittest.main()

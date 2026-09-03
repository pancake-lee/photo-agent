import unittest

import internal.runtime.progress as progress


class RuntimeProgressTranslatorTest(unittest.TestCase):
    def test_translates_real_events_without_exposing_photo_ids(self):
        translator = progress.RuntimeProgressTranslator()
        translator.consume("runtime.decide", {
            "step": 1, "action": "sql_search", "title": "查询照片",
            "reason": "先定位第一天的候选",
        })
        steps = translator.consume("runtime.observe", {
            "step": 1,
            "action": "sql_search",
            "title": "查询照片",
            "summary": "结构化检索（SQL）返回 20 个候选照片",
            "facts": ["已确认timeline：山西旅游"],
            "details": {"SQL": "SELECT id FROM photos WHERE timeline = '山西'"},
        })

        self.assertEqual(steps[0]["title"], "查询照片")
        self.assertEqual(steps[0]["status"], "已完成")
        self.assertEqual(steps[0]["decision"], "先定位第一天的候选")
        self.assertIn("20 个候选", steps[0]["result"])
        self.assertEqual(steps[0]["details"]["SQL"], "SELECT id FROM photos WHERE timeline = '山西'")
        self.assertNotIn("photo_ids", steps[0])

    def test_marks_stopped_step(self):
        translator = progress.RuntimeProgressTranslator()
        translator.consume("runtime.decide", {
            "step": 2, "action": "select_photos", "title": "挑选代表照片",
        })
        steps = translator.consume("runtime.check", {
            "step": 2, "stop_reason": "max_steps", "terminal_reason": "",
        })
        self.assertEqual(steps[0]["status"], "已停止")

    def test_missing_title_falls_back_to_generic(self):
        """事件未携带标题（如未登记能力的决策）时回退通用标题。"""
        translator = progress.RuntimeProgressTranslator()
        steps = translator.consume("runtime.decide", {"step": 3, "action": "no_such"})
        self.assertEqual(steps[0]["title"], "处理任务")

    def test_guardrail_recovery_becomes_own_step_entry(self):
        """AR2-3：恢复动作作为独立条目插入对应步骤之后，瞬时完成并给出原因。"""
        translator = progress.RuntimeProgressTranslator()
        translator.consume("runtime.decide", {
            "step": 1, "action": "sql_search", "title": "查询照片", "reason": "检索",
        })
        steps = translator.consume("runtime.guardrail", {
            "step": 1, "ordinal": 1, "recovery": "retry",
            "title": "重试：查询照片", "reason": "瞬时故障，同能力同参数重试（第 1 次）",
        })
        steps = translator.consume("runtime.observe", {
            "step": 1, "title": "查询照片", "summary": "返回 3 个候选照片",
        })
        self.assertEqual([step["title"] for step in steps], ["查询照片", "重试：查询照片"])
        retry_entry = steps[1]
        self.assertEqual(retry_entry["status"], "已完成")
        self.assertIn("瞬时故障", retry_entry["result"])

    def test_multiple_recoveries_keep_occurrence_order(self):
        """同一步内多次恢复按发生顺序排列，步骤号排序不受恢复条目影响。"""
        translator = progress.RuntimeProgressTranslator()
        translator.consume("runtime.decide", {"step": 2, "title": "挑选代表照片"})
        translator.consume("runtime.guardrail", {
            "step": 2, "ordinal": 1, "title": "修复重试：挑选代表照片", "reason": "第一次修复",
        })
        steps = translator.consume("runtime.guardrail", {
            "step": 2, "ordinal": 2, "title": "修复重试：挑选代表照片", "reason": "第二次修复",
        })
        self.assertEqual(
            [step["result"] for step in steps], ["", "第一次修复", "第二次修复"],
        )
        self.assertEqual([step["step"] for step in steps], [2, 2, 2])


if __name__ == "__main__":
    unittest.main()

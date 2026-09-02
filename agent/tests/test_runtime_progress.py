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


if __name__ == "__main__":
    unittest.main()

import unittest

import internal.runtime.progress as progress


class RuntimeProgressTranslatorTest(unittest.TestCase):
    def test_translates_real_events_without_exposing_photo_ids(self):
        translator = progress.RuntimeProgressTranslator()
        translator.consume("runtime.decide", {
            "step": 1, "action": "sql_search", "reason": "先定位第一天的候选",
        })
        steps = translator.consume("runtime.observe", {
            "step": 1,
            "action": "sql_search",
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
        translator.consume("runtime.decide", {"step": 2, "action": "select_photos"})
        steps = translator.consume("runtime.check", {
            "step": 2, "stop_reason": "max_steps", "terminal_reason": "",
        })
        self.assertEqual(steps[0]["status"], "已停止")

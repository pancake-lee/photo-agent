import json
import logging
import unittest

import infra.app_logging as app_logging


class JsonLineFormatterTest(unittest.TestCase):
    def test_formats_common_fields_with_request_trace(self):
        token = app_logging.trace_id_var.set("trace-123")
        try:
            record = logging.LogRecord(
                "internal.chat", logging.INFO, "/tmp/chat.py", 42, "查询完成", (), None,
            )
            record.event = "chat.answer"
            result = json.loads(app_logging.JsonLineFormatter().format(record))
        finally:
            app_logging.trace_id_var.reset(token)

        self.assertEqual(result["trace_id"], "trace-123")
        self.assertEqual(result["source"], "/tmp/chat.py:42")
        self.assertEqual(result["event"], "chat.answer")
        self.assertEqual(result["message"], "查询完成")

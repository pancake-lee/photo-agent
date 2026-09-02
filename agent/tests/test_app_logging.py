import logging
import json
import unittest

import infra.app_logging as app_logging


class ConsoleFormatterTest(unittest.TestCase):
    def test_console_formatter_is_human_readable_and_keeps_trace_id(self):
        record = logging.LogRecord(
            "internal.runtime.graph", logging.INFO, "/workspace/internal/runtime/graph.py", 42,
            "第 %d 步执行完成", (2,), None,
        )
        record.trace_id = "trace-123"

        line = app_logging.ConsoleFormatter().format(record)

        self.assertIn("INFO", line)
        self.assertIn("[internal.runtime.graph]", line)
        self.assertIn("trace=trace-123", line)
        self.assertIn("第 2 步执行完成", line)
        self.assertTrue(line.endswith("[runtime/graph.py:42]"))
        self.assertFalse(line.startswith("{"))

    def test_json_formatter_uses_the_same_short_source(self):
        record = logging.LogRecord(
            "cli.server", logging.INFO, "/workspace/agent/cli/server.py", 77,
            "服务已启动", (), None,
        )

        line = json.loads(app_logging.JsonLineFormatter().format(record))

        self.assertEqual(line["source"], "cli/server.py:77")

    def test_json_formatter_keeps_trace_id_without_trace_file_fields(self):
        trace_token = app_logging.trace_id_var.set("trace-123")
        try:
            record = logging.LogRecord("cli.server", logging.INFO, "/workspace/agent/cli/server.py", 77, "已完成", (), None)
            line = json.loads(app_logging.JsonLineFormatter().format(record))
        finally:
            app_logging.trace_id_var.reset(trace_token)

        self.assertEqual(line["trace_id"], "trace-123")
        self.assertNotIn("trace_file_ref", line)
        self.assertNotIn("trace_payload_dir_ref", line)

"""SQL 路由诊断日志测试（unittest 风格）。

运行方式（项目统一用 unittest，见 docs/archive/v1.0.13.md）:
    cd agent && .venv/bin/python -m unittest discover -s tests -v
"""

import logging
import types
import unittest
import unittest.mock

import langchain_core.runnables as lc_runnables
import swagger_client as sdk

import chain.photo_agent as photo_agent
import chain.text_to_sql as text_to_sql


class _FakeConfig:
    go_backend_url = "http://backend.example"


def _fake_schema_response() -> sdk.ApiGetPhotoSchemaResponse:
    return sdk.ApiGetPhotoSchemaResponse(
        table_name="photos",
        fields=[
            sdk.ApiSchemaField(name="id", sql_type="TEXT", json_tag="id", nullable=False),
        ],
    )


def _fake_llm_patch(content: str):
    """把 LLM 替换为恒定输出的 Runnable，绕过真实模型调用。"""
    fake = lc_runnables.RunnableLambda(
        lambda _input: types.SimpleNamespace(content=content)
    )
    return unittest.mock.patch.object(
        text_to_sql.llm_factory, "create_llm",
        side_effect=lambda *_args, **_kwargs: fake,
    )


class TestGenerateSqlDiagnostics(unittest.TestCase):

    def test_generate_sql_logs_raw_output_and_sql(self):
        with unittest.mock.patch.object(
            text_to_sql, "_fetch_schema", return_value=_fake_schema_response(),
        ), unittest.mock.patch.object(
            text_to_sql, "_fetch_attribute_values", return_value={},
        ), _fake_llm_patch("SELECT COUNT(*) AS c FROM photos"), self.assertLogs(
            "chain.text_to_sql", level=logging.INFO,
        ) as captured:
            sql = text_to_sql.generate_sql(_FakeConfig(), "我有多少张照片？")

        self.assertEqual(sql, "SELECT COUNT(*) AS c FROM photos")
        text = "\n".join(captured.output)
        self.assertIn("[sql] SQL 生成开始", text)
        self.assertIn("[sql] LLM 原始输出", text)
        self.assertIn("[sql] 生成 SQL: SELECT COUNT(*) AS c FROM photos", text)

    def test_fetch_schema_logs_field_count(self):
        fake_client = types.SimpleNamespace(
            fetch_schema=lambda: _fake_schema_response(),
        )
        with unittest.mock.patch.object(
            text_to_sql.sqlite_client, "QueryClient", return_value=fake_client,
        ), self.assertLogs("chain.text_to_sql", level=logging.INFO) as captured:
            schema = text_to_sql._fetch_schema("http://backend.example")

        self.assertEqual(schema.table_name, "photos")
        self.assertIn("[sql] Schema 已获取: fields=1", "\n".join(captured.output))

    def test_generate_sql_warns_on_cannot_answer_sentinel(self):
        with unittest.mock.patch.object(
            text_to_sql, "_fetch_schema", return_value=_fake_schema_response(),
        ), unittest.mock.patch.object(
            text_to_sql, "_fetch_attribute_values", return_value={},
        ), _fake_llm_patch("SELECT '无法回答' AS result"), self.assertLogs(
            "chain.text_to_sql", level=logging.WARNING,
        ) as captured:
            sql = text_to_sql.generate_sql(_FakeConfig(), "写一段文案")

        self.assertIn("无法回答", sql)
        self.assertIn("无法回答哨兵", "\n".join(captured.output))

    def test_generate_filter_sql_logs_generated_sql(self):
        with unittest.mock.patch.object(
            text_to_sql, "_fetch_schema", return_value=_fake_schema_response(),
        ), unittest.mock.patch.object(
            text_to_sql, "_fetch_attribute_values", return_value={},
        ), _fake_llm_patch("SELECT id FROM photos WHERE scene = 'street' LIMIT 20"), \
                self.assertLogs("chain.text_to_sql", level=logging.INFO) as captured:
            sql = text_to_sql.generate_filter_sql(_FakeConfig(), "街拍照片")

        self.assertIn("scene", sql)
        text = "\n".join(captured.output)
        self.assertIn("[sql] 过滤 SQL 生成开始", text)
        self.assertIn("[sql] 生成 SQL: SELECT id FROM photos", text)


class TestAnswerWithSqlSentinel(unittest.TestCase):
    """无法回答哨兵短路测试（CQ6）：不执行哨兵 SQL，返回可理解的说明。"""

    def test_sentinel_skips_execution_and_returns_explanation(self):
        with unittest.mock.patch.object(
            text_to_sql, "generate_sql", return_value="SELECT '无法回答' AS result",
        ), unittest.mock.patch.object(
            text_to_sql, "execute_sql",
        ) as exec_mock, self.assertLogs(
            "chain.text_to_sql", level=logging.WARNING,
        ) as captured:
            result = text_to_sql.answer_with_sql(_FakeConfig(), "写一段文案")

        exec_mock.assert_not_called()
        self.assertEqual(result["results"], [])
        self.assertIn("无法仅靠照片库的结构化数据回答", result["answer"])
        self.assertIn("[sql] 检测到无法回答哨兵", "\n".join(captured.output))


class TestExecuteSqlDiagnostics(unittest.TestCase):

    def test_execute_sql_logs_row_count(self):
        fake_result = types.SimpleNamespace(rows=[{"id": "a"}, {"id": "b"}])
        with unittest.mock.patch.object(
            text_to_sql.sqlite_client, "safe_execute", return_value=fake_result,
        ), self.assertLogs("chain.text_to_sql", level=logging.INFO) as captured:
            rows = text_to_sql.execute_sql(
                "http://backend.example", "SELECT id FROM photos",
            )

        self.assertEqual(len(rows), 2)
        self.assertIn("[sql] 执行完成: rows=2", "\n".join(captured.output))


class TestSqlNodeDiagnostics(unittest.TestCase):

    def test_sql_node_logs_completion(self):
        fake_result = {
            "question": "我有多少张照片？",
            "sql": "SELECT COUNT(*) AS c FROM photos",
            "results": [{"c": 42}],
            "answer": "查询结果（共 1 条）:\n  1. c=42",
        }
        with unittest.mock.patch.object(
            photo_agent.text_to_sql, "answer_with_sql", return_value=fake_result,
        ), self.assertLogs("chain.photo_agent", level=logging.INFO) as captured:
            state = photo_agent._sql_node(
                {"question": "我有多少张照片？"},
                {"configurable": {"cfg": _FakeConfig()}},
            )

        self.assertEqual(state["sql_result"], fake_result)
        self.assertIn("[sql] 查询完成: rows=1", "\n".join(captured.output))

    def test_sql_node_logs_exception(self):
        with unittest.mock.patch.object(
            photo_agent.text_to_sql, "answer_with_sql",
            side_effect=RuntimeError("backend down"),
        ), self.assertLogs("chain.photo_agent", level=logging.ERROR) as captured:
            state = photo_agent._sql_node(
                {"question": "q"},
                {"configurable": {"cfg": _FakeConfig()}},
            )

        self.assertIn("SQL 查询失败: backend down", state["sql_result"]["answer"])
        self.assertIn("[sql] 查询异常", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()

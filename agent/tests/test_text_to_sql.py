"""
    Text-to-SQL 与 SQLite 安全校验单元测试。

    运行方式：
        cd agent && ./venv/bin/python -m unittest tests.test_text_to_sql -v
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import db.sqlite_client as sqlite_client
import chain.text_to_sql as text_to_sql
import chain.photo_rag as photo_rag
import langchain_core.prompts as lc_prompts


# --------------------------------------------------------------------------- #
# SQLite 安全校验测试
# --------------------------------------------------------------------------- #

class TestValidateSelectOnly(unittest.TestCase):
    """SQL 安全校验测试。"""

    def test_valid_select(self):
        self.assertTrue(sqlite_client.validate_select_only("SELECT * FROM photos"))

    def test_valid_select_with_where(self):
        self.assertTrue(
            sqlite_client.validate_select_only(
                "SELECT filename, brand FROM photos WHERE iso > 100"
            )
        )

    def test_valid_select_multiline(self):
        sql = """
            SELECT
                filename,
                brand
            FROM photos
            WHERE iso > 100
            LIMIT 10
        """
        self.assertTrue(sqlite_client.validate_select_only(sql))

    def test_valid_select_with_comments(self):
        self.assertTrue(
            sqlite_client.validate_select_only(
                "-- 查询照片\nSELECT * FROM photos"
            )
        )

    def test_valid_select_with_block_comment(self):
        self.assertTrue(
            sqlite_client.validate_select_only(
                "/* 查询 */ SELECT * FROM photos"
            )
        )

    def test_reject_insert(self):
        self.assertFalse(
            sqlite_client.validate_select_only(
                "INSERT INTO photos (filename) VALUES ('test.jpg')"
            )
        )

    def test_reject_update(self):
        self.assertFalse(
            sqlite_client.validate_select_only(
                "UPDATE photos SET brand = 'Canon' WHERE id = '1'"
            )
        )

    def test_reject_delete(self):
        self.assertFalse(
            sqlite_client.validate_select_only("DELETE FROM photos WHERE id = '1'")
        )

    def test_reject_drop(self):
        self.assertFalse(sqlite_client.validate_select_only("DROP TABLE photos"))

    def test_reject_create(self):
        self.assertFalse(
            sqlite_client.validate_select_only(
                "CREATE TABLE test (id INTEGER PRIMARY KEY)"
            )
        )

    def test_reject_alter(self):
        self.assertFalse(
            sqlite_client.validate_select_only("ALTER TABLE photos ADD COLUMN x TEXT")
        )

    def test_reject_truncate(self):
        self.assertFalse(sqlite_client.validate_select_only("TRUNCATE TABLE photos"))

    def test_reject_pragma(self):
        self.assertFalse(sqlite_client.validate_select_only("PRAGMA table_info(photos)"))

    def test_reject_select_with_subquery_delete(self):
        # 更隐蔽的注入：SELECT 中包含 DELETE 子句（虽然语法上不太可能，但校验应拒绝）
        sql = "SELECT * FROM photos WHERE id IN (DELETE FROM photos WHERE id = '1')"
        self.assertFalse(sqlite_client.validate_select_only(sql))

    def test_reject_empty(self):
        self.assertFalse(sqlite_client.validate_select_only(""))
        self.assertFalse(sqlite_client.validate_select_only("   "))

    def test_reject_non_select(self):
        self.assertFalse(sqlite_client.validate_select_only("SHOW TABLES"))


# --------------------------------------------------------------------------- #
# SQL 提取测试
# --------------------------------------------------------------------------- #

class TestExtractSqlFromResponse(unittest.TestCase):
    """LLM 响应 SQL 提取测试。"""

    def test_plain_sql(self):
        text = "SELECT * FROM photos"
        self.assertEqual(
            text_to_sql._extract_sql_from_response(text), "SELECT * FROM photos"
        )

    def test_markdown_sql_block(self):
        text = "```sql\nSELECT * FROM photos\n```"
        self.assertEqual(
            text_to_sql._extract_sql_from_response(text), "SELECT * FROM photos"
        )

    def test_markdown_generic_block(self):
        text = "```\nSELECT * FROM photos\n```"
        self.assertEqual(
            text_to_sql._extract_sql_from_response(text), "SELECT * FROM photos"
        )

    def test_with_explanation(self):
        text = "这是一个查询：\n```sql\nSELECT * FROM photos\n```\n希望对你有帮助"
        self.assertEqual(
            text_to_sql._extract_sql_from_response(text), "SELECT * FROM photos"
        )


# --------------------------------------------------------------------------- #
# Schema 格式化测试
# --------------------------------------------------------------------------- #

class TestFormatSchema(unittest.TestCase):
    """Schema 格式化测试。"""

    def test_basic_formatting(self):
        schema_data = {
            "table_name": "photos",
            "fields": [
                {"name": "id", "sql_type": "TEXT", "json_tag": "id", "nullable": False},
                {"name": "brand", "sql_type": "TEXT", "json_tag": "brand", "nullable": False},
                {"name": "latitude", "sql_type": "REAL", "json_tag": "latitude", "nullable": True},
            ],
            "notes": ["brand 字段可能为空字符串", "经纬度为 NULL 表示无 GPS 信息"],
        }
        text = text_to_sql._format_schema(schema_data)
        self.assertIn("表名: photos", text)
        self.assertIn("id (TEXT): JSON tag = id", text)
        self.assertIn("latitude (REAL): JSON tag = latitude，可能为 NULL", text)
        self.assertIn("注意事项:", text)
        self.assertIn("brand 字段可能为空字符串", text)

    def test_empty_notes(self):
        schema_data = {
            "table_name": "photos",
            "fields": [{"name": "id", "sql_type": "TEXT", "json_tag": "id", "nullable": False}],
            "notes": [],
        }
        text = text_to_sql._format_schema(schema_data)
        self.assertNotIn("注意事项:", text)


# --------------------------------------------------------------------------- #
# 结果格式化测试
# --------------------------------------------------------------------------- #

class TestFormatResults(unittest.TestCase):
    """查询结果格式化测试。"""

    def test_empty_results(self):
        result = text_to_sql.format_results("有多少照片？", "SELECT ...", [])
        self.assertEqual(result, "未找到匹配的数据。")

    def test_single_row(self):
        results = [{"photo_count": 42}]
        result = text_to_sql.format_results("有多少照片？", "SELECT ...", results)
        self.assertIn("42", result)
        self.assertIn("共 1 条", result)

    def test_multiple_rows(self):
        results = [
            {"filename": "a.jpg", "brand": "Canon"},
            {"filename": "b.jpg", "brand": "Nikon"},
        ]
        result = text_to_sql.format_results("照片列表？", "SELECT ...", results)
        self.assertIn("共 2 条", result)
        self.assertIn("a.jpg", result)
        self.assertIn("b.jpg", result)

    def test_truncation(self):
        results = [{"id": i} for i in range(15)]
        result = text_to_sql.format_results("test", "SELECT ...", results, max_rows=5)
        self.assertIn("共 15 条", result)
        self.assertIn("还有 10 条未展示", result)


# --------------------------------------------------------------------------- #
# RAG 照片聚合测试
# --------------------------------------------------------------------------- #

class TestAggregateByPhoto(unittest.TestCase):
    """RAG 检索结果照片级别聚合测试。"""

    def test_empty_results(self):
        self.assertEqual(photo_rag._aggregate_by_photo([]), [])

    def test_single_photo_single_chunk(self):
        results = [
            {
                "id": "a#0",
                "document": "desc",
                "metadata": {"photo_id": "a"},
                "distance": 0.1,
            }
        ]
        aggregated = photo_rag._aggregate_by_photo(results)
        self.assertEqual(len(aggregated), 1)
        self.assertEqual(aggregated[0]["metadata"]["photo_id"], "a")

    def test_same_photo_multiple_chunks_keep_best(self):
        results = [
            {
                "id": "a#0",
                "document": "desc1",
                "metadata": {"photo_id": "a"},
                "distance": 0.5,
            },
            {
                "id": "a#1",
                "document": "desc2",
                "metadata": {"photo_id": "a"},
                "distance": 0.2,
            },
        ]
        aggregated = photo_rag._aggregate_by_photo(results)
        self.assertEqual(len(aggregated), 1)
        # 应保留距离最小的 chunk (0.2)
        self.assertEqual(aggregated[0]["distance"], 0.2)
        self.assertEqual(aggregated[0]["id"], "a#1")

    def test_multiple_photos_sorted_by_distance(self):
        results = [
            {
                "id": "b#0",
                "document": "desc b",
                "metadata": {"photo_id": "b"},
                "distance": 0.3,
            },
            {
                "id": "a#0",
                "document": "desc a",
                "metadata": {"photo_id": "a"},
                "distance": 0.1,
            },
            {
                "id": "c#0",
                "document": "desc c",
                "metadata": {"photo_id": "c"},
                "distance": 0.5,
            },
        ]
        aggregated = photo_rag._aggregate_by_photo(results, top_n=2)
        self.assertEqual(len(aggregated), 2)
        self.assertEqual(aggregated[0]["metadata"]["photo_id"], "a")
        self.assertEqual(aggregated[1]["metadata"]["photo_id"], "b")

    def test_missing_photo_id_skipped(self):
        results = [
            {
                "id": "a#0",
                "document": "desc",
                "metadata": {"photo_id": "a"},
                "distance": 0.1,
            },
            {
                "id": "orphan",
                "document": "no photo_id",
                "metadata": {},
                "distance": 0.05,
            },
        ]
        aggregated = photo_rag._aggregate_by_photo(results)
        self.assertEqual(len(aggregated), 1)
        self.assertEqual(aggregated[0]["metadata"]["photo_id"], "a")


# --------------------------------------------------------------------------- #
# Few-shot 构建测试
# --------------------------------------------------------------------------- #

class TestBuildFewShotPrompt(unittest.TestCase):
    """FewShotChatMessagePromptTemplate 构建测试。"""

    def test_returns_few_shot_template(self):
        prompt = text_to_sql._build_few_shot_prompt()
        self.assertIsInstance(
            prompt, lc_prompts.FewShotChatMessagePromptTemplate
        )

    def test_contains_examples(self):
        prompt = text_to_sql._build_few_shot_prompt()
        self.assertEqual(len(prompt.examples), 6)
        self.assertEqual(prompt.examples[0]["question"], "我有多少张照片？")
        self.assertEqual(prompt.examples[0]["sql"], "SELECT COUNT(*) AS photo_count FROM photos")


# --------------------------------------------------------------------------- #
# QueryClient 测试（mock HTTP）
# --------------------------------------------------------------------------- #

class TestQueryClient(unittest.TestCase):
    """QueryClient 测试（通过 mock 验证 HTTP 调用逻辑）。"""

    def test_validate_select_only_passed_to_query(self):
        """query 方法在调用 HTTP 前会执行 SQL 安全校验。"""
        client = sqlite_client.QueryClient("http://localhost:10000")
        # 非 SELECT 语句应在 HTTP 调用前抛出 ValueError
        with self.assertRaises(ValueError) as ctx:
            client.query("DROP TABLE photos")
        self.assertIn("SQL 校验失败", str(ctx.exception))

    def test_safe_query_catches_error(self):
        """safe_query 应将异常封装到 error 字段中。"""
        client = sqlite_client.QueryClient("http://localhost:10000")
        result = client.safe_query("DROP TABLE photos")
        self.assertIn("error", result)
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["count"], 0)

    def test_validate_select_only_allows_legal_select(self):
        """合法的 SELECT 应通过客户端校验，不会因校验失败报错。"""
        client = sqlite_client.QueryClient("http://localhost:10000")
        # 这里不实际调用 HTTP，仅验证校验通过不会提前抛异常
        # 真正的 HTTP 调用会在没有服务时抛 ConnectError，但那是网络层问题
        self.assertTrue(sqlite_client.validate_select_only(
            "SELECT * FROM photos WHERE brand = 'Canon'"
        ))


if __name__ == "__main__":
    unittest.main()

"""
    embedding.chunking 单元测试。

    运行方式：
        cd agent && ./venv/bin/python -m unittest tests.test_chunking -v
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import embedding.chunking as chunking


class TestChunkByNone(unittest.TestCase):
    """不分片策略测试。"""

    def test_short_text(self):
        text = "这是一段短文本"
        result = chunking.chunk_by_none(text)
        self.assertEqual(result, [text])

    def test_empty_text(self):
        self.assertEqual(chunking.chunk_by_none(""), [])
        self.assertEqual(chunking.chunk_by_none("   "), [])


class TestChunkByFixedSize(unittest.TestCase):
    """固定字数分片策略测试。"""

    def test_short_text_no_split(self):
        text = "短文本"
        result = chunking.chunk_by_fixed_size(text, chunk_size=500)
        self.assertEqual(result, [text])

    def test_exact_length_no_split(self):
        text = "a" * 500
        result = chunking.chunk_by_fixed_size(text, chunk_size=500)
        self.assertEqual(result, [text])

    def test_long_text_split(self):
        text = "a" * 600
        result = chunking.chunk_by_fixed_size(text, chunk_size=500, chunk_overlap=50)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]), 500)
        self.assertEqual(len(result[1]), 150)

    def test_overlap_consistency(self):
        text = "a" * 950
        result = chunking.chunk_by_fixed_size(text, chunk_size=500, chunk_overlap=50)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(result[0]), 500)
        self.assertEqual(len(result[1]), 500)
        self.assertEqual(len(result[2]), 50)

    def test_empty_text(self):
        self.assertEqual(chunking.chunk_by_fixed_size("", chunk_size=500), [])


class TestChunkByMarkdownHeading(unittest.TestCase):
    """Markdown 标题分片策略测试。"""

    def test_no_heading(self):
        text = "纯文本内容\n没有标题"
        result = chunking.chunk_by_markdown_heading(text, level=2)
        self.assertEqual(result, [text])

    def test_level2_headings(self):
        text = "## 标题1\n内容1\n## 标题2\n内容2"
        result = chunking.chunk_by_markdown_heading(text, level=2)
        self.assertEqual(len(result), 2)
        self.assertTrue(result[0].startswith("## 标题1"))
        self.assertTrue(result[1].startswith("## 标题2"))

    def test_level3_headings(self):
        text = "### A\n1\n### B\n2"
        result = chunking.chunk_by_markdown_heading(text, level=3)
        self.assertEqual(len(result), 2)

    def test_mixed_levels(self):
        """更高级别标题不应被低级别策略误切，整段归入第一个匹配的标题块。"""
        text = "## 二级\n内容\n### 三级\n子内容"
        result = chunking.chunk_by_markdown_heading(text, level=2)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].startswith("## 二级"))

    def test_level2_does_not_split_on_level3(self):
        """level=2 不应把 ### 当作切分点。"""
        text = "## 二级\n内容\n### 三级\n子内容\n#### 四级\n孙内容"
        result = chunking.chunk_by_markdown_heading(text, level=2)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].startswith("## 二级"))

    def test_content_before_first_heading(self):
        """第一个目标标题前的内容单独成块，标题及之后内容归入后续块。"""
        text = "前置内容\n## 标题\n正文"
        result = chunking.chunk_by_markdown_heading(text, level=2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "前置内容")
        self.assertTrue(result[1].startswith("## 标题"))

    def test_empty_text(self):
        self.assertEqual(chunking.chunk_by_markdown_heading("", level=2), [])

    def test_invalid_level(self):
        with self.assertRaises(ValueError):
            chunking.chunk_by_markdown_heading("text", level=0)
        with self.assertRaises(ValueError):
            chunking.chunk_by_markdown_heading("text", level=7)


class TestChunkTextDispatch(unittest.TestCase):
    """chunk_text 统一入口分发测试。"""

    def test_dispatch_none(self):
        text = "abc"
        result = chunking.chunk_text(text, strategy=chunking.Strategy.NONE)
        self.assertEqual(result, [text])

    def test_dispatch_fixed_size(self):
        text = "a" * 600
        result = chunking.chunk_text(
            text, strategy=chunking.Strategy.FIXED_SIZE, chunk_size=500, chunk_overlap=50
        )
        self.assertEqual(len(result), 2)

    def test_dispatch_markdown_heading(self):
        text = "## A\n1\n## B\n2"
        result = chunking.chunk_text(
            text, strategy=chunking.Strategy.MARKDOWN_HEADING, level=2
        )
        self.assertEqual(len(result), 2)

    def test_empty_input(self):
        self.assertEqual(chunking.chunk_text("", strategy=chunking.Strategy.NONE), [])
        self.assertEqual(
            chunking.chunk_text("   ", strategy=chunking.Strategy.FIXED_SIZE), []
        )

    def test_unknown_strategy(self):
        with self.assertRaises(ValueError):
            chunking.chunk_text("text", strategy="unknown")  # type: ignore[arg-type]

    def test_strategy_type_check(self):
        with self.assertRaises(ValueError):
            chunking.chunk_text("text", strategy="none")  # type: ignore[arg-type]


class TestChunkTextAuto(unittest.TestCase):
    """chunk_text_auto 自动策略选择测试。"""

    def test_short_text_no_split(self):
        text = "这是一段短文本"
        result = chunking.chunk_text_auto(text, chunk_size=500)
        self.assertEqual(result, [text])

    def test_long_text_no_md(self):
        text = "a" * 600
        result = chunking.chunk_text_auto(text, chunk_size=500)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]), 500)

    def test_md_headings_fit(self):
        text = "## 标题1\n" + "内容1\n" * 100 + "## 标题2\n" + "内容2\n" * 100
        result = chunking.chunk_text_auto(text, chunk_size=500)
        self.assertGreater(len(result), 1)
        for chunk in result:
            self.assertLessEqual(len(chunk), 500)

    def test_md_headings_auto_fallback_to_finer(self):
        """二级标题分块后仍有块超长，应自动升级到更细级别。"""
        text = "## 标题1\n" + "a" * 600 + "\n## 标题2\n内容2"
        result = chunking.chunk_text_auto(text, chunk_size=500)
        for chunk in result:
            self.assertLessEqual(len(chunk), 500)

    def test_md_headings_fallback_to_fixed_size(self):
        """所有 Markdown 级别都不满足时，兜底 FIXED_SIZE。"""
        text = "## 标题1\n" + "a" * 600 + "\n### 子标题\n" + "b" * 600
        result = chunking.chunk_text_auto(text, chunk_size=500)
        for chunk in result:
            self.assertLessEqual(len(chunk), 500)

    def test_user_specified_md_level(self):
        text = "## A\n" + "x\n" * 300 + "## B\n" + "y\n" * 300
        result = chunking.chunk_text_auto(text, chunk_size=500, md_level=2)
        self.assertGreater(len(result), 1)
        for chunk in result:
            self.assertLessEqual(len(chunk), 500)

    def test_user_specified_level_downgrade(self):
        """用户指定级别分块后仍有超长，应降级。"""
        text = "## 标题1\n" + "a" * 600 + "\n### 子标题\n内容"
        result = chunking.chunk_text_auto(text, chunk_size=500, md_level=2)
        for chunk in result:
            self.assertLessEqual(len(chunk), 500)

    def test_only_level1_heading_treated_as_no_md(self):
        """只有一级标题 # 时，应视为非 Markdown 格式，走 FIXED_SIZE。"""
        text = "# 标题1\n" + "a" * 600
        result = chunking.chunk_text_auto(text, chunk_size=500)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]), 500)

    def test_empty_text(self):
        self.assertEqual(chunking.chunk_text_auto("", chunk_size=500), [])


if __name__ == "__main__":
    unittest.main()

"""会话上下文构建器测试（AR4-1 / V4 Context Builder）。"""

import unittest

import internal.context.builder as ctx_builder


def _message(role: str, content: str, photos: list[dict] | None = None) -> dict:
    return {"role": role, "content": content, "photos": photos or []}


class EmptyHistoryTest(unittest.TestCase):
    """空会话：无历史块，分类走既有无历史路径。"""

    def test_empty_history_produces_empty_block(self):
        ctx = ctx_builder.build_session_context([])
        self.assertEqual(ctx.history_block, "")
        self.assertFalse(ctx.has_history)
        self.assertEqual(ctx.turn_count, 0)
        self.assertFalse(ctx.truncated)

    def test_dangling_user_message_without_answer_is_kept(self):
        ctx = ctx_builder.build_session_context([_message("user", "刚才那组怎么样")])
        self.assertTrue(ctx.has_history)
        self.assertEqual(ctx.turn_count, 1)
        self.assertIn("刚才那组怎么样", ctx.history_block)


class SelectionTest(unittest.TestCase):
    """选择：近窗口原文，更早轮次摘要。"""

    def test_recent_turns_kept_verbatim_and_older_compressed(self):
        messages = []
        for index in range(1, 5):
            messages.append(_message("user", f"第{index}个问题：找山西旅游第{index}天的照片"))
            messages.append(_message("assistant", f"# 第{index}天成果\n正文内容{index}"))
        messages.append(_message("user", "第5个问题：不要那么文艺"))
        messages.append(_message("assistant", "好的，已调整为平实风格"))

        ctx = ctx_builder.build_session_context(messages)

        self.assertEqual(ctx.turn_count, 5)
        # 最近两组保留原文
        self.assertIn("[最近会话]", ctx.history_block)
        self.assertIn("第4个问题：找山西旅游第4天的照片", ctx.history_block)
        self.assertIn("正文内容4", ctx.history_block)
        self.assertIn("第5个问题：不要那么文艺", ctx.history_block)
        self.assertIn("好的，已调整为平实风格", ctx.history_block)
        # 更早轮次压缩为单行摘要（多行正文只剩首行）
        self.assertIn("[更早会话摘要]", ctx.history_block)
        self.assertIn("第1个问题：找山西旅游第1天的照片", ctx.history_block)
        self.assertIn("回答：# 第1天成果", ctx.history_block)
        self.assertNotIn("正文内容1", ctx.history_block)
        self.assertNotIn("正文内容2", ctx.history_block)

    def test_single_turn_has_no_older_summary_section(self):
        messages = [
            _message("user", "找山西旅游第一天的照片"),
            _message("assistant", "# 山西首日"),
        ]
        ctx = ctx_builder.build_session_context(messages)
        self.assertNotIn("[更早会话摘要]", ctx.history_block)
        self.assertIn("[最近会话]", ctx.history_block)


class CompressionBoundTest(unittest.TestCase):
    """压缩：长会话输出有界，超限丢弃最早的轮次并标记。"""

    def test_older_turns_capped_with_truncated_flag(self):
        messages = []
        for index in range(1, 12):
            messages.append(_message("user", f"第{index}问"))
            messages.append(_message("assistant", f"答{index}"))
        ctx = ctx_builder.build_session_context(messages)
        self.assertTrue(ctx.truncated)
        # 11 轮 → 保留最近 2 轮原文 + 6 行摘要，最早的轮次被丢弃
        self.assertEqual(ctx.turn_count, 8)
        self.assertNotIn("第3问", ctx.history_block)
        self.assertIn("第4问", ctx.history_block)
        self.assertIn("第11问", ctx.history_block)

    def test_retained_turns_keep_original_ordinal_after_truncation(self):
        """截断最早轮次后，序数指代仍对应原始会话，而非保留窗口的局部序号。"""
        messages = []
        for index in range(1, 11):
            messages.append(_message("user", f"原始第{index}轮问题"))
            messages.append(_message("assistant", f"原始第{index}轮回答"))

        ctx = ctx_builder.build_session_context(messages)

        self.assertTrue(ctx.truncated)
        self.assertIn("第3轮 用户：原始第3轮问题", ctx.history_block)
        self.assertIn("— 第9轮 —", ctx.history_block)
        self.assertIn("— 第10轮 —", ctx.history_block)
        self.assertNotIn("第1轮 用户：原始第3轮问题", ctx.history_block)

    def test_huge_messages_produce_bounded_block(self):
        """逐项截断保证输出长度有界：海量输入不会撑爆历史块。"""
        messages = []
        for _ in range(30):
            messages.append(_message("user", "长问题" * 2000))
            messages.append(_message("assistant", "长回答" * 2000))
        ctx = ctx_builder.build_session_context(messages)
        self.assertTrue(ctx.truncated)
        # 轮数与单条截断上限共同约束，总长远离原始输入的 12 万字符
        self.assertLess(len(ctx.history_block), 4000)
        self.assertLess(len(ctx.history_block), 120_000)


class ReferenceTest(unittest.TestCase):
    """引用：照片只保留 ID 引用与数量，详情不进入上下文。"""

    def test_photo_ids_referenced_with_bound(self):
        photos = [{"photo_id": f"p{i}"} for i in range(20)]
        messages = [
            _message("user", "选片"),
            _message("assistant", "已选好", photos=photos),
        ]
        ctx = ctx_builder.build_session_context(messages)
        self.assertIn("照片引用：p0、p1", ctx.history_block)
        self.assertIn("共 20 张", ctx.history_block)
        # 引用有界：p15 超出上限不逐个列出
        self.assertNotIn("p15", ctx.history_block)

    def test_photo_count_visible_in_older_summary(self):
        photos = [{"photo_id": f"p{i}"} for i in range(3)]
        messages = [
            _message("user", "找照片"),
            _message("assistant", "# 标题\n正文", photos=photos),
            _message("user", "再来一组"),
            _message("assistant", "第二组"),
            _message("user", "第三组"),
            _message("assistant", "第三组完成"),
        ]
        ctx = ctx_builder.build_session_context(messages)
        self.assertIn("（照片 3 张，引用：p0、p1、p2）", ctx.history_block)


class OlderReferenceTest(unittest.TestCase):
    """长程指代（AR4-6）：更早轮次摘要保留有界 ID 引用，长会话可展开具体所指。"""

    def _long_session(self, first_turn_photos: list[dict]) -> list[dict]:
        messages = [
            _message("user", "找山西旅游第一天的照片并生成发布文案"),
            _message("assistant", "# 山西首日", photos=first_turn_photos),
        ]
        for index in range(2, 6):
            messages.append(_message("user", f"第{index}轮问题"))
            messages.append(_message("assistant", f"第{index}轮回答"))
        return messages

    def test_first_turn_photo_ids_visible_in_long_session(self):
        photos = [{"photo_id": f"p{i}"} for i in range(3)]
        ctx = ctx_builder.build_session_context(self._long_session(photos))
        # 第 1 轮已滑出近窗口，其照片 ID 仍在摘要行中可见，指代可展开
        self.assertIn("第1轮 用户：找山西旅游第一天的照片", ctx.history_block)
        self.assertIn("引用：p0、p1、p2", ctx.history_block)

    def test_older_reference_capped_with_total_count(self):
        photos = [{"photo_id": f"p{i}"} for i in range(10)]
        ctx = ctx_builder.build_session_context(self._long_session(photos))
        self.assertIn("（照片 10 张，引用：p0、p1、p2、p3、p4、p5…）", ctx.history_block)
        # 超出摘要引用上限的 ID 不逐个列出（p9 只可能以「共/照片 10 张」计数形式出现）
        self.assertNotIn("p9", ctx.history_block)

    def test_older_turn_without_photos_has_no_reference(self):
        messages = self._long_session([])
        ctx = ctx_builder.build_session_context(messages)
        self.assertIn("第1轮 用户：", ctx.history_block)
        self.assertNotIn("引用：", ctx.history_block.split("[最近会话]")[0])


class PriorityTest(unittest.TestCase):
    """优先级：当前用户消息由调用方独立传入，历史块只承载指代与约束线索。"""

    def test_user_constraint_text_kept_verbatim_in_older_summary(self):
        """更早轮次的硬约束（日期/范围）原样保留，不因压缩丢失。"""
        constraint = "2026年8月山西旅游第一天傍晚"
        messages = [
            _message("user", f"找{constraint}的照片并生成发布文案"),
            _message("assistant", "# 山西首日傍晚"),
            _message("user", "再来一张"),
            _message("assistant", "完成"),
            _message("user", "最后确认"),
            _message("assistant", "完成"),
        ]
        ctx = ctx_builder.build_session_context(messages)
        self.assertIn(constraint, ctx.history_block)


if __name__ == "__main__":
    unittest.main()

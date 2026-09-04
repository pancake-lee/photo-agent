"""AR2-7 故障注入回归集与 V2 指标基线（不依赖真实 LLM 与外部服务）。

七类注入故障（04 文档 V2 验收）各建图级确定性场景，mock 能力边界注入：
    SQL 空结果（硬范围空 / 软提示零命中）、RAG 低置信、工具超时（瞬时 / 持续）、
    重复旅行歧义、photo_id 失效、异常输出结构、连续无新信息。

每个场景声明注入器视角的 Ground Truth（是否可恢复 + 合理恢复动作清单），
跑完整 run_runtime 循环后分类结局，据此统计三项 V2 指标：
    恢复成功率    可恢复故障最终是否完成
    正确停止率    不可恢复时是否停止且说明原因（含澄清，不含预算耗尽伪装）
    无谓重试率    对永久错误或空集的盲目恢复尝试占比

基线数字写入 docs/eval/baseline.md；本文件重复生成：
    python tests/test_runtime_fault_injection.py --metrics
"""

import contextlib
import dataclasses
import sys
import typing
import unittest
import unittest.mock

import httpx

import internal.chat.text_to_sql as text_to_sql
import internal.posts.post_studio as post_studio
import internal.runtime.capabilities as rt_capabilities
import internal.runtime.capabilities.common as caps_common
import internal.runtime.capabilities.resolve_trip as caps_resolve_trip
import internal.runtime.graph as rt_graph
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state


def _cfg(**overrides):
    attrs = {
        "go_backend_url": "http://backend",
        "compose_group_limit": 20,
        "compose_cover_limit": 40,
        "rag_distance_threshold": None,
        "rag_auto_distance_ratio": 1.8,
        "runtime_max_steps": 6,
        "runtime_timeout_seconds": 300.0,
        "runtime_cost_limit": 2.0,
        "runtime_retry_max": 2,
        "runtime_repair_max": 2,
        "runtime_redecide_max": 2,
    }
    attrs.update(overrides)
    return type("Config", (), attrs)()


_PHOTOS = [
    {"id": "a", "filename": "a.jpg", "description": "寺庙", "burst_group_id": "g1"},
    {"id": "b", "filename": "b.jpg", "description": "面馆", "burst_group_id": "g1",
     "is_burst_cover": True},
    {"id": "c", "filename": "c.jpg", "description": "山景"},
]

_CONSTRAINTS_DEFAULT = '{"timeline": "山西旅游", "day": "", "time_of_day": "", "soft_hints": []}'


class _ScriptedLLM:
    """伪 LLM：决策提示词消费脚本队列，选片提示词消费独立队列，其余按类型固定回答。

    decisions     决策脚本（按调用次序消费，耗尽后返回空 JSON，触发无效决策路径）
    constraints   约束抽取固定回答（resolve_trip）
    select        选片回答队列（耗尽后按默认 {"selected_ids": ["b", "c"]} 处理）
    """

    def __init__(
        self,
        decisions: list[str],
        constraints: str = _CONSTRAINTS_DEFAULT,
        select: list[str] | None = None,
    ):
        self._decisions = list(decisions)
        self._constraints = constraints
        self._select = list(select or [])
        self.decide_prompts: list[str] = []
        self.select_prompts: list[str] = []
        self.judge_prompts: list[str] = []

    def invoke(self, messages):
        text = "".join(str(getattr(m, "content", m)) for m in messages)
        if "执行规划器" in text:
            self.decide_prompts.append(text)
            content = self._decisions.pop(0) if self._decisions else "{}"
        elif "时间线列表" in text:
            content = self._constraints
        elif "评委" in text:
            self.judge_prompts.append(text)
            content = '{"passed": true, "feedback": ""}'
        elif "摄影编辑" in text:
            self.select_prompts.append(text)
            content = self._select.pop(0) if self._select else '{"selected_ids": ["b", "c"]}'
        else:
            content = '{"selected_ids": ["b", "c"]}'
        resp = unittest.mock.MagicMock()
        resp.content = content
        return resp


def _happy_patches(llm):
    """成功路径依赖统一 mock：LLM 工厂、SQL 生成/执行、照片详情、文案生成。"""
    return [
        unittest.mock.patch.object(rt_graph.llm_factory, "create_llm", return_value=llm),
        unittest.mock.patch.object(text_to_sql,
                                  "generate_filter_sql", return_value="SELECT id FROM photos"),
        unittest.mock.patch.object(text_to_sql,
                                  "execute_sql_for_ids", return_value=["a", "b", "c"]),
        unittest.mock.patch.object(caps_common, "fetch_photos_batch",
                                  side_effect=lambda cfg, ids: [
                                      p for p in _PHOTOS if p.get("id") in ids
                                  ]),
        unittest.mock.patch.object(post_studio, "generate_post",
                                  return_value=("山西第一天", "正文内容", [])),
    ]


# --------------------------------------------------
# RAG 低置信注入：临时替换注册表中的 rag_search 能力
# --------------------------------------------------

def _low_confidence_rag_run(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
    """注入的 rag_search：有查询但证据不足，产出 low_confidence 观察。"""
    return rt_state.Observation(
        rt_state.OBS_PHOTO_IDS,
        "语义检索相似度均低于阈值，结果可信度不足",
        {"ids": [], "source": "rag"},
        status=rt_state.STATUS_LOW_CONFIDENCE,
    )


def _registry_with_low_confidence_rag() -> rt_registry.CapabilityRegistry:
    """复制正式注册表，仅替换 rag_search 的执行函数（能力声明的其余部分不变）。"""
    original = rt_capabilities.build_registry()
    custom = rt_registry.CapabilityRegistry()
    for name in original.names():
        capability = original.get(name)
        if name == "rag_search":
            capability = dataclasses.replace(capability, run=_low_confidence_rag_run)
        custom.register(capability)
    return custom


# --------------------------------------------------
# 场景 harness
# --------------------------------------------------

@dataclasses.dataclass
class RunOutcome:
    """场景执行器返回的原始观测：run_runtime 结果 + 场景私有记录点。"""

    result: dict
    llm: _ScriptedLLM
    extra: dict


@dataclasses.dataclass
class FaultScenario:
    """一类注入故障的声明与执行器。

    recoverable          注入器判定：该故障在预算内是否可恢复（Ground Truth）
    justified_recovery   本场景合理的恢复计数（超出部分计为无谓重试）：
                         瞬时故障的有界重试、可修复缺陷的带反馈修复属合理动作；
                         永久错误/空集上的任何重试都属无谓
    run                  装配 patches 与脚本并执行一次 run_runtime
    """

    name: str
    category: str
    recoverable: bool
    justified_recovery: dict[str, int]
    run: typing.Callable[[], RunOutcome]


@dataclasses.dataclass
class RunRecord:
    """一次注入场景的完整记录（场景声明 + 执行结局）。"""

    scenario: FaultScenario
    result: dict
    llm: _ScriptedLLM
    extra: dict


def _invoke(question: str, llm: _ScriptedLLM, patches, extra_patches=()) -> dict:
    """在全部 patch 生效期间执行一次 run_runtime。"""
    with contextlib.ExitStack() as stack:
        for patch in (*patches, *extra_patches):
            stack.enter_context(patch)
        return rt_graph.run_runtime(_cfg(), question)


# —— 场景 1：SQL 空结果 · 硬范围为空（不可恢复，确定性终态） ——

def _run_sql_empty_hard_scope() -> RunOutcome:
    llm = _ScriptedLLM(
        ['{"action": "resolve_trip", "params": {}, "reason": "先确认候选范围"}'],
        constraints='{"timeline": "山西旅游", "day": "first", "time_of_day": "夜晚",'
                    ' "soft_hints": []}',
    )
    patches = _happy_patches(llm)
    extra = [
        unittest.mock.patch.object(
            caps_resolve_trip, "_fetch_timelines", return_value=["山西旅游", "北京街拍"],
        ),
        unittest.mock.patch.object(text_to_sql, "execute_sql_for_ids", return_value=[]),
    ]
    result = _invoke("找山西旅游第一天夜晚的照片并生成发布文案", llm, patches, extra)
    return RunOutcome(result, llm, {})


# —— 场景 2：SQL 空结果 · 软提示零命中（可恢复，权威范围兜底） ——

def _run_sql_empty_soft_hint() -> RunOutcome:
    llm = _ScriptedLLM(
        [
            '{"action": "resolve_trip", "params": {}, "reason": "先确认候选范围"}',
            '{"action": "sql_search", "params": {"query": "太原植物园 植物"}, "reason": "软提示检索"}',
            '{"action": "select_photos", "params": {}, "reason": "挑选"}',
            '{"action": "write_post", "params": {}, "reason": "文案"}',
        ],
        constraints='{"timeline": "山西旅游", "day": "first", "time_of_day": "傍晚",'
                    ' "soft_hints": ["太原植物园", "植物"]}',
    )

    def fake_execute(base_url, sql, limit=50):
        return ["a", "b", "c"] if "timeline = '山西旅游'" in sql else []

    patches = _happy_patches(llm)
    patches[2] = unittest.mock.patch.object(
        text_to_sql, "execute_sql_for_ids", side_effect=fake_execute,
    )
    extra = [unittest.mock.patch.object(
        caps_resolve_trip, "_fetch_timelines", return_value=["山西旅游", "北京街拍"],
    )]
    result = _invoke("找山西旅游第一天傍晚的照片并生成发布文案", llm, patches, extra)
    return RunOutcome(result, llm, {})


# —— 场景 3：RAG 低置信（可恢复，换策略建议） ——

def _run_rag_low_confidence() -> RunOutcome:
    llm = _ScriptedLLM(
        [
            '{"action": "resolve_trip", "params": {}, "reason": "先确认候选范围"}',
            '{"action": "rag_search", "params": {"query": "寺庙"}, "reason": "语义检索"}',
            '{"action": "sql_search", "params": {"query": "寺庙"}, "reason": "换结构化检索"}',
            '{"action": "select_photos", "params": {}, "reason": "挑选"}',
            '{"action": "write_post", "params": {}, "reason": "文案"}',
        ],
    )
    patches = _happy_patches(llm)
    extra = [
        unittest.mock.patch.object(
            caps_resolve_trip, "_fetch_timelines", return_value=["山西旅游", "北京街拍"],
        ),
        unittest.mock.patch.object(
            rt_graph, "_registry", _registry_with_low_confidence_rag(),
        ),
    ]
    result = _invoke("找山西旅游的照片并生成发布文案", llm, patches, extra)
    return RunOutcome(result, llm, {})


# —— 场景 4：工具超时 · 瞬时（可恢复，有界重试） ——

def _run_tool_timeout_transient() -> RunOutcome:
    llm = _ScriptedLLM(
        [
            '{"action": "sql_search", "params": {"query": "山西"}, "reason": "检索"}',
            '{"action": "select_photos", "params": {}, "reason": "挑选"}',
            '{"action": "write_post", "params": {}, "reason": "文案"}',
        ],
    )
    calls: list[str] = []

    def flaky_execute(base_url, sql, limit=50):
        calls.append(sql)
        if len(calls) == 1:
            raise httpx.ReadTimeout("backend read timeout")
        return ["a", "b", "c"]

    patches = _happy_patches(llm)
    patches[2] = unittest.mock.patch.object(
        text_to_sql, "execute_sql_for_ids", side_effect=flaky_execute,
    )
    result = _invoke("找山西旅游的照片并生成发布文案", llm, patches)
    return RunOutcome(result, llm, {"sql_calls": len(calls)})


# —— 场景 5：工具超时 · 持续（不可恢复，重试耗尽正确停止） ——

def _run_tool_timeout_persistent() -> RunOutcome:
    llm = _ScriptedLLM(
        ['{"action": "sql_search", "params": {"query": "山西"}, "reason": "检索"}'],
    )
    patches = _happy_patches(llm)
    patches[2] = unittest.mock.patch.object(
        text_to_sql, "execute_sql_for_ids",
        side_effect=httpx.ReadTimeout("backend read timeout"),
    )
    result = _invoke("找山西旅游的照片并生成发布文案", llm, patches)
    return RunOutcome(result, llm, {})


# —— 场景 6：重复旅行歧义（不可恢复，澄清即正确停止） ——

def _run_duplicate_trip_ambiguity() -> RunOutcome:
    llm = _ScriptedLLM(
        ['{"action": "resolve_trip", "params": {}, "reason": "先确认候选范围"}'],
    )
    patches = _happy_patches(llm)
    extra = [unittest.mock.patch.object(
        caps_resolve_trip, "_fetch_timelines",
        return_value=["2026 山西旅游", "2025 山西旅游"],
    )]
    result = _invoke("找山西旅游的照片并生成发布文案", llm, patches, extra)
    return RunOutcome(result, llm, {})


# —— 场景 7：photo_id 失效（可恢复，带反馈修复） ——

def _run_photo_id_stale() -> RunOutcome:
    llm = _ScriptedLLM(
        [
            '{"action": "sql_search", "params": {"query": "山西"}, "reason": "检索"}',
            '{"action": "select_photos", "params": {}, "reason": "挑选"}',
            '{"action": "write_post", "params": {}, "reason": "文案"}',
        ],
        select=[
            '{"selected_ids": ["ghost-1", "ghost-2"]}',   # 首次挑选全部为幻觉 ID
            '{"selected_ids": ["b", "c"]}',               # 修复后返回合法 ID
        ],
    )
    patches = _happy_patches(llm)
    result = _invoke("找山西旅游的照片并生成发布文案", llm, patches)
    return RunOutcome(result, llm, {})


# —— 场景 8：异常输出结构（可恢复，再决策） ——

def _run_malformed_decision_output() -> RunOutcome:
    llm = _ScriptedLLM(
        [
            "先帮我查一下照片，谢谢",                                # 非 JSON 输出
            '{"action": "sql_search", "params": {"query": "山西"}, "reason": "检索"}',
            '{"action": "select_photos", "params": {}, "reason": "挑选"}',
            '{"action": "write_post", "params": {}, "reason": "文案"}',
        ],
    )
    patches = _happy_patches(llm)
    result = _invoke("找山西旅游的照片并生成发布文案", llm, patches)
    return RunOutcome(result, llm, {})


# —— 场景 9：连续无新信息（不可恢复，两级响应后停止） ——

def _run_no_new_info_loop() -> RunOutcome:
    llm = _ScriptedLLM(
        ['{"action": "sql_search", "params": {"query": "山西"}, "reason": "检索"}'] * 8,
    )
    patches = _happy_patches(llm)
    patches[3] = unittest.mock.patch.object(
        caps_common, "fetch_photos_batch", side_effect=lambda cfg, ids: [],
    )
    result = _invoke("找山西旅游的照片并生成发布文案", llm, patches)
    return RunOutcome(result, llm, {})


SCENARIOS: list[FaultScenario] = [
    FaultScenario(
        name="sql_empty_hard_scope", category="SQL 空结果（硬范围空）",
        recoverable=False, justified_recovery={}, run=_run_sql_empty_hard_scope,
    ),
    FaultScenario(
        name="sql_empty_soft_hint", category="SQL 空结果（软提示零命中）",
        recoverable=True, justified_recovery={}, run=_run_sql_empty_soft_hint,
    ),
    FaultScenario(
        name="rag_low_confidence", category="RAG 低置信",
        recoverable=True, justified_recovery={}, run=_run_rag_low_confidence,
    ),
    FaultScenario(
        name="tool_timeout_transient", category="工具超时（瞬时）",
        recoverable=True, justified_recovery={"retry:sql_search": 1},
        run=_run_tool_timeout_transient,
    ),
    FaultScenario(
        name="tool_timeout_persistent", category="工具超时（持续）",
        recoverable=False, justified_recovery={"retry:sql_search": 2},
        run=_run_tool_timeout_persistent,
    ),
    FaultScenario(
        name="duplicate_trip_ambiguity", category="重复旅行歧义",
        recoverable=False, justified_recovery={}, run=_run_duplicate_trip_ambiguity,
    ),
    FaultScenario(
        name="photo_id_stale", category="photo_id 失效",
        recoverable=True, justified_recovery={"repair:select_photos": 1},
        run=_run_photo_id_stale,
    ),
    FaultScenario(
        name="malformed_decision_output", category="异常输出结构",
        recoverable=True, justified_recovery={"redecide": 1},
        run=_run_malformed_decision_output,
    ),
    FaultScenario(
        name="no_new_info_loop", category="连续无新信息",
        recoverable=False, justified_recovery={}, run=_run_no_new_info_loop,
    ),
]

_BY_NAME = {scenario.name: scenario for scenario in SCENARIOS}


def run_scenario(name: str) -> RunRecord:
    scenario = _BY_NAME[name]
    outcome = scenario.run()
    return RunRecord(scenario=scenario, result=outcome.result,
                     llm=outcome.llm, extra=outcome.extra)


# --------------------------------------------------
# 结局分类与指标计算
# --------------------------------------------------

def is_recovered(record: RunRecord) -> bool:
    """可恢复故障最终完成：无终态/停止原因，交付照片与带标题的回答。"""
    result = record.result
    return (
        not result["terminal_reason"]
        and not result["stop_reason"]
        and bool(result["photos"])
        and "#" in result["answer"]
    )


def is_correct_stop(record: RunRecord) -> bool:
    """不可恢复时正确停止：确定性终态或无进展停止，回答说明原因且不伪装成预算耗尽。"""
    if is_recovered(record):
        return False
    result = record.result
    stopped = bool(result["terminal_reason"]) or result["stop_reason"] == "no_progress"
    explains = bool(result["answer"]) and "预算已耗尽" not in result["answer"]
    return stopped and explains


def unnecessary_recovery_attempts(record: RunRecord) -> int:
    """超出场景合理恢复清单的尝试次数（对永久错误/空集的盲目重试计为无谓）。"""
    actual = record.result["recovery_used"]
    justified = record.scenario.justified_recovery
    count = 0
    for key, used in actual.items():
        count += max(0, used - justified.get(key, 0))
    return count


@dataclasses.dataclass
class MetricsReport:
    """V2 三项指标与逐场景明细。"""

    recovery_success_rate: float
    correct_stop_rate: float
    unnecessary_retry_rate: float
    recovered: int
    recoverable: int
    correct_stops: int
    non_recoverable: int
    unnecessary_attempts: int
    total_attempts: int
    rows: list[dict]


def compute_metrics(records: list[RunRecord]) -> MetricsReport:
    recoverable = [r for r in records if r.scenario.recoverable]
    non_recoverable = [r for r in records if not r.scenario.recoverable]
    recovered = sum(1 for r in recoverable if is_recovered(r))
    correct_stops = sum(1 for r in non_recoverable if is_correct_stop(r))
    unnecessary = sum(unnecessary_recovery_attempts(r) for r in records)
    total_attempts = sum(sum(r.result["recovery_used"].values()) for r in records)
    return MetricsReport(
        recovery_success_rate=recovered / len(recoverable) if recoverable else 1.0,
        correct_stop_rate=correct_stops / len(non_recoverable) if non_recoverable else 1.0,
        unnecessary_retry_rate=unnecessary / total_attempts if total_attempts else 0.0,
        recovered=recovered, recoverable=len(recoverable),
        correct_stops=correct_stops, non_recoverable=len(non_recoverable),
        unnecessary_attempts=unnecessary, total_attempts=total_attempts,
        rows=[
            {
                "场景": r.scenario.name,
                "类别": r.scenario.category,
                "可恢复": "是" if r.scenario.recoverable else "否",
                "结局": ("已恢复" if is_recovered(r)
                        else "正确停止" if is_correct_stop(r) else "未按预期"),
                "恢复计数": r.result["recovery_used"] or {},
            }
            for r in records
        ],
    )


def format_metrics(report: MetricsReport) -> str:
    lines = ["V2 故障注入指标（AR2-7 基线）", "=" * 46]
    for row in report.rows:
        lines.append(
            f"  {row['场景']:<28} {row['结局']:<4} 恢复={row['恢复计数']}"
        )
    lines += [
        "-" * 46,
        f"恢复成功率   {report.recovered}/{report.recoverable}"
        f" = {report.recovery_success_rate:.1%}",
        f"正确停止率   {report.correct_stops}/{report.non_recoverable}"
        f" = {report.correct_stop_rate:.1%}",
        f"无谓重试率   {report.unnecessary_attempts}/{report.total_attempts}"
        f" = {report.unnecessary_retry_rate:.1%}",
    ]
    return "\n".join(lines)


# --------------------------------------------------
# 七类注入的恢复路径断言
# --------------------------------------------------

class SqlEmptyResultInjectionTest(unittest.TestCase):
    """SQL 空结果：硬范围空是确定性终态，软提示零命中由权威范围兜底，均不盲目重试。"""

    def test_hard_scope_empty_stops_deterministically(self):
        record = run_scenario("sql_empty_hard_scope")
        self.assertEqual(record.result["terminal_reason"], "empty_scope")
        self.assertIn("未找到符合条件的照片", record.result["answer"])
        self.assertIn("放宽条件", record.result["answer"])
        self.assertEqual(record.result["photos"], [])
        # 空集不触发任何恢复尝试（无谓重试率的核心断言）
        self.assertEqual(record.result["recovery_used"], {})
        self.assertEqual(len(record.llm.decide_prompts), 1)

    def test_soft_hint_zero_match_falls_back_to_scope_and_completes(self):
        record = run_scenario("sql_empty_soft_hint")
        self.assertTrue(is_recovered(record), record.result["answer"])
        self.assertEqual(record.result["recovery_used"], {})
        # 空结果是合法观察直接接受：候选回落为权威范围而非空集，任务继续
        self.assertIn("候选范围: 山西旅游第一天傍晚（硬约束，共 3 张）",
                      record.llm.decide_prompts[1])


class RagLowConfidenceInjectionTest(unittest.TestCase):
    """RAG 低置信：换策略建议注入决策上下文，由 decide 采纳后任务完成。"""

    def test_low_confidence_switches_strategy_and_completes(self):
        record = run_scenario("rag_low_confidence")
        self.assertTrue(is_recovered(record), record.result["answer"])
        # 第三次决策（换用 sql_search）的提示词携带换策略反馈
        self.assertIn("证据不足", record.llm.decide_prompts[2])
        self.assertIn("建议更换检索方式", record.llm.decide_prompts[2])
        # 换策略是建议注入而非恢复动作，不消耗恢复预算
        self.assertEqual(record.result["recovery_used"], {})


class ToolTimeoutInjectionTest(unittest.TestCase):
    """工具超时：瞬时故障同能力同参数有界重试后完成；持续超时耗尽后可行动停止。"""

    def test_transient_timeout_retries_once_and_completes(self):
        record = run_scenario("tool_timeout_transient")
        self.assertTrue(is_recovered(record), record.result["answer"])
        self.assertEqual(record.extra["sql_calls"], 2)
        # 重试不重新决策：三次决策对应三个正常步骤
        self.assertEqual(len(record.llm.decide_prompts), 3)
        self.assertEqual(record.result["recovery_used"], {"retry:sql_search": 1})

    def test_persistent_timeout_exhausts_into_actionable_stop(self):
        record = run_scenario("tool_timeout_persistent")
        self.assertEqual(record.result["terminal_reason"], "retry_exhausted")
        self.assertIn("已重试 2 次", record.result["answer"])
        self.assertIn("确认相关服务", record.result["answer"])
        self.assertNotIn("预算已耗尽", record.result["answer"])
        # 重试期间不再消耗决策
        self.assertEqual(len(record.llm.decide_prompts), 1)
        self.assertEqual(record.result["recovery_used"], {"retry:sql_search": 2})


class DuplicateTripInjectionTest(unittest.TestCase):
    """重复旅行歧义：两条同名旅行触发澄清而非静默选择，是正确停止的一种。"""

    def test_duplicate_timelines_ask_for_clarification(self):
        record = run_scenario("duplicate_trip_ambiguity")
        self.assertEqual(record.result["terminal_reason"], "needs_clarification")
        self.assertIn("2 条时间线", record.result["answer"])
        self.assertIn("2026 山西旅游", record.result["answer"])
        self.assertIn("2025 山西旅游", record.result["answer"])
        self.assertIn("请回复完整名称", record.result["answer"])
        self.assertEqual(record.result["clarification"].get("confirm_kind"), "timeline")
        self.assertEqual(record.result["photos"], [])
        self.assertEqual(record.result["recovery_used"], {})
        self.assertEqual(len(record.llm.decide_prompts), 1)


class StalePhotoIdInjectionTest(unittest.TestCase):
    """photo_id 失效：挑选结果全为幻觉 ID 时带反馈修复，第二次返回合法 ID 后完成。"""

    def test_hallucinated_ids_repaired_with_feedback(self):
        record = run_scenario("photo_id_stale")
        self.assertTrue(is_recovered(record), record.result["answer"])
        self.assertEqual(record.result["recovery_used"], {"repair:select_photos": 1})
        # 修复反馈进入第二次选片提示词（携带失败摘要，AR2-3 约定）
        self.assertEqual(len(record.llm.select_prompts), 2)
        self.assertIn("上次挑选未通过", record.llm.select_prompts[1])
        self.assertIn("挑选结果为空或均不在候选内", record.llm.select_prompts[1])
        # 修复不重新决策
        self.assertEqual(len(record.llm.decide_prompts), 3)


class MalformedOutputInjectionTest(unittest.TestCase):
    """异常输出结构：决策输出非 JSON 时错误摘要反馈 decide，修正后任务完成。"""

    def test_non_json_decision_redecides_and_completes(self):
        record = run_scenario("malformed_decision_output")
        self.assertTrue(is_recovered(record), record.result["answer"])
        self.assertEqual(record.result["recovery_used"], {"redecide": 1})
        self.assertIn("上一决策无效", record.llm.decide_prompts[1])


class NoNewInfoInjectionTest(unittest.TestCase):
    """连续无新信息：先注入换策略反馈，仍无进展才停止，全程无盲目恢复。"""

    def test_stalled_loop_two_phase_response(self):
        record = run_scenario("no_new_info_loop")
        self.assertEqual(record.result["stop_reason"], "no_progress")
        self.assertIn("没有任何新进展", record.result["answer"])
        self.assertNotIn("预算已耗尽", record.result["answer"])
        # 第 3 步注入换策略反馈，第 4 步仍无进展停止
        self.assertEqual(len(record.llm.decide_prompts), 4)
        self.assertIn("没有任何变化", record.llm.decide_prompts[3])
        # 每步观察都是成功空兜底，不应有任何恢复尝试
        self.assertEqual(record.result["recovery_used"], {})


# --------------------------------------------------
# V2 指标基线
# --------------------------------------------------

class V2MetricsBaselineTest(unittest.TestCase):
    """在完整注入集上统计三项指标并锚定 V2 基线（写入 docs/eval/baseline.md）。"""

    def test_v2_baseline_metrics(self):
        records = [run_scenario(scenario.name) for scenario in SCENARIOS]
        report = compute_metrics(records)
        # 逐场景结局必须全部符合注入器判定，否则指标失去意义
        for row in report.rows:
            self.assertNotEqual(row["结局"], "未按预期", row)
        self.assertEqual(
            (report.recovery_success_rate, report.correct_stop_rate,
             report.unnecessary_retry_rate),
            (1.0, 1.0, 0.0),
            format_metrics(report),
        )
        self.assertEqual((report.recoverable, report.non_recoverable), (5, 4))
        self.assertEqual(report.total_attempts, 5)  # 重试3 + 修复1 + 再决策1


if __name__ == "__main__":
    if "--metrics" in sys.argv:
        records = [run_scenario(scenario.name) for scenario in SCENARIOS]
        print(format_metrics(compute_metrics(records)))
    else:
        unittest.main()

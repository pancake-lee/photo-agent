"""
    启发式规则评估引擎。

    加载 eval_rules.yaml 配置，对聚类结果执行启发式规则检查，
    生成评估报告并以 JSONL 行追加到 data/agent/execution-traces/YYYY-MM-DD.jsonl（按天拆分）。

    用法:
        import chain.eval_engine as eval_engine

        # 加载规则
        rules = eval_engine.load_rules("data/agent/topic-discovery-evaluation-rules.yaml")

        # 执行评估
        report = eval_engine.evaluate_cluster_themes(result, rules)

        # 保存报告
        eval_engine.save_report(report, project_root)

        # CLI
        python chain/eval_engine.py --rules cluster_theme --result-id <id>
"""

import sys
import pathlib
import json
import uuid
import datetime
import logging
import typing

import yaml

logger = logging.getLogger(__name__)

# ── 类型定义 ──

RuleDef = dict
RuleResult = dict  # {rule_id, severity, passed, value, expected, message}
EvalReport = dict


# ── 规则加载 ──

def load_rules(yaml_path: str | pathlib.Path) -> dict[str, list[RuleDef]]:
    """从 YAML 文件加载启发式规则配置。

    返回:
        {"cluster_theme": [...], "attribute_availability": [...]}
    """
    fp = pathlib.Path(yaml_path)
    if not fp.exists():
        logger.warning("规则配置文件不存在: %s", fp)
        return {}
    with open(fp, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


# ── 规则执行 ──

def _check_rule(rule: RuleDef, cluster: dict, all_clusters: list[dict] | None = None) -> RuleResult:
    """对单个簇执行单条规则，返回检查结果。"""
    rule_id = rule["id"]
    severity = rule.get("severity", "error")
    desc = rule.get("description", rule_id)
    check = rule.get("check", {})

    # 跨簇规则（如 all_unique）
    scope = rule.get("scope", "")
    if scope == "all_clusters" and all_clusters is not None:
        return _check_all_clusters_rule(rule, all_clusters)

    field = check.get("field", "")
    op = check.get("op", "")
    value = cluster.get(field, "")

    # length_between
    if op == "length_between":
        lo = check.get("min", 0)
        hi = check.get("max", 999)
        actual = len(value) if value else 0
        passed = lo <= actual <= hi
        return {
            "rule_id": rule_id,
            "severity": severity,
            "passed": passed,
            "value": f"{actual} 字",
            "expected": f"{lo}-{hi} 字",
            "message": "" if passed else f"{desc}: 实际 {actual} 字，期望 {lo}-{hi} 字",
        }

    # not_contains_any
    if op == "not_contains_any":
        forbidden = check.get("values", [])
        found = [w for w in forbidden if w in (value or "")]
        passed = len(found) == 0
        return {
            "rule_id": rule_id,
            "severity": severity,
            "passed": passed,
            "value": f"含禁止词: {found}" if found else "无禁止词",
            "expected": f"不含 {forbidden}",
            "message": "" if passed else f"{desc}: 发现禁止词 {found}",
        }

    # min_length
    if op == "min_length":
        lo = check.get("min", 0)
        actual = len(value) if value else 0
        passed = actual >= lo
        return {
            "rule_id": rule_id,
            "severity": severity,
            "passed": passed,
            "value": f"{actual} 字",
            "expected": f"≥{lo} 字",
            "message": "" if passed else f"{desc}: 实际 {actual} 字，期望 ≥{lo} 字",
        }

    # 未知操作
    return {
        "rule_id": rule_id,
        "severity": severity,
        "passed": True,
        "value": "",
        "expected": "",
        "message": f"未知检查操作: {op}",
    }


def _check_all_clusters_rule(rule: RuleDef, clusters: list[dict]) -> RuleResult:
    """执行跨簇规则（如 all_unique）。"""
    rule_id = rule["id"]
    severity = rule.get("severity", "error")
    desc = rule.get("description", rule_id)
    check = rule.get("check", {})
    field = check.get("field", "")
    op = check.get("op", "")

    if op == "all_unique":
        values = [c.get(field, "") for c in clusters]
        seen: set[str] = set()
        dupes: set[str] = set()
        for v in values:
            if v in seen:
                dupes.add(v)
            seen.add(v)
        passed = len(dupes) == 0
        return {
            "rule_id": rule_id,
            "severity": severity,
            "passed": passed,
            "value": f"重复 {len(dupes)} 个" if dupes else "全部唯一",
            "expected": "所有簇标题互不相同",
            "message": "" if passed else f"{desc}: 重复标题 {sorted(dupes)}",
        }

    return {
        "rule_id": rule_id,
        "severity": severity,
        "passed": True,
        "value": "",
        "expected": "",
        "message": f"未知跨簇操作: {op}",
    }


def run_theme_rules(
    clusters: list[dict],
    rules: list[RuleDef],
) -> list[RuleResult]:
    """对一组簇执行启发式规则检查。

    参数:
        clusters: 簇列表，每个 dict 含 label / theme_description / cluster_id
        rules:    规则定义列表

    返回:
        检查结果列表
    """
    results: list[RuleResult] = []

    for rule in rules:
        scope = rule.get("scope", "")
        if scope == "all_clusters":
            r = _check_rule(rule, {}, all_clusters=clusters)
            results.append(r)
        else:
            for c in clusters:
                r = _check_rule(rule, c)
                r["cluster_id"] = c.get("cluster_id", -1)
                results.append(r)

    return results


# ── 属性可用性检查 ──

def check_attribute_availability(
    photo_attrs: list[dict],
    rules: list[RuleDef],
) -> list[RuleResult]:
    """检查照片结构化属性的可用性。

    参数:
        photo_attrs: 照片属性列表，每个 dict 含 objects/scene/colors 等字段
        rules:       属性可用性规则

    返回:
        检查结果列表
    """
    results: list[RuleResult] = []
    if not photo_attrs:
        return results

    total = len(photo_attrs)
    for rule in rules:
        field = rule.get("check", {}).get("field", "")
        op = rule.get("check", {}).get("op", "")
        lo = rule.get("check", {}).get("min", 0)

        if op == "non_empty_ratio":
            non_empty = sum(1 for p in photo_attrs if (p.get(field) or "").strip())
            ratio = non_empty / total if total > 0 else 0.0
            passed = ratio >= lo
            results.append({
                "rule_id": rule["id"],
                "severity": rule.get("severity", "warning"),
                "passed": passed,
                "value": f"{ratio:.1%} ({non_empty}/{total})",
                "expected": f"≥{lo:.0%}",
                "message": "" if passed else (
                    f"{rule.get('description', rule['id'])}: "
                    f"实际 {ratio:.1%}，期望 ≥{lo:.0%}"
                ),
            })

    return results


# ── 评估报告 ──

def evaluate_cluster_themes(
    result: typing.Any,  # ClusterResult
    rules: list[RuleDef],
    photo_attrs: list[dict] | None = None,
    attr_rules: list[RuleDef] | None = None,
) -> EvalReport:
    """对聚类结果的所有簇标题执行启发式规则评估，生成评估报告。

    参数:
        result:     ClusterResult 对象（含 clusters 列表）
        rules:      主题规则列表
        photo_attrs: 照片属性列表（可选，用于属性可用性检查）
        attr_rules:  属性可用性规则列表（可选）

    返回:
        评估报告 dict
    """
    # 将 ClusterInfo 转为 dict
    clusters_dict = [
        {
            "cluster_id": c.cluster_id,
            "label": c.label,
            "theme_description": c.theme_description,
            "size": c.size,
        }
        for c in (result.clusters or [])
    ]

    theme_results = run_theme_rules(clusters_dict, rules)

    passed = sum(1 for r in theme_results if r["passed"])
    failed = sum(1 for r in theme_results if not r["passed"])
    failures = [r for r in theme_results if not r["passed"]]

    report: EvalReport = {
        "report_id": uuid.uuid4().hex[:12],
        "created_at": datetime.datetime.now().isoformat(),
        "result_id": getattr(result, "id", ""),
        "total_clusters": len(clusters_dict),
        "heuristic": {
            "total_checks": len(theme_results),
            "passed": passed,
            "failed": failed,
            "failures": failures,
        },
    }

    # 属性可用性检查
    if photo_attrs and attr_rules:
        attr_results = check_attribute_availability(photo_attrs, attr_rules)
        report["attribute_availability"] = {
            "checks": attr_results,
            "passed": sum(1 for r in attr_results if r["passed"]),
            "failed": sum(1 for r in attr_results if not r["passed"]),
        }

    return report


# ── 报告文件读写 ──

def _traces_dir(project_root: str | pathlib.Path) -> pathlib.Path:
    d = pathlib.Path(project_root) / "data" / "agent" / "execution-traces"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _daily_jsonl_path(project_root: str | pathlib.Path) -> pathlib.Path:
    """当前日期的 JSONL 文件路径。"""
    today = datetime.date.today().isoformat()  # YYYY-MM-DD
    return _traces_dir(project_root) / f"{today}.jsonl"


def save_report(report: EvalReport, project_root: str | pathlib.Path) -> pathlib.Path:
    """以 JSONL 行追加评估报告到按天拆分的 trace 文件。返回文件路径。"""
    fp = _daily_jsonl_path(project_root)
    trace_line = {
        "ts": report.get("created_at", datetime.datetime.now().isoformat()),
        "level": "INFO",
        "trace_id": report.get("report_id", ""),
        "module": "eval_engine",
        "event": "eval.report",
        "data": report,
    }
    with open(fp, "a", encoding="utf-8") as f:
        f.write(json.dumps(trace_line, ensure_ascii=False, default=str) + "\n")
    logger.info("评估报告已追加: %s (report_id=%s)", fp, report.get("report_id"))
    return fp


def load_report(report_id: str, project_root: str | pathlib.Path) -> EvalReport | None:
    """从每日 JSONL trace 文件中加载指定 ID 的评估报告。"""
    d = _traces_dir(project_root)
    if not d.exists():
        return None
    for fp in sorted(d.glob("*.jsonl"), reverse=True):
        try:
            for line in fp.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("trace_id") == report_id and entry.get("event") == "eval.report":
                    return entry.get("data", entry)
        except (json.JSONDecodeError, OSError):
            continue
    return None


def list_reports(project_root: str | pathlib.Path) -> list[dict]:
    """列出所有评估报告摘要（从每日 JSONL trace 读取，按时间倒序）。"""
    d = _traces_dir(project_root)
    if not d.exists():
        return []
    results: list[dict] = []
    for fp in sorted(d.glob("*.jsonl"), reverse=True):
        try:
            for line in fp.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("event") != "eval.report":
                    continue
                data = entry.get("data", entry)
                results.append({
                    "report_id": data.get("report_id", entry.get("trace_id", "")),
                    "created_at": data.get("created_at", entry.get("ts", "")),
                    "result_id": data.get("result_id", ""),
                    "total_clusters": data.get("total_clusters", 0),
                    "heuristic_passed": data.get("heuristic", {}).get("passed", 0),
                    "heuristic_failed": data.get("heuristic", {}).get("failed", 0),
                    "has_attribute_check": "attribute_availability" in data,
                })
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("跳过损坏的 trace 文件 %s: %s", fp.name, e)
    # 按创建时间倒序
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return results

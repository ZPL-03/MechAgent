"""ReporterAgent。"""

from __future__ import annotations

import json
import re
from typing import Any

from mechagent.config import MechAgentConfig
from mechagent.orchestrator.llm_advisor import AgentLLMAdvisor, AgentLLMTrace
from mechagent.orchestrator.llm_payload import advisory_payload
from mechagent.orchestrator.models import SolverRunSummary, TaskRunRecord
from mechagent.redaction import redact_sensitive_text


class ReporterAgent:
    """生成 Markdown 报告。

    Args:
        无。

    Returns:
        ReporterAgent: Reporter 节点实例。

    Raises:
        无。

    Example:
        >>> ReporterAgent().render([])
        '# MechAgent 仿真报告\\n...'
    """

    def __init__(self, config: MechAgentConfig | None = None) -> None:
        self.advisor = AgentLLMAdvisor(config)

    def render(self, records: list[TaskRunRecord]) -> str:
        """渲染工作流报告。

        Args:
            records: 任务运行记录。

        Returns:
            str: Markdown 报告。

        Raises:
            无。

        Example:
            >>> ReporterAgent().render([])
            '# MechAgent 仿真报告\\n'
        """

        report, _ = self.render_with_trace(records)
        return report

    def render_with_trace(self, records: list[TaskRunRecord]) -> tuple[str, AgentLLMTrace]:
        """渲染工作流报告并返回 Reporter LLM 审计记录。

        Args:
            records: 任务运行记录。

        Returns:
            tuple[str, AgentLLMTrace]: Markdown 报告和 Reporter LLM 审计记录。

        Raises:
            无。
        """

        reporter_trace = self.advisor.complete(
            "ReporterAgent",
            "基于有限元求解结果生成工程解释性报告",
            advisory_payload(_report_context(records)),
            (
                "只输出 JSON 对象，字段包括 executive_summary、result_interpretation、"
                "mesh_and_solver_assessment、boundary_load_interpretation、limitations、"
                "recommended_next_steps。字段值使用中文字符串或中文字符串数组。"
                "内容只解释有限元模型、网格、求解结果、边界载荷、工程局限和复核建议，"
                "不得讨论 LLM 调用、Agent trace、网络请求、开发过程或执行链路审计。"
            ),
        )
        lines = [
            "# MechAgent 仿真报告",
            "",
            "## 任务摘要",
            "",
            "| 任务 | 算例 | 物理量 | 计算值 | 参考值 | 相对误差 | 阈值 | 状态 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
        for record in records:
            result = record.solver_result
            status = _status_label(result)
            case_label = _escape_table_text(_record_case_label(record))
            raw_quantity = result.quantity
            quantity = _escape_table_text(_format_quantity(raw_quantity, result.unit))
            value = _format_optional_number(_reported_value(result, raw_quantity))
            reference = _format_optional_number(result.reference)
            relative_error = _format_optional_percent(result.relative_error, precision=4)
            tolerance = _format_optional_percent(result.tolerance, precision=2)
            lines.append(
                f"| {_escape_table_text(record.task.task_id)} | {case_label} | {quantity} | "
                f"{value} | {reference} | {relative_error} | {tolerance} | {status} |"
            )

        lines.extend(["", "## 工程解读", ""])
        for record in records:
            if record.analysis_text:
                lines.append(f"- {record.analysis_text}")
            elif record.error is not None:
                message = redact_sensitive_text(record.error.message)
                lines.append(f"- {record.task.task_id} 执行失败：{message}")
            else:
                lines.append(f"- {record.task.task_id} 未生成工程解读。")

        _append_llm_engineering_report(lines, reporter_trace)

        failed_records = [record for record in records if record.error is not None]
        if failed_records:
            lines.extend(["", "## 错误诊断", ""])
            lines.append("| 任务 | 节点 | 错误码 | 缺失字段 | 信息 |")
            lines.append("| --- | --- | --- | --- | --- |")
            for record in failed_records:
                assert record.error is not None
                lines.append(
                    f"| {record.task.task_id} | {record.error.node} | "
                    f"{record.error.code} | "
                    f"{_escape_table_text(_format_missing_fields(record.error.missing_fields))} | "
                    f"{_escape_table_text(redact_sensitive_text(record.error.message))} |"
                )
        lines.extend(["", "## 阶段产物", ""])
        lines.append("| 任务 | 网格文件 | 求解输出数量 |")
        lines.append("| --- | --- | ---: |")
        for record in records:
            mesh_file = record.mesh_result.mesh_file if record.mesh_result else None
            output_count = len(record.solver_result.output_files)
            lines.append(
                f"| {_escape_table_text(record.task.task_id)} | "
                f"{_escape_table_text(str(mesh_file) if mesh_file else '')} | {output_count} |"
            )
        lines.extend(["", "## 执行链路摘要", ""])
        lines.append("| 任务 | 阶段 | 智能辅助 | 状态 |")
        lines.append("| --- | --- | --- | --- |")
        for record in records:
            for trace in _record_traces(record):
                lines.append(
                    f"| {_escape_table_text(record.task.task_id)} | "
                    f"{_escape_table_text(trace['stage'])} | "
                    f"{_escape_table_text(trace['used'])} | "
                    f"{_escape_table_text(trace['status'])} |"
                )
        reporter_status = (
            "ok" if reporter_trace.error is None else redact_sensitive_text(reporter_trace.error)
        )
        lines.append(
            f"| REPORT | {_escape_table_text(_stage_label(reporter_trace.agent))} | "
            f"{_trace_used_label(reporter_trace.used)} | {_escape_table_text(reporter_status)} |"
        )
        return "\n".join(lines) + "\n", reporter_trace


def _report_context(records: list[TaskRunRecord]) -> dict[str, object]:
    return {
        "report_goal": "面向工程用户解释有限元求解结果、可信度、边界载荷含义、局限和复核建议。",
        "report_scope": (
            "仅基于几何、材料、载荷、边界条件、网格、求解摘要和后处理标量进行工程解释。"
            "执行链路审计信息由报告固定表格呈现，不进入 LLM 工程解释。"
        ),
        "tasks": [_record_report_context(record) for record in records],
    }


def _record_report_context(record: TaskRunRecord) -> dict[str, object]:
    model_params = record.model_params
    return {
        "task": record.task.model_dump(mode="json", exclude={"planner_llm_trace"}),
        "geometry": _model_dump(model_params.geometry) if model_params is not None else None,
        "material": _model_dump(model_params.material) if model_params is not None else None,
        "loads": [_model_dump(load) for load in model_params.loads]
        if model_params is not None
        else [],
        "boundary_conditions": [_model_dump(bc) for bc in model_params.bcs]
        if model_params is not None
        else [],
        "analysis": _model_dump(model_params.analysis) if model_params is not None else None,
        "mesh_spec": _model_dump(model_params.mesh) if model_params is not None else None,
        "mesh_result": _model_dump(record.mesh_result),
        "solver_result": _model_dump(
            record.solver_result,
            exclude={"solver_llm_trace", "output_files", "mesh_file"},
        ),
        "post_summary": _model_dump(
            record.post_summary,
            exclude={"postproc_llm_trace", "analyst_llm_trace"},
        ),
        "deterministic_analysis_text": record.analysis_text,
        "error": _model_dump(record.error),
    }


def _model_dump(value: Any, *, exclude: set[str] | None = None) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude=exclude or set())
    return value


def _append_llm_engineering_report(lines: list[str], trace: AgentLLMTrace) -> None:
    if not trace.used or trace.error or not trace.response.strip():
        return
    payload = _parse_llm_report_json(trace.response)
    if not payload:
        return

    lines.extend(["", "## LLM 工程解释", ""])
    sections = [
        ("综合结论", "executive_summary"),
        ("结果解释", "result_interpretation"),
        ("网格与求解可信度", "mesh_and_solver_assessment"),
        ("边界与载荷解释", "boundary_load_interpretation"),
        ("局限", "limitations"),
        ("复核建议", "recommended_next_steps"),
    ]
    for title, key in sections:
        items = _normalized_report_items(payload.get(key))
        if not items:
            continue
        lines.extend([f"### {title}", ""])
        for item in items:
            lines.append(f"- {redact_sensitive_text(item)}")
        lines.append("")


def _parse_llm_report_json(response: str) -> dict[str, Any]:
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match is None:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalized_report_items(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _record_case_label(record: TaskRunRecord) -> str:
    if record.model_params is not None:
        return record.model_params.case_id or record.task.case_id
    return record.solver_result.model_case_id or record.task.case_id


def _reported_value(data: SolverRunSummary, quantity: str) -> float | None:
    value = data.predicted
    if isinstance(value, (int, float)):
        return float(value)

    key_by_quantity = {
        "tip_deflection": "tip_deflection_mm",
        "center_deflection": "center_deflection_mm",
        "max_displacement": "max_displacement_mm",
    }
    quantity_key = key_by_quantity.get(quantity)
    if quantity_key:
        quantity_value = data.get(quantity_key)
        if isinstance(quantity_value, (int, float)):
            return float(quantity_value)
    return None


def _status_label(result: SolverRunSummary) -> str:
    if not result.success:
        return "失败"
    if result.verification_status == "passed":
        return "通过"
    if result.verification_status == "failed":
        return "失败"
    return "未验证"


def _format_quantity(quantity: str, unit: str) -> str:
    return f"{quantity} ({unit})" if unit else quantity


def _format_optional_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.8g}"


def _format_optional_percent(value: float | None, *, precision: int) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{precision}%}"


def _record_traces(record: TaskRunRecord) -> list[dict[str, str]]:
    traces: list[dict[str, str]] = []
    for value in [
        record.task.planner_llm_trace,
        record.designer_llm_trace,
        record.mesh_llm_trace,
        record.solver_result.solver_llm_trace,
        record.post_summary.postproc_llm_trace,
        record.post_summary.analyst_llm_trace,
    ]:
        if value is not None:
            traces.append(_trace_summary(value))
    return traces


def _trace_summary(trace: AgentLLMTrace) -> dict[str, str]:
    stage = _stage_label(trace.agent)
    used = _trace_used_label(trace.used)
    error = trace.error
    status = redact_sensitive_text(str(error)) if error else "ok"
    return {"stage": stage, "used": used, "status": status}


def _trace_used_label(value: bool) -> str:
    return "启用" if value else "未启用"


def _stage_label(agent: str) -> str:
    labels = {
        "PlannerAgent": "任务识别",
        "Planner": "任务识别",
        "DesignerAgent": "参数建模",
        "Designer": "参数建模",
        "MeshAgent": "网格生成",
        "SolverAgent": "求解执行",
        "PostProcAgent": "结果提取",
        "PostProc": "结果提取",
        "AnalystAgent": "工程校核",
        "Analyst": "工程校核",
        "ReporterAgent": "报告输出",
        "Reporter": "报告输出",
    }
    return labels.get(agent, agent)


def _escape_table_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _format_missing_fields(fields: list[str]) -> str:
    return "、".join(fields) if fields else "无"

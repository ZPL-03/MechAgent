"""ReporterAgent。"""

from __future__ import annotations

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

        reporter_trace = self.advisor.advise(
            "ReporterAgent",
            "检查报告结构、阶段产物和结果摘要完整性",
            advisory_payload({"tasks": [record.task for record in records]}),
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
        lines.extend(["", "## Agent 通信摘要", ""])
        lines.append("| 任务 | Agent | LLM | 状态 |")
        lines.append("| --- | --- | --- | --- |")
        for record in records:
            for trace in _record_traces(record):
                lines.append(
                    f"| {_escape_table_text(record.task.task_id)} | "
                    f"{_escape_table_text(trace['agent'])} | "
                    f"{_escape_table_text(trace['used'])} | "
                    f"{_escape_table_text(trace['status'])} |"
                )
        reporter_status = (
            "ok" if reporter_trace.error is None else redact_sensitive_text(reporter_trace.error)
        )
        lines.append(
            f"| REPORT | {_escape_table_text(reporter_trace.agent)} | "
            f"{reporter_trace.used} | {_escape_table_text(reporter_status)} |"
        )
        return "\n".join(lines) + "\n", reporter_trace


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
    agent = trace.agent
    used = str(trace.used)
    error = trace.error
    status = redact_sensitive_text(str(error)) if error else "ok"
    return {"agent": agent, "used": used, "status": status}


def _escape_table_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _format_missing_fields(fields: list[str]) -> str:
    return "、".join(fields) if fields else "无"

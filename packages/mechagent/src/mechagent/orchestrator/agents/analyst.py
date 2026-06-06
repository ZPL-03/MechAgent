"""AnalystAgent。"""

from __future__ import annotations

from mechagent.config import MechAgentConfig
from mechagent.orchestrator.llm_advisor import AgentLLMAdvisor
from mechagent.orchestrator.llm_payload import advisory_payload
from mechagent.orchestrator.models import PostProcessingSummary, TaskItem


class AnalystAgent:
    """生成工程分析文本。

    Args:
        无。

    Returns:
        AnalystAgent: Analyst 节点实例。

    Raises:
        无。

    Example:
        >>> task = TaskItem(task_id="TASK_1", case_id="STATIC", title="x")
        >>> AnalystAgent().analyze(task, PostProcessingSummary())
        '...'
    """

    def __init__(self, config: MechAgentConfig | None = None) -> None:
        self.advisor = AgentLLMAdvisor(config)

    def analyze(self, task: TaskItem, post_summary: PostProcessingSummary) -> str:
        """分析仿真结果。

        Args:
            task: 任务描述。
            post_summary: 后处理摘要。

        Returns:
            str: 工程分析文本。

        Raises:
            无。

        Example:
            >>> AnalystAgent().analyze(task, PostProcessingSummary(passed=True))
            '...'
        """

        trace = self.advisor.advise(
            "AnalystAgent",
            "基于后处理结果生成工程解读并识别风险",
            advisory_payload({"task": task, "post_summary": post_summary}),
        )
        post_summary.analyst_llm_trace = trace
        passed = post_summary.passed
        case_id = post_summary.model_case_id or task.case_id
        quantity = post_summary.quantity
        unit = post_summary.unit
        predicted = _format_value(post_summary.predicted)
        if post_summary.relative_error is not None and post_summary.tolerance is not None:
            error = post_summary.relative_error
            tolerance = post_summary.tolerance
            status = "满足" if passed else "不满足"
            return (
                f"{case_id} {task.title} 的 {quantity} 计算值为 "
                f"{predicted} {unit}，解析参考误差为 {error:.6%}，"
                f"阈值为 {tolerance:.2%}，结果{status}验收标准。"
            )

        if post_summary.success and post_summary.verification_status == "unverified":
            return (
                f"{case_id} {task.title} 求解完成，未配置参考验收，"
                f"{quantity} 为 {predicted} {unit}。"
            )

        status = "完成" if passed else "失败"
        return f"{case_id} {task.title} {status}，{quantity} 为 {predicted} {unit}。"


def _format_value(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.8g}"

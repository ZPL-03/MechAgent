"""Planner Agent。"""

from __future__ import annotations

import re
from typing import Optional

from mechagent.config import MechAgentConfig
from mechagent.orchestrator.capabilities import (
    SimulationCapability,
    all_capabilities,
    get_capability,
    match_capabilities,
)
from mechagent.orchestrator.intent import SimulationIntent
from mechagent.orchestrator.llm_advisor import AgentLLMAdvisor
from mechagent.orchestrator.llm_structured import (
    capability_intent_contract,
    capability_intent_payload,
    parse_llm_capability_intent,
)
from mechagent.orchestrator.models import TaskItem


class PlannerAgent:
    """将自然语言请求拆分为结构化仿真任务。

    Args:
        无。

    Returns:
        PlannerAgent: Planner 节点实例。

    Raises:
        无。

    Example:
        >>> PlannerAgent().plan("长1000mm、截面20mmx40mm、材料钢的悬臂梁静力分析")[0].case_id
        'STATIC-STRUCTURAL'
    """

    def __init__(self, config: Optional[MechAgentConfig] = None) -> None:
        self.advisor = AgentLLMAdvisor(config)

    def plan(self, request: str) -> list[TaskItem]:
        """解析用户请求并生成任务列表。

        Args:
            request: 用户自然语言请求。

        Returns:
            list[TaskItem]: 任务列表。

        Raises:
            ValueError: 当请求为空或无法识别任务时抛出。

        Example:
            >>> PlannerAgent().plan("长1000mm、截面20mmx40mm、材料钢的悬臂梁静力分析")
            [TaskItem(...)]
        """

        text = request.strip()
        if not text:
            msg = "request 不能为空。"
            raise ValueError(msg)

        if _is_validation_case_request(text):
            msg = (
                "标准验证算例属于独立测试入口，请使用 `mechagent benchmark` "
                "或 `scripts/run_benchmarks.py`。"
            )
            raise ValueError(msg)

        intents = match_capabilities(text)
        if intents:
            tasks: list[TaskItem] = []
            trace = self.advisor.advise(
                "Planner",
                "识别仿真任务类型并检查意图完整性",
                text,
            )
            for index, intent in enumerate(intents, start=1):
                capability = get_capability(intent.capability_id)
                tasks.append(
                    TaskItem(
                        task_id=f"TASK_{index}",
                        case_id=capability.task_case_id,
                        capability_id=intent.capability_id,
                        title=capability.title,
                        analysis_type=intent.analysis_type,
                        intent=intent,
                        planner_llm_trace=trace,
                    )
                )
            return tasks

        llm_tasks = self._plan_with_llm(text)
        if llm_tasks:
            return llm_tasks

        msg = (
            f"工作流无法识别请求中的受支持分析类型。当前已注册能力: "
            f"{_supported_capability_titles()}。"
            "请求需包含几何、材料、载荷和边界条件。"
        )
        raise ValueError(msg)

    def _plan_with_llm(self, text: str) -> list[TaskItem]:
        capabilities = all_capabilities()
        trace = self.advisor.complete(
            "Planner",
            "从自然语言请求中选择一个已注册仿真能力",
            capability_intent_payload(text, capabilities),
            capability_intent_contract(capabilities),
        )
        intent, parsed_trace = parse_llm_capability_intent(trace, text, capabilities)
        if intent is None:
            return []
        capability = get_capability(intent.capability_id)
        intent = _merge_capability_diagnostics(intent, capability, text)
        return [
            TaskItem(
                task_id="TASK_1",
                case_id=capability.task_case_id,
                capability_id=intent.capability_id,
                title=capability.title,
                analysis_type=intent.analysis_type,
                intent=intent,
                planner_llm_trace=parsed_trace,
            )
        ]


def _merge_capability_diagnostics(
    intent: SimulationIntent,
    capability: SimulationCapability,
    text: str,
) -> SimulationIntent:
    capability_intent = capability.build_intent(text)
    missing_fields = _merge_missing_fields(
        capability_intent.missing_fields,
        intent.missing_fields,
    )
    confidence = intent.confidence if not missing_fields else min(intent.confidence, 0.75)
    return intent.model_copy(
        update={
            "analysis_type": intent.analysis_type or capability.analysis_type,
            "physics_domain": intent.physics_domain or capability.physics_domain,
            "geometry_type": intent.geometry_type or capability_intent.geometry_type,
            "missing_fields": missing_fields,
            "confidence": confidence,
            "source": "llm",
        }
    )


def _merge_missing_fields(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    for field in (*primary, *secondary):
        if field not in merged:
            merged.append(field)
    return merged


def _supported_capability_titles() -> str:
    titles = [capability.title for capability in all_capabilities()]
    return "、".join(titles) if titles else "无"


def _is_validation_case_request(text: str) -> bool:
    lower_text = text.lower()
    return (
        re.search(r"\btc[-_\s]?\d+\b", lower_text) is not None
        or "标准算例" in text
        or "benchmark" in lower_text
        or "validation" in lower_text
    )

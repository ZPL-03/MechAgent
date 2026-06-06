"""Designer Agent。"""

from __future__ import annotations

from typing import Optional

from mechagent.config import MechAgentConfig
from mechagent.core.models import ModelParams
from mechagent.core.rules import ensure_parameter_ranges
from mechagent.orchestrator.capabilities import SimulationCapability, get_capability
from mechagent.orchestrator.llm_advisor import AgentLLMAdvisor, AgentLLMTrace
from mechagent.orchestrator.llm_structured import (
    model_params_contract,
    model_params_payload,
    parse_llm_model_params,
)
from mechagent.orchestrator.models import DesignAgentOutput, TaskItem


class DesignerAgent:
    """将任务转换为结构化仿真参数。

    Args:
        无。

    Returns:
        DesignerAgent: Designer 节点实例。

    Raises:
        无。

    Example:
        >>> task = TaskItem(
        ...     task_id="TASK_1",
        ...     case_id="STATIC-STRUCTURAL",
        ...     title="结构静力分析",
        ...     capability_id="structural_static",
        ...     intent=SimulationIntent(
        ...         raw_request="长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，向下1000N",
        ...         capability_id="structural_static",
        ...     ),
        ... )
        >>> DesignerAgent().design(task).geometry.type.value
        'beam'
    """

    def __init__(self, config: Optional[MechAgentConfig] = None) -> None:
        self.advisor = AgentLLMAdvisor(config)

    def design(self, task: TaskItem) -> ModelParams:
        """生成 `ModelParams`。

        Args:
            task: Planner 输出任务。

        Returns:
            ModelParams: 结构化仿真参数。

        Raises:
            ValueError: 当任务类型不受支持或缺少必要参数时抛出。

        Example:
            >>> DesignerAgent().design(task)
            ModelParams(...)
        """

        return self.design_with_trace(task).model_params

    def design_with_trace(self, task: TaskItem) -> DesignAgentOutput:
        """生成仿真参数和 Designer LLM 审计记录。

        Args:
            task: Planner 输出任务。

        Returns:
            DesignAgentOutput: 结构化参数和审计记录。

        Raises:
            ValueError: 当任务类型不受支持或缺少必要参数时抛出。
        """

        if task.capability_id:
            if task.intent is None:
                msg = "DesignerAgent 需要 TaskItem.intent 提供标准化仿真意图。"
                raise ValueError(msg)
            raw_request = task.intent.raw_request
            capability = get_capability(task.capability_id)
            local_params = _try_parse_model_params(capability.parser, raw_request)
            trace = self.advisor.complete(
                "Designer",
                "从自然语言提取几何、材料、载荷、边界、网格和分析参数",
                model_params_payload(raw_request, capability, local_params),
                model_params_contract(capability),
            )
            llm_params, trace = parse_llm_model_params(
                trace,
                raw_request,
                normalizer=capability.model_normalizer,
            )
            params = local_params if local_params is not None else llm_params
            if params is None:
                if task.intent.missing_fields:
                    _raise_incomplete_intent(task, trace)
                params = capability.parser(raw_request)
            ensure_parameter_ranges(params)
            _ensure_declared_model_case(capability, params)
            if capability.execution_validator is not None:
                capability.execution_validator(params)
            return DesignAgentOutput(
                model_params=params,
                designer_llm_trace=trace,
            )

        msg = f"DesignerAgent 不支持任务类型: {task.case_id}"
        raise ValueError(msg)


class DesignerAgentError(ValueError):
    """Designer 阶段错误，保留已产生的 LLM 审计记录。"""

    def __init__(self, message: str, llm_trace: AgentLLMTrace | None = None) -> None:
        super().__init__(message)
        self.llm_trace = llm_trace


def _try_parse_model_params(parser: object, request: str) -> ModelParams | None:
    if not callable(parser):
        return None
    try:
        parsed = parser(request)
    except ValueError:
        return None
    if isinstance(parsed, ModelParams):
        return parsed
    return None


def _ensure_declared_model_case(
    capability: SimulationCapability,
    params: ModelParams,
) -> None:
    if not capability.model_case_ids:
        return
    if params.case_id in capability.model_case_ids:
        return
    supported = "、".join(capability.model_case_ids)
    msg = (
        f"模型编号不在能力声明范围: {params.case_id or '<empty>'}。"
        f"{capability.capability_id} 支持的模型编号: {supported}。"
    )
    raise ValueError(msg)


def _raise_incomplete_intent(
    task: TaskItem,
    llm_trace: AgentLLMTrace | None = None,
) -> None:
    if task.intent is None:
        msg = "DesignerAgent 需要 TaskItem.intent 提供标准化仿真意图。"
        raise DesignerAgentError(msg, llm_trace)
    missing_fields = list(task.intent.missing_fields)
    if "单一几何类型" in missing_fields:
        msg = "仿真请求包含多个几何类型或多个物理任务；请拆分为单个仿真任务。"
        raise DesignerAgentError(msg, llm_trace)
    task_title = task.title or "仿真任务"
    msg = f"{task_title}缺少必要参数: {'、'.join(missing_fields)}。"
    raise DesignerAgentError(msg, llm_trace)

"""LangGraph 全局状态定义。"""

from __future__ import annotations

from typing import TypedDict

from mechagent.core.mesher import MeshResult
from mechagent.core.models import ModelParams
from mechagent.orchestrator.llm_advisor import AgentLLMTrace
from mechagent.orchestrator.models import (
    ErrorRecord,
    PostProcessingSummary,
    SolverRunSummary,
    TaskItem,
    TaskRunRecord,
)


class MechAgentState(TypedDict, total=False):
    """所有 Agent 节点共享的全局状态。

    Args:
        无。

    Returns:
        MechAgentState: TypedDict 类型定义。

    Raises:
        无。

    Example:
        >>> state: MechAgentState = {"session_id": "SESSION_demo", "user_request": "结构静力分析"}
        >>> state["session_id"]
        'SESSION_demo'
    """

    session_id: str
    user_request: str
    plan: list[TaskItem]
    active_tasks: list[TaskItem]
    work_dir: str
    model_params_list: list[ModelParams]
    designer_traces: list[AgentLLMTrace]
    mesh_results: list[MeshResult]
    mesh_traces: list[AgentLLMTrace]
    solver_results: list[SolverRunSummary]
    post_summaries: list[PostProcessingSummary]
    analysis_texts: list[str]
    report: str
    report_path: str
    reporter_trace: AgentLLMTrace
    success: bool
    records: list[TaskRunRecord]
    failed_records: list[TaskRunRecord]
    errors: list[ErrorRecord]

"""Agent 编排图构建接口。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from mechagent.config import MechAgentConfig
from mechagent.core.mesher import MeshResult
from mechagent.core.models import ModelParams
from mechagent.orchestrator.agents import (
    AnalystAgent,
    DesignerAgent,
    MeshAgent,
    PlannerAgent,
    PostProcAgent,
    ReporterAgent,
    SolverAgent,
)
from mechagent.orchestrator.agents.designer import DesignerAgentError
from mechagent.orchestrator.ids import new_run_id
from mechagent.orchestrator.llm_advisor import AgentLLMTrace
from mechagent.orchestrator.models import (
    ErrorRecord,
    PostProcessingSummary,
    SolverRunSummary,
    TaskItem,
    TaskRunRecord,
)
from mechagent.orchestrator.progress import StageName, StageStatus, emit_progress
from mechagent.orchestrator.state import MechAgentState


def build_graph(config: dict[str, Any] | MechAgentConfig) -> Any:
    """构建 LangGraph StateGraph。

    Args:
        config: MechAgent 配置对象或配置字典。

    Returns:
        Any: 编译后的 LangGraph 图对象。

    Raises:
        RuntimeError: 当 langgraph 不可用时抛出。

    Example:
        >>> build_graph({})
        <CompiledStateGraph ...>
    """

    try:
        from langgraph.graph import StateGraph
    except ImportError as exc:
        msg = "langgraph 不可用，无法构建编排图。"
        raise RuntimeError(msg) from exc

    active_config = _coerce_config(config)
    graph = StateGraph(MechAgentState)
    _add_progress_node(graph, "planner", _planner_node, active_config)
    _add_progress_node(graph, "designer", _designer_node, active_config)
    _add_progress_node(graph, "mesh", _mesh_node, active_config)
    _add_progress_node(graph, "solver", _solver_node, active_config)
    _add_progress_node(graph, "postproc", _postproc_node, active_config)
    _add_progress_node(graph, "analyst", _analyst_node, active_config)
    _add_progress_node(graph, "reporter", _reporter_node, active_config)
    graph.set_entry_point("planner")
    graph.add_edge("planner", "designer")
    graph.add_edge("designer", "mesh")
    graph.add_edge("mesh", "solver")
    graph.add_edge("solver", "postproc")
    graph.add_edge("postproc", "analyst")
    graph.add_edge("analyst", "reporter")
    graph.set_finish_point("reporter")
    return graph.compile()


def _coerce_config(config: dict[str, Any] | MechAgentConfig) -> MechAgentConfig:
    if isinstance(config, MechAgentConfig):
        return config
    return MechAgentConfig.model_validate(config)


def _add_progress_node(
    graph: Any,
    stage: StageName,
    node: Callable[[MechAgentState, MechAgentConfig], dict[str, Any]],
    config: MechAgentConfig,
) -> None:
    graph.add_node(stage, lambda state: _with_progress(stage, node, state, config))


def _with_progress(
    stage: StageName,
    node: Callable[[MechAgentState, MechAgentConfig], dict[str, Any]],
    state: MechAgentState,
    config: MechAgentConfig,
) -> dict[str, Any]:
    emit_progress(stage, "running", _stage_message(stage, "running"))
    try:
        result = node(state, config)
    except Exception:
        emit_progress(stage, "failed", _stage_message(stage, "failed"))
        raise
    status: StageStatus = "failed" if _result_has_stage_error(result, stage) else "complete"
    emit_progress(stage, status, _stage_message(stage, status))
    return result


def _result_has_stage_error(result: dict[str, Any], stage: StageName) -> bool:
    for error in result.get("errors", []):
        error_record = _error_record(error)
        if error_record.node == stage:
            return True
    return False


def _stage_message(stage: StageName, status: str) -> str:
    labels = {
        "planner": "任务识别",
        "designer": "参数建模",
        "mesh": "网格生成",
        "solver": "求解执行",
        "postproc": "结果提取",
        "analyst": "工程校核",
        "reporter": "报告输出",
    }
    status_labels = {
        "running": "开始",
        "complete": "完成",
        "failed": "失败",
    }
    return f"{labels[stage]}{status_labels[status]}"


def _planner_node(state: MechAgentState, config: MechAgentConfig) -> dict[str, Any]:
    request = str(state.get("user_request", "")).strip()
    work_dir = Path(state.get("work_dir", "")) if state.get("work_dir") else None
    active_work_dir = work_dir or config.output.output_dir / new_run_id(request)
    active_work_dir.mkdir(parents=True, exist_ok=True)
    try:
        tasks = PlannerAgent(config).plan(request)
    except Exception as exc:
        error = ErrorRecord.from_exception("planner", exc)
        return {
            "plan": [],
            "active_tasks": [],
            "work_dir": str(active_work_dir),
            "errors": [error],
            "failed_records": [_request_failure_record(error)],
        }
    return {
        "plan": tasks,
        "active_tasks": tasks,
        "work_dir": str(active_work_dir),
    }


def _designer_node(state: MechAgentState, config: MechAgentConfig) -> dict[str, Any]:
    active_tasks = _active_tasks(state)
    if not active_tasks:
        return {}
    designer = DesignerAgent(config)
    next_tasks: list[TaskItem] = []
    params: list[ModelParams] = []
    traces: list[AgentLLMTrace] = []
    errors: list[ErrorRecord] = []
    failed_records: list[TaskRunRecord] = []
    for task_value in active_tasks:
        task = _task_item(task_value)
        try:
            output = designer.design_with_trace(task)
            next_tasks.append(task)
            params.append(output.model_params)
            traces.append(output.designer_llm_trace)
        except Exception as exc:
            error = ErrorRecord.from_exception("designer", exc, task)
            errors.append(error)
            designer_trace = exc.llm_trace if isinstance(exc, DesignerAgentError) else None
            failed_records.append(
                TaskRunRecord(
                    task=task,
                    designer_llm_trace=designer_trace,
                    error=error,
                )
            )
    result: dict[str, Any] = {
        "active_tasks": next_tasks,
        "model_params_list": params,
        "designer_traces": traces,
    }
    _append_failures(result, state, errors, failed_records)
    return result


def _mesh_node(state: MechAgentState, config: MechAgentConfig) -> dict[str, Any]:
    active_tasks = _active_tasks(state)
    if not active_tasks:
        return {}
    try:
        (model_params_values,) = _required_stage_values(
            state,
            active_tasks,
            "mesh",
            "model_params_list",
        )
    except ValueError as exc:
        return _state_contract_failure(state, "mesh", active_tasks, exc)
    next_tasks: list[TaskItem] = []
    next_params: list[ModelParams] = []
    next_designer_traces: list[AgentLLMTrace] = []
    results: list[MeshResult] = []
    traces: list[AgentLLMTrace] = []
    errors: list[ErrorRecord] = []
    failed_records: list[TaskRunRecord] = []
    for index, (task_value, params_value) in enumerate(zip(active_tasks, model_params_values)):
        task = _task_item(task_value)
        params = _model_params(params_value)
        designer_trace = _designer_trace(state, index)
        mesh_agent = MeshAgent(config, _task_work_dir(state, task))
        try:
            output = mesh_agent.generate_with_trace(params, task)
        except Exception as exc:
            error = ErrorRecord.from_exception("mesh", exc, task)
            errors.append(error)
            failed_records.append(
                TaskRunRecord(
                    task=task,
                    model_params=params,
                    designer_llm_trace=designer_trace,
                    error=error,
                )
            )
            continue
        if not output.mesh_result.success:
            msg = output.mesh_result.error_message or "网格生成失败，求解阶段无法继续。"
            error = ErrorRecord.from_exception("mesh", ValueError(msg), task)
            errors.append(error)
            failed_records.append(
                TaskRunRecord(
                    task=task,
                    model_params=params,
                    mesh_result=output.mesh_result,
                    designer_llm_trace=designer_trace,
                    mesh_llm_trace=output.mesh_llm_trace,
                    error=error,
                )
            )
            continue
        next_tasks.append(task)
        next_params.append(params)
        if designer_trace is not None:
            next_designer_traces.append(designer_trace)
        results.append(output.mesh_result)
        traces.append(output.mesh_llm_trace)
    result = {
        "active_tasks": next_tasks,
        "model_params_list": next_params,
        "designer_traces": next_designer_traces,
        "mesh_results": results,
        "mesh_traces": traces,
    }
    _append_failures(result, state, errors, failed_records)
    return result


def _solver_node(state: MechAgentState, config: MechAgentConfig) -> dict[str, Any]:
    active_tasks = _active_tasks(state)
    if not active_tasks:
        return {}
    try:
        model_params_values, mesh_values = _required_stage_values(
            state,
            active_tasks,
            "solver",
            "model_params_list",
            "mesh_results",
        )
    except ValueError as exc:
        return _state_contract_failure(state, "solver", active_tasks, exc)
    next_tasks: list[TaskItem] = []
    next_params: list[ModelParams] = []
    next_mesh_results: list[MeshResult] = []
    next_designer_traces: list[AgentLLMTrace] = []
    next_mesh_traces: list[AgentLLMTrace] = []
    results: list[SolverRunSummary] = []
    errors: list[ErrorRecord] = []
    failed_records: list[TaskRunRecord] = []
    for index, (task, params, mesh) in enumerate(
        zip(
            active_tasks,
            model_params_values,
            mesh_values,
        )
    ):
        task_item = _task_item(task)
        model_params = _model_params(params)
        mesh_result = _mesh_result(mesh)
        designer_trace = _designer_trace(state, index)
        mesh_trace = _mesh_trace(state, index)
        solver_agent = SolverAgent(config, _task_work_dir(state, task_item))
        try:
            results.append(solver_agent.solve(task_item, model_params, mesh_result))
        except Exception as exc:
            error = ErrorRecord.from_exception("solver", exc, task_item)
            errors.append(error)
            solver_result = solver_agent.failure_summary(task_item, model_params, mesh_result)
            failed_records.append(
                TaskRunRecord(
                    task=task_item,
                    model_params=model_params,
                    mesh_result=mesh_result,
                    solver_result=solver_result,
                    designer_llm_trace=designer_trace,
                    mesh_llm_trace=mesh_trace,
                    error=error,
                )
            )
            continue
        next_tasks.append(task_item)
        next_params.append(model_params)
        next_mesh_results.append(mesh_result)
        if designer_trace is not None:
            next_designer_traces.append(designer_trace)
        if mesh_trace is not None:
            next_mesh_traces.append(mesh_trace)
    result = {
        "active_tasks": next_tasks,
        "model_params_list": next_params,
        "mesh_results": next_mesh_results,
        "designer_traces": next_designer_traces,
        "mesh_traces": next_mesh_traces,
        "solver_results": results,
    }
    _append_failures(result, state, errors, failed_records)
    return result


def _postproc_node(state: MechAgentState, config: MechAgentConfig) -> dict[str, Any]:
    active_tasks = _active_tasks(state)
    if not active_tasks:
        return {}
    try:
        model_params_values, mesh_values, solver_values = _required_stage_values(
            state,
            active_tasks,
            "postproc",
            "model_params_list",
            "mesh_results",
            "solver_results",
        )
    except ValueError as exc:
        return _state_contract_failure(state, "postproc", active_tasks, exc)
    next_tasks: list[TaskItem] = []
    next_params: list[ModelParams] = []
    next_mesh_results: list[MeshResult] = []
    next_solver_results: list[SolverRunSummary] = []
    next_designer_traces: list[AgentLLMTrace] = []
    next_mesh_traces: list[AgentLLMTrace] = []
    summaries: list[PostProcessingSummary] = []
    errors: list[ErrorRecord] = []
    failed_records: list[TaskRunRecord] = []
    for index, (task, params, mesh, result) in enumerate(
        zip(
            active_tasks,
            model_params_values,
            mesh_values,
            solver_values,
        )
    ):
        task_item = _task_item(task)
        model_params = _model_params(params)
        mesh_result = _mesh_result(mesh)
        solver_result = _solver_summary(result)
        designer_trace = _designer_trace(state, index)
        mesh_trace = _mesh_trace(state, index)
        post_agent = PostProcAgent(_task_work_dir(state, task_item), config)
        try:
            summaries.append(post_agent.summarize(solver_result))
        except Exception as exc:
            error = ErrorRecord.from_exception("postproc", exc, task_item)
            errors.append(error)
            failed_records.append(
                TaskRunRecord(
                    task=task_item,
                    model_params=model_params,
                    mesh_result=mesh_result,
                    solver_result=solver_result,
                    designer_llm_trace=designer_trace,
                    mesh_llm_trace=mesh_trace,
                    error=error,
                )
            )
            continue
        next_tasks.append(task_item)
        next_params.append(model_params)
        next_mesh_results.append(mesh_result)
        next_solver_results.append(solver_result)
        if designer_trace is not None:
            next_designer_traces.append(designer_trace)
        if mesh_trace is not None:
            next_mesh_traces.append(mesh_trace)
    result_update = {
        "active_tasks": next_tasks,
        "model_params_list": next_params,
        "mesh_results": next_mesh_results,
        "solver_results": next_solver_results,
        "designer_traces": next_designer_traces,
        "mesh_traces": next_mesh_traces,
        "post_summaries": summaries,
    }
    _append_failures(result_update, state, errors, failed_records)
    return result_update


def _analyst_node(state: MechAgentState, config: MechAgentConfig) -> dict[str, Any]:
    active_tasks = _active_tasks(state)
    if not active_tasks:
        return {}
    try:
        (
            model_params_values,
            mesh_values,
            solver_values,
            post_summary_values,
        ) = _required_stage_values(
            state,
            active_tasks,
            "analyst",
            "model_params_list",
            "mesh_results",
            "solver_results",
            "post_summaries",
        )
    except ValueError as exc:
        return _state_contract_failure(state, "analyst", active_tasks, exc)
    analyst = AnalystAgent(config)
    next_tasks: list[TaskItem] = []
    next_params: list[ModelParams] = []
    next_mesh_results: list[MeshResult] = []
    next_solver_results: list[SolverRunSummary] = []
    next_designer_traces: list[AgentLLMTrace] = []
    next_mesh_traces: list[AgentLLMTrace] = []
    texts: list[str] = []
    post_summaries: list[PostProcessingSummary] = []
    errors: list[ErrorRecord] = []
    failed_records: list[TaskRunRecord] = []
    for index, (task, params, mesh, solver, summary) in enumerate(
        zip(
            active_tasks,
            model_params_values,
            mesh_values,
            solver_values,
            post_summary_values,
        )
    ):
        task_item = _task_item(task)
        model_params = _model_params(params)
        mesh_result = _mesh_result(mesh)
        solver_result = _solver_summary(solver)
        post_summary = _post_summary(summary)
        designer_trace = _designer_trace(state, index)
        mesh_trace = _mesh_trace(state, index)
        try:
            texts.append(analyst.analyze(task_item, post_summary))
            post_summaries.append(post_summary)
        except Exception as exc:
            error = ErrorRecord.from_exception("analyst", exc, task_item)
            record = TaskRunRecord(
                task=task_item,
                model_params=model_params,
                mesh_result=mesh_result,
                solver_result=solver_result,
                post_summary=post_summary,
                designer_llm_trace=designer_trace,
                mesh_llm_trace=mesh_trace,
                error=error,
            )
            errors.append(error)
            failed_records.append(record)
            continue
        next_tasks.append(task_item)
        next_params.append(model_params)
        next_mesh_results.append(mesh_result)
        next_solver_results.append(solver_result)
        if designer_trace is not None:
            next_designer_traces.append(designer_trace)
        if mesh_trace is not None:
            next_mesh_traces.append(mesh_trace)
    result = {
        "active_tasks": next_tasks,
        "model_params_list": next_params,
        "mesh_results": next_mesh_results,
        "solver_results": next_solver_results,
        "designer_traces": next_designer_traces,
        "mesh_traces": next_mesh_traces,
        "analysis_texts": texts,
        "post_summaries": post_summaries,
    }
    _append_failures(result, state, errors, failed_records)
    return result


def _reporter_node(state: MechAgentState, config: MechAgentConfig) -> dict[str, Any]:
    records, errors = _report_records_and_errors(state)
    report, reporter_trace = ReporterAgent(config).render_with_trace(records)
    work_dir = Path(state["work_dir"])
    report_path = work_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    success = (
        not errors and bool(records) and all(record.solver_result.success for record in records)
    )
    return {
        "success": success,
        "report": report,
        "report_path": str(report_path),
        "reporter_trace": reporter_trace,
        "records": records,
        "errors": errors,
    }


def _records_from_state(state: MechAgentState) -> list[TaskRunRecord]:
    active_tasks = _active_tasks(state)
    if not active_tasks:
        return []
    (
        model_params_values,
        mesh_values,
        solver_values,
        post_summary_values,
        analysis_text_values,
    ) = _required_stage_values(
        state,
        active_tasks,
        "reporter",
        "model_params_list",
        "mesh_results",
        "solver_results",
        "post_summaries",
        "analysis_texts",
    )
    records = []
    for index, (task, params, mesh, solver, summary, analysis_text) in enumerate(
        zip(
            active_tasks,
            model_params_values,
            mesh_values,
            solver_values,
            post_summary_values,
            analysis_text_values,
        )
    ):
        records.append(
            TaskRunRecord(
                task=_task_item(task),
                model_params=_model_params(params),
                mesh_result=_mesh_result(mesh),
                solver_result=_solver_summary(solver),
                post_summary=_post_summary(summary),
                analysis_text=analysis_text,
                designer_llm_trace=_designer_trace(state, index),
                mesh_llm_trace=_mesh_trace(state, index),
            )
        )
    return records


def _report_records_and_errors(
    state: MechAgentState,
) -> tuple[list[TaskRunRecord], list[ErrorRecord]]:
    errors = _state_errors(state)
    try:
        success_records = _records_from_state(state)
        failed_records = _state_failed_records(state)
    except ValueError as exc:
        active_tasks = _active_tasks(state)
        contract_errors = [
            ErrorRecord.from_exception("reporter", exc, task) for task in active_tasks
        ]
        contract_failed_records = [
            TaskRunRecord(task=task, error=error)
            for task, error in zip(active_tasks, contract_errors)
        ]
        records = _ordered_report_records(
            state,
            [],
            [*_state_failed_records(state), *contract_failed_records],
        )
        return records, [*errors, *contract_errors]

    return _ordered_report_records(state, success_records, failed_records), errors


def _ordered_report_records(
    state: MechAgentState,
    success_records: list[TaskRunRecord],
    failed_records: list[TaskRunRecord],
) -> list[TaskRunRecord]:
    if not state.get("plan"):
        return failed_records or success_records

    by_task_id = {record.task.task_id: record for record in [*failed_records, *success_records]}
    records = [
        by_task_id[task.task_id]
        for task in (_task_item(task_value) for task_value in state["plan"])
        if task.task_id in by_task_id
    ]
    return records or failed_records or success_records


def _task_item(value: TaskItem | dict[str, Any]) -> TaskItem:
    return value if isinstance(value, TaskItem) else TaskItem.model_validate(value)


def _model_params(value: ModelParams | dict[str, Any]) -> ModelParams:
    return value if isinstance(value, ModelParams) else ModelParams.model_validate(value)


def _mesh_result(value: MeshResult | dict[str, Any]) -> MeshResult:
    return value if isinstance(value, MeshResult) else MeshResult.model_validate(value)


def _solver_summary(value: SolverRunSummary | dict[str, Any]) -> SolverRunSummary:
    return value if isinstance(value, SolverRunSummary) else SolverRunSummary.model_validate(value)


def _post_summary(value: PostProcessingSummary | dict[str, Any]) -> PostProcessingSummary:
    return (
        value
        if isinstance(value, PostProcessingSummary)
        else PostProcessingSummary.model_validate(value)
    )


def _task_record(value: TaskRunRecord | dict[str, Any]) -> TaskRunRecord:
    return value if isinstance(value, TaskRunRecord) else TaskRunRecord.model_validate(value)


def _error_record(value: ErrorRecord | dict[str, Any]) -> ErrorRecord:
    return value if isinstance(value, ErrorRecord) else ErrorRecord.model_validate(value)


def _designer_trace(state: MechAgentState, index: int) -> AgentLLMTrace | None:
    traces = state.get("designer_traces", [])
    if index >= len(traces):
        return None
    return _llm_trace(traces[index])


def _mesh_trace(state: MechAgentState, index: int) -> AgentLLMTrace | None:
    traces = state.get("mesh_traces", [])
    if index >= len(traces):
        return None
    return _llm_trace(traces[index])


def _llm_trace(value: AgentLLMTrace | dict[str, Any]) -> AgentLLMTrace:
    return value if isinstance(value, AgentLLMTrace) else AgentLLMTrace.model_validate(value)


def _task_work_dir(state: MechAgentState, task: TaskItem) -> Path:
    path = Path(state["work_dir"]) / task.task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _active_tasks(state: MechAgentState) -> list[TaskItem]:
    return [_task_item(task) for task in state.get("active_tasks", [])]


def _required_stage_values(
    state: MechAgentState,
    active_tasks: list[TaskItem],
    node: str,
    *keys: str,
) -> tuple[list[Any], ...]:
    expected_count = len(active_tasks)
    values: list[list[Any]] = []
    mismatches: list[str] = []
    for key in keys:
        state_value = state.get(key, [])
        raw_values = state_value if isinstance(state_value, list) else []
        values.append(raw_values)
        if not isinstance(state_value, list):
            mismatches.append(f"{key}=非列表")
        elif len(raw_values) != expected_count:
            mismatches.append(f"{key}={len(raw_values)}")
    if mismatches:
        task_ids = "、".join(task.task_id for task in active_tasks)
        details = "、".join(mismatches)
        msg = (
            f"{node} 节点状态不一致: active_tasks={expected_count}，{details}。"
            f"受影响任务: {task_ids}。"
        )
        raise ValueError(msg)
    return tuple(values)


def _state_contract_failure(
    state: MechAgentState,
    node: str,
    active_tasks: list[TaskItem],
    exc: Exception,
) -> dict[str, Any]:
    errors = [ErrorRecord.from_exception(node, exc, task) for task in active_tasks]
    failed_records = [
        TaskRunRecord(task=task, error=error) for task, error in zip(active_tasks, errors)
    ]
    result: dict[str, Any] = {"active_tasks": []}
    _append_failures(result, state, errors, failed_records)
    return result


def _append_failures(
    result: dict[str, Any],
    state: MechAgentState,
    errors: list[ErrorRecord],
    failed_records: list[TaskRunRecord],
) -> None:
    if errors:
        result["errors"] = [*_state_errors(state), *errors]
    if failed_records:
        result["failed_records"] = [*_state_failed_records(state), *failed_records]


def _state_errors(state: MechAgentState) -> list[ErrorRecord]:
    return [_error_record(error) for error in state.get("errors", [])]


def _state_failed_records(state: MechAgentState) -> list[TaskRunRecord]:
    return [_task_record(record) for record in state.get("failed_records", [])]


def _request_failure_record(error: ErrorRecord) -> TaskRunRecord:
    return TaskRunRecord(
        task=TaskItem(task_id="REQUEST", case_id="REQUEST", title="请求解析"),
        error=error,
    )

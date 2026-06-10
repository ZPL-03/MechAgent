"""自然语言到求解报告的工作流测试。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from mechagent import MechAgent
from mechagent.config import (
    CalculiXSettings,
    LLMSettings,
    MechAgentConfig,
    MesherSettings,
    OrchestratorSettings,
    OutputSettings,
    SolverSettings,
)
from mechagent.core import (
    AbstractMesher,
    AbstractSolver,
    MeshResult,
    SolverResult,
    register_mesher,
    register_solver,
    unregister_mesher,
    unregister_solver,
)
from mechagent.core.models import ModelParams
from mechagent.core.validation import tc01_model_params
from mechagent.orchestrator import SequentialWorkflow
from mechagent.orchestrator.agents import DesignerAgent
from mechagent.orchestrator.capabilities import (
    SimulationCapability,
    register_capability,
    unregister_capability,
)
from mechagent.orchestrator.evaluation import (
    ResultEvaluationContext,
    evaluate_structural_static_result,
)
from mechagent.orchestrator.graph import (
    _analyst_node,
    _mesh_node,
    _postproc_node,
    _reporter_node,
    _solver_node,
    build_graph,
)
from mechagent.orchestrator.intent import SimulationIntent
from mechagent.orchestrator.models import SolverRunSummary, TaskItem
from mechagent.orchestrator.progress import ProgressEvent, progress_sink
from mechagent.orchestrator.state import MechAgentState

_STATIC_BEAM_REQUEST = (
    "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
)
_STATIC_SOLID_REQUEST = "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
_PERFORATED_PLATE_REQUEST = (
    "求解长400mm、宽240mm、厚6mm、中心圆孔孔径60mm、材料钢的开孔薄板，"
    "四边简支，承受0.004MPa向下均布压力的静力响应"
)
_COMPOUND_STATIC_REQUEST = (
    "求解梁长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，"
    "沿梁竖向向下1kN/m均布线载荷的静力响应；"
    "矩形板300mmx200mmx5mm，材料铝，四边简支，承受0.01MPa均布压力静力分析"
)
_PARTIAL_FAILURE_STATIC_REQUEST = (
    "求解梁长1000mm、截面20mmx40mm的悬臂梁，一端固支，端部向下1000N静力分析；"
    "矩形板300mmx200mmx5mm，材料铝，四边简支，承受0.01MPa均布压力静力分析"
)


def _configured_solver_settings() -> SolverSettings:
    solver_path = MechAgent.from_config("config/mechagent.yaml").config.solver.calculix.path
    return SolverSettings(calculix=CalculiXSettings(path=solver_path))


@pytest.mark.real_solver
def test_sequential_workflow_runs_natural_language_static_beam(tmp_path: Path) -> None:
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(mode="sequential"),
        solver=_configured_solver_settings(),
        output=OutputSettings(output_dir=tmp_path),
    )
    workflow = SequentialWorkflow(config)
    events: list[ProgressEvent] = []

    with progress_sink(events.append):
        result = workflow.run(_STATIC_BEAM_REQUEST)

    assert result.success is True
    event_pairs = [(event["stage"], event["status"]) for event in events]
    assert ("planner", "running") in event_pairs
    assert ("planner", "complete") in event_pairs
    assert ("designer", "running") in event_pairs
    assert ("mesh", "running") in event_pairs
    assert ("solver", "running") in event_pairs
    assert ("postproc", "running") in event_pairs
    assert ("analyst", "running") in event_pairs
    assert ("reporter", "complete") in event_pairs
    assert len(result.tasks) == 1
    assert "MechAgent 仿真报告" in result.report
    record = result.tasks[0]
    assert record.task.case_id == "STATIC-STRUCTURAL"
    assert record.task.intent is not None
    assert record.task.intent.capability_id == "structural_static"
    assert record.task.planner_llm_trace is not None
    assert record.task.planner_llm_trace.agent == "Planner"
    assert record.designer_llm_trace is not None
    assert record.designer_llm_trace.agent == "Designer"
    assert record.model_params is not None
    assert "designer_llm_trace" not in record.model_params.metadata
    assert record.model_params.case_id == "STATIC-BEAM"
    assert record.model_params.load_case == "cantilever_uniform_line_load"
    assert record.model_params.loads[0].type.value == "line_load"
    assert record.mesh_result is not None
    assert record.mesh_llm_trace is not None
    assert record.mesh_llm_trace.agent == "MeshAgent"
    assert "mesh_llm_trace" not in record.mesh_result.metadata
    assert record.mesh_result.mesh_file is not None
    assert record.solver_result.mesh_file == record.mesh_result.mesh_file
    assert record.solver_result.predicted == record.solver_result["tip_deflection_mm"]
    assert "阶段产物" in result.report
    assert "执行链路摘要" in result.report


@pytest.mark.real_solver
def test_workflow_preserves_solver_result_when_llm_advisory_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_runtime_error(prompt: str, config: object) -> str:
        _ = (prompt, config)
        raise RuntimeError("LLM 远端拒绝请求")

    monkeypatch.setattr(
        "mechagent.orchestrator.llm_advisor.completion",
        raise_runtime_error,
    )
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(mode="sequential", use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
        solver=_configured_solver_settings(),
        output=OutputSettings(output_dir=tmp_path),
    )
    workflow = SequentialWorkflow(config)

    result = workflow.run(_STATIC_BEAM_REQUEST)

    assert result.success is True
    record = result.tasks[0]
    assert record.solver_result.passed is True
    assert record.task.planner_llm_trace is not None
    assert record.task.planner_llm_trace.used is True
    assert record.task.planner_llm_trace.error == "LLM 远端拒绝请求"
    assert record.designer_llm_trace is not None
    assert record.designer_llm_trace.error == "LLM 远端拒绝请求"
    assert record.mesh_llm_trace is not None
    assert record.mesh_llm_trace.error == "LLM 远端拒绝请求"
    assert record.solver_result.solver_llm_trace is not None
    assert record.solver_result.solver_llm_trace.error == "LLM 远端拒绝请求"
    assert record.post_summary.postproc_llm_trace is not None
    assert record.post_summary.postproc_llm_trace.error == "LLM 远端拒绝请求"
    assert record.post_summary.analyst_llm_trace is not None
    assert record.post_summary.analyst_llm_trace.error == "LLM 远端拒绝请求"
    assert result.reporter_llm_trace is not None
    assert result.reporter_llm_trace.error == "LLM 远端拒绝请求"
    assert "LLM 远端拒绝请求" in result.report


def test_sequential_workflow_report_includes_error_diagnostics(tmp_path: Path) -> None:
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(mode="sequential"),
        output=OutputSettings(output_dir=tmp_path),
    )
    workflow = SequentialWorkflow(config)

    result = workflow.run("求解长1000mm、截面20mmx40mm的悬臂梁，一端固支，向下1000N静力分析")

    assert result.success is False
    assert result.errors
    assert result.tasks[0].error is not None
    task_error = result.summary()["tasks"][0]["error"]
    assert task_error["code"] == "missing_required_inputs"
    assert task_error["missing_fields"] == ["材料"]
    assert "错误诊断" in result.report
    assert "missing_required_inputs" in result.report
    assert "材料" in result.report


@pytest.mark.real_solver
def test_sequential_workflow_runs_compound_static_request_as_independent_tasks(
    tmp_path: Path,
) -> None:
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(mode="sequential"),
        solver=_configured_solver_settings(),
        output=OutputSettings(output_dir=tmp_path),
    )
    workflow = SequentialWorkflow(config)

    result = workflow.run(_COMPOUND_STATIC_REQUEST)

    assert result.success is True
    assert len(result.tasks) == 2
    assert [record.task.task_id for record in result.tasks] == ["TASK_1", "TASK_2"]
    assert [
        record.model_params.case_id if record.model_params else None for record in result.tasks
    ] == [
        "STATIC-BEAM",
        "STATIC-PLATE",
    ]
    mesh_files = [record.mesh_result.mesh_file for record in result.tasks if record.mesh_result]
    assert len(mesh_files) == 2
    assert {path.parent.name for path in mesh_files if path is not None} == {"TASK_1", "TASK_2"}
    assert all(record.solver_result.passed for record in result.tasks)
    assert "STATIC-BEAM" in result.report
    assert "STATIC-PLATE" in result.report


@pytest.mark.real_solver
def test_sequential_workflow_runs_natural_language_perforated_plate(
    tmp_path: Path,
) -> None:
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(mode="sequential"),
        solver=_configured_solver_settings(),
        output=OutputSettings(output_dir=tmp_path),
    )
    workflow = SequentialWorkflow(config)

    result = workflow.run(_PERFORATED_PLATE_REQUEST)

    assert result.success is True
    record = result.tasks[0]
    assert record.model_params is not None
    assert record.model_params.case_id == "STATIC-PERFORATED-PLATE"
    assert record.model_params.geometry.dimensions["hole_radius"] == pytest.approx(30.0)
    assert record.mesh_result is not None
    assert record.mesh_result.metadata["source"] == "gmsh_perforated_plate"
    assert record.solver_result.success is True
    assert record.solver_result.model_case_id == "STATIC-PERFORATED-PLATE"
    assert record.solver_result.quantity == "max_displacement"
    assert record.solver_result.predicted is not None
    assert record.solver_result.predicted > 0.0
    assert record.solver_result.verification_status == "unverified"
    assert "STATIC-PERFORATED-PLATE" in result.report


@pytest.mark.real_solver
def test_sequential_workflow_preserves_successful_tasks_when_compound_request_partly_fails(
    tmp_path: Path,
) -> None:
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(mode="sequential"),
        solver=_configured_solver_settings(),
        output=OutputSettings(output_dir=tmp_path),
    )
    workflow = SequentialWorkflow(config)

    result = workflow.run(_PARTIAL_FAILURE_STATIC_REQUEST)

    assert result.success is False
    assert len(result.tasks) == 2
    failed_record = result.tasks[0]
    successful_record = result.tasks[1]
    assert failed_record.error is not None
    assert failed_record.error.node == "designer"
    assert failed_record.error.code == "missing_required_inputs"
    assert failed_record.error.missing_fields == ["材料"]
    assert successful_record.error is None
    assert successful_record.model_params is not None
    assert successful_record.model_params.case_id == "STATIC-PLATE"
    assert successful_record.solver_result.success is True
    assert successful_record.solver_result.passed is True
    assert "missing_required_inputs" in result.report
    assert "STATIC-PLATE" in result.report


def test_sequential_workflow_success_does_not_require_reference_check(tmp_path: Path) -> None:
    _register_unverified_workflow_plugins()
    try:
        workflow = SequentialWorkflow(_unverified_workflow_config(tmp_path))

        result = workflow.run("unit unverified task")

        assert result.success is True
        assert result.tasks[0].solver_result.success is True
        assert result.tasks[0].solver_result.passed is False
        assert result.tasks[0].solver_result.verification_status == "unverified"
        assert "未验证" in result.report
    finally:
        _unregister_unverified_workflow_plugins()


def test_sequential_workflow_reports_low_quality_mesh_as_mesh_failure(tmp_path: Path) -> None:
    _register_mesh_failure_workflow_plugins()
    try:
        workflow = SequentialWorkflow(_mesh_failure_workflow_config(tmp_path))

        result = workflow.run("unit mesh quality task")

        assert result.success is False
        assert result.errors[0].node == "mesh"
        assert result.errors[0].code == "mesh_failed"
        assert result.tasks[0].mesh_result is not None
        assert result.tasks[0].mesh_result.success is False
        assert result.tasks[0].error is not None
        assert result.tasks[0].error.code == "mesh_failed"
        assert "mesh_failed" in result.report
    finally:
        _unregister_mesh_failure_workflow_plugins()


def test_designer_requires_structured_intent() -> None:
    task = TaskItem(
        task_id="TASK_1",
        case_id="STATIC-STRUCTURAL",
        capability_id="structural_static",
        title="结构静力分析",
    )

    with pytest.raises(ValueError, match="TaskItem.intent"):
        DesignerAgent().design(task)


def test_designer_rejects_incomplete_intent_after_llm_structured_extraction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def fake_completion(prompt: str, _config: object) -> str:
        prompts.append(prompt)
        return json.dumps({"assessment": "缺少参数"}, ensure_ascii=False)

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )
    task = TaskItem(
        task_id="TASK_1",
        case_id="STATIC-STRUCTURAL",
        capability_id="structural_static",
        title="结构静力分析",
        intent=SimulationIntent(
            raw_request="求解一个悬臂梁一端固支，一端垂直受压50KN/m的受力情况",
            capability_id="structural_static",
            missing_fields=["材料", "载荷方向"],
        ),
    )

    with pytest.raises(ValueError, match="缺少必要参数: 材料、载荷方向"):
        DesignerAgent(config).design_with_trace(task)
    assert any("\nAgent: Designer\n" in prompt for prompt in prompts)


def test_designer_uses_llm_structured_model_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_completion(prompt: str, _config: object) -> str:
        assert "ModelParams" in prompt
        return json.dumps(
            {
                "geometry": {
                    "type": "beam",
                    "length": 1000,
                    "section": {"profile": "rectangular", "b": 20, "h": 40},
                },
                "material": {
                    "elastic_modulus": 210000,
                    "poissons_ratio": 0.3,
                    "density": 7.85e-9,
                },
                "loads": [
                    {
                        "type": "force",
                        "magnitude": 1000,
                        "direction": [0, -1, 0],
                        "position": [1000, 0, 0],
                    }
                ],
                "bcs": [
                    {
                        "type": "fixed",
                        "position": [0, 0, 0],
                    }
                ],
                "mesh": {"element_type": "B31", "seed_size": 10},
                "analysis": {"type": "static", "solver": "external"},
                "case_id": "",
                "load_case": "",
                "metadata": {"source": "llm"},
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )
    task = TaskItem(
        task_id="TASK_1",
        case_id="STATIC-STRUCTURAL",
        capability_id="structural_static",
        title="结构静力分析",
        intent=SimulationIntent(
            raw_request="请对这根梁完成结构静力求解",
            capability_id="structural_static",
        ),
    )

    output = DesignerAgent(config).design_with_trace(task)

    assert output.designer_llm_trace.used is True
    assert output.designer_llm_trace.error is None
    assert output.model_params.case_id == "STATIC-BEAM"
    assert output.model_params.load_case == "cantilever_tip_force"
    assert output.model_params.metadata["source"] == "llm_structured"


def test_designer_prefers_validated_local_params_over_llm_structured_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_completion(prompt: str, _config: object) -> str:
        assert "validated_local_draft" in prompt
        return json.dumps(
            {
                "geometry": {
                    "type": "beam",
                    "dimensions": {"length": 2000, "width": 30, "height": 60},
                },
                "material": {"E": 70000, "nu": 0.33, "rho": 2.7e-9},
                "loads": [
                    {
                        "type": "force",
                        "magnitude": 5000,
                        "region": "tip",
                        "direction": [0, -1, 0],
                    }
                ],
                "bcs": [
                    {
                        "type": "fixed",
                        "region": "root",
                        "dofs": ["ux", "uy", "uz", "rx", "ry", "rz"],
                        "values": [0, 0, 0, 0, 0, 0],
                    }
                ],
                "mesh": {"element_type": "B31", "seed_size": 20},
                "analysis": {"type": "static", "nlgeom": False},
                "case_id": "STATIC-BEAM",
                "load_case": "cantilever_tip_force",
                "metadata": {"source": "llm"},
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )
    request = "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，向下1000N静力分析"
    task = TaskItem(
        task_id="TASK_1",
        case_id="STATIC-STRUCTURAL",
        capability_id="structural_static",
        title="结构静力分析",
        intent=SimulationIntent(
            raw_request=request,
            capability_id="structural_static",
        ),
    )

    output = DesignerAgent(config).design_with_trace(task)

    assert output.designer_llm_trace.used is True
    assert output.model_params.geometry.dimensions == {
        "length": 1000.0,
        "width": 20.0,
        "height": 40.0,
    }
    assert output.model_params.material.E == 210000.0
    assert output.model_params.loads[0].magnitude == 1000.0
    assert output.model_params.mesh.seed_size == 10.0
    assert output.model_params.metadata["source"] == "natural_language"


@pytest.mark.real_solver
def test_sdk_run_uses_langgraph_by_default(tmp_path: Path) -> None:
    agent = MechAgent(
        MechAgentConfig(
            solver=_configured_solver_settings(),
            output=OutputSettings(output_dir=tmp_path),
        )
    )

    result = agent.run(_STATIC_BEAM_REQUEST)

    assert result.summary["success"] is True
    assert len(result.summary["tasks"]) == 1
    assert result.summary["tasks"][0]["capability_id"] == "structural_static"
    assert result.summary["tasks"][0]["analysis_type"] == "static"
    assert result.summary["tasks"][0]["intent"]["capability_id"] == "structural_static"
    assert result.summary["tasks"][0]["planner_llm_trace"]["agent"] == "Planner"
    assert result.summary["tasks"][0]["designer_llm_trace"]["agent"] == "Designer"
    assert result.summary["tasks"][0]["model_params"]["case_id"] == "STATIC-BEAM"
    assert result.summary["tasks"][0]["model_params"]["loads"][0]["type"] == "line_load"
    assert result.summary["tasks"][0]["mesh_llm_trace"]["agent"] == "MeshAgent"
    assert result.summary["tasks"][0]["mesh_result"]["success"] is True
    assert (
        result.summary["tasks"][0]["post_summary"]["analyst_llm_trace"]["agent"] == "AnalystAgent"
    )
    assert result.summary["reporter_llm_trace"]["agent"] == "ReporterAgent"
    assert result.output_dir == Path(result.summary["work_dir"])
    assert "STATIC-BEAM" in result.report
    assert "执行链路摘要" in result.report
    assert "| TASK_1 | 任务识别 | 未启用 | ok |" in result.report


@pytest.mark.real_solver
def test_langgraph_workflow_runs_natural_language_static_beam(tmp_path: Path) -> None:
    graph = build_graph(
        MechAgentConfig(
            solver=_configured_solver_settings(),
            output=OutputSettings(output_dir=tmp_path),
        )
    )

    state = graph.invoke({"user_request": _STATIC_BEAM_REQUEST})

    assert state["success"] is True
    assert "MechAgent 仿真报告" in state["report"]
    assert state["plan"][0].case_id == "STATIC-STRUCTURAL"
    assert state["plan"][0].intent is not None
    assert state["plan"][0].intent.capability_id == "structural_static"
    assert state["plan"][0].planner_llm_trace is not None
    assert state["model_params_list"][0].case_id == "STATIC-BEAM"
    assert state["designer_traces"][0].agent == "Designer"
    assert state["model_params_list"][0].load_case == "cantilever_uniform_line_load"
    assert state["mesh_traces"][0].agent == "MeshAgent"
    assert state["solver_results"][0].passed is True
    assert state["post_summaries"][0].analyst_llm_trace is not None
    assert state["post_summaries"][0].analyst_llm_trace.agent == "AnalystAgent"
    assert state["reporter_trace"].agent == "ReporterAgent"
    assert "执行链路摘要" in state["report"]


@pytest.mark.real_solver
def test_langgraph_workflow_runs_natural_language_static_solid(tmp_path: Path) -> None:
    graph = build_graph(
        MechAgentConfig(
            solver=_configured_solver_settings(),
            output=OutputSettings(output_dir=tmp_path),
        )
    )

    state = graph.invoke({"user_request": _STATIC_SOLID_REQUEST})

    assert state["success"] is True
    assert state["model_params_list"][0].case_id == "STATIC-SOLID"
    assert state["model_params_list"][0].load_case == "fixed_solid_axial_pressure"
    assert state["model_params_list"][0].mesh.element_type == "C3D8R"
    assert state["solver_results"][0].model_case_id == "STATIC-SOLID"
    assert state["solver_results"][0].quantity == "axial_displacement"
    assert state["solver_results"][0].passed is True
    assert "STATIC-SOLID" in state["analysis_texts"][0]


@pytest.mark.real_solver
def test_langgraph_workflow_runs_compound_static_request_as_independent_tasks(
    tmp_path: Path,
) -> None:
    graph = build_graph(
        MechAgentConfig(
            solver=_configured_solver_settings(),
            output=OutputSettings(output_dir=tmp_path),
        )
    )

    state = graph.invoke({"user_request": _COMPOUND_STATIC_REQUEST})

    assert state["success"] is True
    assert [task.task_id for task in state["plan"]] == ["TASK_1", "TASK_2"]
    assert [params.case_id for params in state["model_params_list"]] == [
        "STATIC-BEAM",
        "STATIC-PLATE",
    ]
    mesh_files = [mesh.mesh_file for mesh in state["mesh_results"]]
    assert len(mesh_files) == 2
    assert {path.parent.name for path in mesh_files if path is not None} == {"TASK_1", "TASK_2"}
    assert all(result.passed for result in state["solver_results"])
    assert "STATIC-BEAM" in state["report"]
    assert "STATIC-PLATE" in state["report"]


@pytest.mark.real_solver
def test_langgraph_workflow_preserves_successful_tasks_when_compound_request_partly_fails(
    tmp_path: Path,
) -> None:
    graph = build_graph(
        MechAgentConfig(
            solver=_configured_solver_settings(),
            output=OutputSettings(output_dir=tmp_path),
        )
    )

    state = graph.invoke({"user_request": _PARTIAL_FAILURE_STATIC_REQUEST})

    assert state["success"] is False
    assert len(state["errors"]) == 1
    assert state["errors"][0].node == "designer"
    assert state["errors"][0].code == "missing_required_inputs"
    assert len(state["records"]) == 2
    failed_record = state["records"][0]
    successful_record = state["records"][1]
    assert failed_record.task.task_id == "TASK_1"
    assert failed_record.error is not None
    assert failed_record.error.missing_fields == ["材料"]
    assert successful_record.task.task_id == "TASK_2"
    assert successful_record.error is None
    assert successful_record.model_params is not None
    assert successful_record.model_params.case_id == "STATIC-PLATE"
    assert successful_record.solver_result.success is True
    assert successful_record.solver_result.passed is True
    assert "missing_required_inputs" in state["report"]
    assert "STATIC-PLATE" in state["report"]


def test_langgraph_workflow_report_includes_error_diagnostics(tmp_path: Path) -> None:
    graph = build_graph(MechAgentConfig(output=OutputSettings(output_dir=tmp_path)))

    state = graph.invoke({"user_request": "求解一个悬臂梁一端固支，一端垂直受压50KN/m的受力情况"})

    assert state["success"] is False
    assert state["errors"][0].node == "designer"
    assert state["errors"][0].code == "missing_required_inputs"
    assert "梁长" in state["errors"][0].missing_fields
    assert state["records"][0].error is not None
    assert "错误诊断" in state["report"]
    assert "missing_required_inputs" in state["report"]
    assert "梁长" in state["report"]


def test_langgraph_workflow_success_does_not_require_reference_check(tmp_path: Path) -> None:
    _register_unverified_workflow_plugins()
    try:
        graph = build_graph(_unverified_workflow_config(tmp_path))

        state = graph.invoke({"user_request": "unit unverified task"})

        assert state["success"] is True
        assert state["solver_results"][0].success is True
        assert state["solver_results"][0].passed is False
        assert state["solver_results"][0].verification_status == "unverified"
        assert "未验证" in state["report"]
    finally:
        _unregister_unverified_workflow_plugins()


def test_langgraph_workflow_reports_low_quality_mesh_as_mesh_failure(tmp_path: Path) -> None:
    _register_mesh_failure_workflow_plugins()
    try:
        graph = build_graph(_mesh_failure_workflow_config(tmp_path))

        state = graph.invoke({"user_request": "unit mesh quality task"})

        assert state["success"] is False
        assert state["errors"][0].node == "mesh"
        assert state["errors"][0].code == "mesh_failed"
        assert state["records"][0].mesh_result is not None
        assert state["records"][0].mesh_result.success is False
        assert state["records"][0].error is not None
        assert state["records"][0].error.code == "mesh_failed"
        assert "mesh_failed" in state["report"]
    finally:
        _unregister_mesh_failure_workflow_plugins()


def test_sequential_workflow_includes_failed_solver_summary_metadata(tmp_path: Path) -> None:
    _register_solver_failure_workflow_plugins()
    try:
        workflow = SequentialWorkflow(_solver_failure_workflow_config(tmp_path))

        result = workflow.run("unit solver failure task")

        record = result.tasks[0]
        assert result.success is False
        assert result.errors[0].node == "solver"
        assert result.errors[0].code == "solver_failed"
        assert record.error is not None
        assert record.error.code == "solver_failed"
        assert record.mesh_result is not None
        assert record.solver_result.success is False
        assert record.solver_result.verification_status == "failed"
        assert record.solver_result.solver == "unit-failing-solver"
        assert record.solver_result.model_case_id == "STATIC-BEAM"
        assert record.solver_result.task_title == "求解器失败静力分析"
        assert record.solver_result.mesh_file == record.mesh_result.mesh_file
        assert "unit solver process failed" in result.report
    finally:
        _unregister_solver_failure_workflow_plugins()


def test_langgraph_workflow_includes_failed_solver_summary_metadata(tmp_path: Path) -> None:
    _register_solver_failure_workflow_plugins()
    try:
        graph = build_graph(_solver_failure_workflow_config(tmp_path))

        state = graph.invoke({"user_request": "unit solver failure task"})

        record = state["records"][0]
        assert state["success"] is False
        assert state["errors"][0].node == "solver"
        assert state["errors"][0].code == "solver_failed"
        assert record.error is not None
        assert record.error.code == "solver_failed"
        assert record.mesh_result is not None
        assert record.solver_result.success is False
        assert record.solver_result.verification_status == "failed"
        assert record.solver_result.solver == "unit-failing-solver"
        assert record.solver_result.model_case_id == "STATIC-BEAM"
        assert record.solver_result.task_title == "求解器失败静力分析"
        assert record.solver_result.mesh_file == record.mesh_result.mesh_file
        assert "unit solver process failed" in state["report"]
    finally:
        _unregister_solver_failure_workflow_plugins()


@pytest.mark.parametrize(
    ("node_name", "node_func", "state", "expected_code"),
    [
        (
            "mesh",
            _mesh_node,
            {"model_params_list": []},
            "mesh_failed",
        ),
        (
            "solver",
            _solver_node,
            {
                "model_params_list": [tc01_model_params()],
                "mesh_results": [],
            },
            "solver_failed",
        ),
        (
            "postproc",
            _postproc_node,
            {
                "model_params_list": [tc01_model_params()],
                "mesh_results": [MeshResult(success=True)],
                "solver_results": [],
            },
            "postproc_failed",
        ),
        (
            "analyst",
            _analyst_node,
            {
                "model_params_list": [tc01_model_params()],
                "mesh_results": [MeshResult(success=True)],
                "solver_results": [SolverRunSummary(success=True)],
                "post_summaries": [],
            },
            "analysis_failed",
        ),
    ],
)
def test_langgraph_nodes_report_state_contract_mismatch(
    node_name: str,
    node_func: Callable[[dict[str, Any], MechAgentConfig], dict[str, Any]],
    state: dict[str, Any],
    expected_code: str,
) -> None:
    task = TaskItem(
        task_id="TASK_1",
        case_id="UNIT-CONTRACT",
        capability_id="unit",
        title="状态契约测试",
    )
    state.update({"active_tasks": [task]})

    result = node_func(state, MechAgentConfig())

    assert result["active_tasks"] == []
    assert result["errors"][0].node == node_name
    assert result["errors"][0].code == expected_code
    assert "状态不一致" in result["errors"][0].message
    assert result["failed_records"][0].task.task_id == "TASK_1"
    assert result["failed_records"][0].error.code == expected_code


def test_langgraph_reporter_reports_final_state_contract_mismatch(tmp_path: Path) -> None:
    task = TaskItem(
        task_id="TASK_1",
        case_id="UNIT-CONTRACT",
        capability_id="unit",
        title="报告状态契约测试",
    )
    state: MechAgentState = {
        "plan": [task],
        "active_tasks": [task],
        "work_dir": str(tmp_path),
        "model_params_list": [tc01_model_params()],
        "mesh_results": [MeshResult(success=True)],
        "solver_results": [SolverRunSummary(success=True)],
    }

    result = _reporter_node(state, MechAgentConfig())

    assert result["success"] is False
    assert result["errors"][0].node == "reporter"
    assert result["errors"][0].code == "report_failed"
    assert "状态不一致" in result["errors"][0].message
    assert result["records"][0].task.task_id == "TASK_1"
    assert result["records"][0].error.code == "report_failed"
    assert "report_failed" in result["report"]
    assert Path(result["report_path"]).exists()


def test_sdk_reports_missing_physical_inputs_as_failed_result(tmp_path: Path) -> None:
    agent = MechAgent(MechAgentConfig(output=OutputSettings(output_dir=tmp_path)))

    result = agent.run("求解一个悬臂梁一端固支，一端垂直受压50KN/m的受力情况")

    assert result.summary["success"] is False
    assert result.summary["errors"][0]["node"] == "designer"
    assert result.summary["errors"][0]["code"] == "missing_required_inputs"
    assert "梁长" in result.summary["errors"][0]["missing_fields"]
    assert result.summary["tasks"][0]["error"] is not None
    assert "错误诊断" in result.report


def test_sdk_llm_agents_preserve_missing_input_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def fake_completion(prompt: str, _config: object) -> str:
        prompts.append(prompt)
        return json.dumps(
            {
                "assessment": "缺少工程输入",
                "missing_fields": ["梁长", "矩形截面尺寸", "材料", "载荷方向"],
                "risks": ["缺参请求不能进入参数建模"],
                "recommended_action": "补充缺失输入",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
        output=OutputSettings(output_dir=tmp_path),
    )
    agent = MechAgent(config)

    result = agent.run("求解一个悬臂梁一端固支，一端垂直受压50KN/m的受力情况")

    assert result.summary["success"] is False
    assert result.summary["errors"][0]["node"] == "designer"
    assert result.summary["errors"][0]["code"] == "missing_required_inputs"
    assert result.summary["tasks"][0]["model_params"] is None
    designer_trace = result.summary["tasks"][0]["designer_llm_trace"]
    assert designer_trace["used"] is True
    assert designer_trace["error"] is not None
    assert "载荷方向" in result.summary["errors"][0]["missing_fields"]
    assert prompts
    assert any("\nAgent: Designer\n" in prompt for prompt in prompts)


def test_sdk_reports_unsplit_compound_geometry_request_as_ambiguous_result(
    tmp_path: Path,
) -> None:
    agent = MechAgent(MechAgentConfig(output=OutputSettings(output_dir=tmp_path)))

    result = agent.run("请分析一个梁板组合结构的静力响应，材料钢，长度1000mm，载荷1000N。")

    assert result.summary["success"] is False
    assert result.summary["errors"][0]["node"] == "designer"
    assert result.summary["errors"][0]["code"] == "ambiguous_request"
    assert result.summary["errors"][0]["missing_fields"] == ["单一几何类型"]
    assert result.summary["tasks"][0]["error"] is not None
    assert "ambiguous_request" in result.report


def test_sdk_reports_embedded_validation_case_request_as_failed_result(
    tmp_path: Path,
) -> None:
    agent = MechAgent(MechAgentConfig(output=OutputSettings(output_dir=tmp_path)))

    result = agent.run("请执行标准算例 TC-01")

    assert result.summary["success"] is False
    assert result.summary["errors"][0]["node"] == "planner"
    assert result.summary["errors"][0]["code"] == "validation_case_request"
    assert "独立测试入口" in result.report

    compact_result = agent.run("请执行 TC01")

    assert compact_result.summary["success"] is False
    assert compact_result.summary["errors"][0]["node"] == "planner"
    assert compact_result.summary["errors"][0]["code"] == "validation_case_request"
    assert "独立测试入口" in compact_result.report


def test_sdk_reports_unknown_request_as_failed_result(tmp_path: Path) -> None:
    agent = MechAgent(MechAgentConfig(output=OutputSettings(output_dir=tmp_path)))

    result = agent.run("分析一个完全未知的任务")

    assert result.summary["success"] is False
    assert result.summary["errors"][0]["node"] == "planner"
    assert result.summary["errors"][0]["code"] == "unsupported_request"
    assert "无法识别" in result.report


def test_sdk_reports_empty_request_as_failed_result(tmp_path: Path) -> None:
    agent = MechAgent(MechAgentConfig(output=OutputSettings(output_dir=tmp_path)))

    result = agent.run("   ")

    assert result.summary["success"] is False
    assert result.summary["errors"][0]["node"] == "planner"
    assert result.summary["errors"][0]["code"] == "empty_request"
    assert result.summary["tasks"][0]["error"] is not None
    assert "request 不能为空" in result.report


def _unverified_workflow_config(tmp_path: Path) -> MechAgentConfig:
    return MechAgentConfig(
        solver=SolverSettings(default="unit-unverified-solver"),
        mesher=MesherSettings(default="unit-unverified-mesher"),
        output=OutputSettings(output_dir=tmp_path),
    )


def _mesh_failure_workflow_config(tmp_path: Path) -> MechAgentConfig:
    return MechAgentConfig(
        mesher=MesherSettings(min_quality=0.5),
        output=OutputSettings(output_dir=tmp_path),
    )


def _solver_failure_workflow_config(tmp_path: Path) -> MechAgentConfig:
    return MechAgentConfig(output=OutputSettings(output_dir=tmp_path))


def _register_unverified_workflow_plugins() -> None:
    register_solver("unit-unverified-solver", _UnverifiedDummySolver)
    register_mesher("unit-unverified-mesher", _UnverifiedDummyMesher)
    register_capability(
        SimulationCapability(
            capability_id="unit_unverified_static",
            task_case_id="UNIT-UNVERIFIED-STATIC",
            title="无参考静力分析",
            analysis_type="static",
            physics_domain="structural",
            parser=_unverified_parser,
            matcher=lambda request: "unit unverified" in request.lower(),
            geometry_detector=lambda _request: "beam",
            evaluator=_unverified_evaluator,
            missing_field_detector=lambda _request: [],
        )
    )


def _register_mesh_failure_workflow_plugins() -> None:
    register_mesher("unit-low-quality-workflow-mesher", _LowQualityWorkflowMesher)
    register_capability(
        SimulationCapability(
            capability_id="unit_mesh_quality_static",
            task_case_id="UNIT-MESH-QUALITY-STATIC",
            title="低质量网格静力分析",
            analysis_type="static",
            physics_domain="structural",
            parser=_unverified_parser,
            matcher=lambda request: "unit mesh quality" in request.lower(),
            geometry_detector=lambda _request: "beam",
            evaluator=_unverified_evaluator,
            missing_field_detector=lambda _request: [],
            mesher_name="unit-low-quality-workflow-mesher",
        )
    )


def _register_solver_failure_workflow_plugins() -> None:
    register_solver("unit-failing-solver", _FailingDummySolver)
    register_mesher("unit-solver-failure-mesher", _UnverifiedDummyMesher)
    register_capability(
        SimulationCapability(
            capability_id="unit_solver_failure_static",
            task_case_id="UNIT-SOLVER-FAILURE-STATIC",
            title="求解器失败静力分析",
            analysis_type="static",
            physics_domain="structural",
            parser=_solver_failure_parser,
            matcher=lambda request: "unit solver failure" in request.lower(),
            geometry_detector=lambda _request: "beam",
            evaluator=_unverified_evaluator,
            missing_field_detector=lambda _request: [],
            mesher_name="unit-solver-failure-mesher",
            solver_name="unit-failing-solver",
        )
    )


def _unregister_unverified_workflow_plugins() -> None:
    unregister_capability("unit_unverified_static")
    unregister_mesher("unit-unverified-mesher")
    unregister_solver("unit-unverified-solver")


def _unregister_mesh_failure_workflow_plugins() -> None:
    unregister_capability("unit_mesh_quality_static")
    unregister_mesher("unit-low-quality-workflow-mesher")


def _unregister_solver_failure_workflow_plugins() -> None:
    unregister_capability("unit_solver_failure_static")
    unregister_mesher("unit-solver-failure-mesher")
    unregister_solver("unit-failing-solver")


class _UnverifiedDummyMesher(AbstractMesher):
    def generate(self, _model_params: ModelParams) -> MeshResult:
        mesh_file = self.config.work_dir / "unit_unverified_mesh.inp"
        mesh_file.write_text("*NODE\n", encoding="utf-8")
        return MeshResult(
            success=True,
            mesh_file=mesh_file,
            quality={"min_jacobian": 1.0},
            metadata={"mesher": "unit"},
        )


class _LowQualityWorkflowMesher(AbstractMesher):
    def generate(self, _model_params: ModelParams) -> MeshResult:
        mesh_file = self.config.work_dir / "unit_low_quality_mesh.inp"
        mesh_file.write_text("*NODE\n", encoding="utf-8")
        return MeshResult(
            success=True,
            mesh_file=mesh_file,
            quality={"min_jacobian": 0.2},
            metadata={"mesher": "unit-low-quality"},
        )


class _UnverifiedDummySolver(AbstractSolver):
    def generate_input(self, _model_params: ModelParams) -> Path:
        input_file = self.config.work_dir / "unit_unverified.inp"
        input_file.write_text("*HEADING\n", encoding="utf-8")
        return input_file

    def solve(self, input_file: Path) -> SolverResult:
        return SolverResult(
            success=True,
            wall_time=0.0,
            output_files=[input_file],
        )

    def extract_results(self, result: SolverResult) -> dict[str, object]:
        return {
            "success": True,
            "output_files": [str(path) for path in result.output_files],
            "tip_deflection_mm": 12.0,
        }


class _FailingDummySolver(AbstractSolver):
    def generate_input(self, _model_params: ModelParams) -> Path:
        input_file = self.config.work_dir / "unit_failing.inp"
        input_file.write_text("*HEADING\n", encoding="utf-8")
        return input_file

    def solve(self, input_file: Path) -> SolverResult:
        return SolverResult(
            success=False,
            wall_time=0.0,
            output_files=[input_file],
            error_message="unit solver process failed",
        )

    def extract_results(self, _result: SolverResult) -> dict[str, object]:
        pytest.fail("failed solver result must stop before result extraction")


def _unverified_parser(_request: str) -> ModelParams:
    return tc01_model_params().model_copy(
        update={
            "case_id": "STATIC-BEAM-UNVERIFIED",
            "load_case": "custom_static_beam",
        }
    )


def _solver_failure_parser(_request: str) -> ModelParams:
    return tc01_model_params().model_copy(
        update={
            "case_id": "STATIC-BEAM",
            "load_case": "cantilever_tip_force",
        }
    )


def _unverified_evaluator(context: ResultEvaluationContext) -> dict[str, object]:
    return evaluate_structural_static_result(context)

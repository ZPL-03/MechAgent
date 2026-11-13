"""SolverAgent 评价逻辑测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mechagent.config import MechAgentConfig, SolverSettings
from mechagent.core import (
    AbstractSolver,
    MeshProvenance,
    MeshQualityGate,
    MeshResult,
    SolverResult,
    register_solver,
    unregister_solver,
)
from mechagent.core.models import (
    AnalysisSpec,
    AnalysisType,
    BCSpec,
    BCType,
    ElementType,
    GeometrySpec,
    GeometryType,
    LoadSpec,
    LoadType,
    MaterialSpec,
    MeshSpec,
    ModelParams,
)
from mechagent.core.validation import cantilever_tip_deflection, tc01_model_params
from mechagent.evidence import sha256
from mechagent.orchestrator.agents.solver import SolverAgent
from mechagent.orchestrator.capabilities import (
    SimulationCapability,
    register_capability,
    unregister_capability,
)
from mechagent.orchestrator.evaluation import (
    ResultEvaluationContext,
    evaluate_structural_static_result,
)
from mechagent.orchestrator.models import TaskItem


def test_solver_evaluation_rejects_unverified_geometry_type() -> None:
    params = ModelParams(
        geometry=GeometrySpec(
            type=GeometryType.SHELL,
            dimensions={"length": 100.0, "width": 100.0, "thickness": 1.0},
        ),
        material=MaterialSpec(E=210000.0, nu=0.3, rho=7.85e-9),
        loads=[
            LoadSpec(
                type=LoadType.PRESSURE,
                magnitude=1.0,
                region="top_surface",
                direction=(0.0, 0.0, -1.0),
            )
        ],
        bcs=[
            BCSpec(
                type=BCType.SIMPLE_SUPPORT,
                region="all_edges",
                dofs=["uz"],
                values=[0.0],
            )
        ],
        mesh=MeshSpec(element_type=ElementType.S4, seed_size=10.0),
        analysis=AnalysisSpec(type=AnalysisType.STATIC),
    )
    with pytest.raises(ValueError, match="shell"):
        evaluate_structural_static_result(
            ResultEvaluationContext(
                model_params=params,
                solver_result={"success": True, "max_displacement_mm": 1.0},
                solver_name="calculix",
                task_case_id="STATIC-STRUCTURAL",
                task_title="结构静力分析",
            )
        )


def test_solver_evaluation_marks_unreferenced_result_as_unverified() -> None:
    params = tc01_model_params().model_copy(update={"load_case": "custom_static_beam"})

    result = evaluate_structural_static_result(
        ResultEvaluationContext(
            model_params=params,
            solver_result={"success": True, "tip_deflection_mm": 12.0},
            solver_name="calculix",
            task_case_id="STATIC-STRUCTURAL",
            task_title="结构静力分析",
        )
    )

    assert result["success"] is True
    assert result["passed"] is False
    assert result["verification_status"] == "unverified"
    assert "reference" not in result
    assert result["equilibrium"]["status"] == "unverified"


def test_solver_evaluation_records_reaction_balance() -> None:
    params = tc01_model_params()
    result = evaluate_structural_static_result(
        ResultEvaluationContext(
            model_params=params,
            solver_result={
                "success": True,
                "tip_deflection_mm": _tc01_tip_reference(params),
                "nodes": {"1": [0.0, 0.0, 0.0], "2": [1000.0, 0.0, 0.0]},
                "fields": {"reaction_force": {"values": {"1": [0.0, 1000.0, 0.0]}}},
            },
            solver_name="calculix",
            task_case_id="TC-01",
            task_title="悬臂梁端部集中力",
        )
    )

    assert result["equilibrium"]["status"] == "passed"
    assert result["equilibrium"]["applied_resultant"] == [0.0, -1000.0, 0.0]


def test_solver_evaluation_marks_failed_reference_result_as_failed() -> None:
    params = tc01_model_params()
    reference = _tc01_tip_reference(params)

    result = evaluate_structural_static_result(
        ResultEvaluationContext(
            model_params=params,
            solver_result={"success": False, "tip_deflection_mm": reference},
            solver_name="calculix",
            task_case_id="STATIC-STRUCTURAL",
            task_title="结构静力分析",
        )
    )

    assert result["success"] is False
    assert result["passed"] is False
    assert result["verification_status"] == "failed"
    assert result["relative_error"] == pytest.approx(0.0)


def test_solver_evaluation_marks_failed_unreferenced_result_as_failed() -> None:
    params = tc01_model_params().model_copy(update={"load_case": "custom_static_beam"})

    result = evaluate_structural_static_result(
        ResultEvaluationContext(
            model_params=params,
            solver_result={"success": "failed", "tip_deflection_mm": 12.0},
            solver_name="calculix",
            task_case_id="STATIC-STRUCTURAL",
            task_title="结构静力分析",
        )
    )

    assert result["success"] == "failed"
    assert result["passed"] is False
    assert result["verification_status"] == "failed"
    assert "reference" not in result


def test_solver_agent_uses_capability_evaluator(tmp_path: Path) -> None:
    register_solver("unit-eval-solver", _EvalDummySolver)
    register_capability(
        SimulationCapability(
            capability_id="unit_eval_capability",
            task_case_id="UNIT-EVAL",
            title="单元评价能力",
            analysis_type="static",
            physics_domain="structural",
            parser=_unit_eval_parser,
            matcher=lambda _request: False,
            geometry_detector=lambda _request: "beam",
            evaluator=_unit_eval_evaluator,
        )
    )
    try:
        config = MechAgentConfig(solver=SolverSettings(default="unit-eval-solver"))
        task = TaskItem(
            task_id="TASK_1",
            case_id="UNIT-EVAL",
            capability_id="unit_eval_capability",
            title="单元评价能力",
        )

        summary = SolverAgent(config, tmp_path).solve(task, tc01_model_params())

        assert summary.model_case_id == "EVALUATED-BY-CAPABILITY"
        assert summary.quantity == "custom_quantity"
        assert summary.predicted == 42.0
        assert summary.passed
        assert summary.solver == "unit-eval-solver"
    finally:
        unregister_capability("unit_eval_capability")
        unregister_solver("unit-eval-solver")


def test_solver_agent_uses_capability_solver_over_global_default(tmp_path: Path) -> None:
    register_solver("unit-capability-solver", _EvalDummySolver)
    register_capability(
        SimulationCapability(
            capability_id="unit_solver_tool_capability",
            task_case_id="UNIT-SOLVER-TOOL",
            title="单元求解工具能力",
            analysis_type="static",
            physics_domain="structural",
            parser=_unit_eval_parser,
            matcher=lambda _request: False,
            geometry_detector=lambda _request: "beam",
            evaluator=_unit_eval_evaluator,
            solver_name="unit-capability-solver",
        )
    )
    try:
        task = TaskItem(
            task_id="TASK_1",
            case_id="UNIT-SOLVER-TOOL",
            capability_id="unit_solver_tool_capability",
            title="单元求解工具能力",
        )

        summary = SolverAgent(MechAgentConfig(), tmp_path).solve(task, tc01_model_params())

        assert summary.solver == "unit-capability-solver"
        assert summary.model_case_id == "EVALUATED-BY-CAPABILITY"
    finally:
        unregister_capability("unit_solver_tool_capability")
        unregister_solver("unit-capability-solver")


def test_solver_agent_carries_mesh_provenance_into_summary(tmp_path: Path) -> None:
    register_solver("unit-provenance-solver", _EvalDummySolver)
    register_capability(
        SimulationCapability(
            capability_id="unit_provenance_capability",
            task_case_id="UNIT-PROVENANCE",
            title="网格来源能力",
            analysis_type="static",
            physics_domain="structural",
            parser=_unit_eval_parser,
            matcher=lambda _request: False,
            geometry_detector=lambda _request: "beam",
            evaluator=_unit_eval_evaluator,
            solver_name="unit-provenance-solver",
        )
    )
    mesh_file = tmp_path / "mesh.inp"
    mesh_file.write_text("*NODE\n1, 0, 0, 0\n", encoding="utf-8")
    digest = sha256(mesh_file)
    provenance = MeshProvenance(
        case_id="TC-01",
        geometry_type="beam",
        mesher="unit-provenance-mesher",
        seed_size_mm=10.0,
        element_type="B31",
        mesh_sha256=digest,
        quality_metrics={"min_jacobian": 1.0},
        quality_gate=MeshQualityGate(
            threshold=0.3,
            lower_bound_metrics=["min_jacobian"],
            status="passed",
        ),
    )
    try:
        summary = SolverAgent(MechAgentConfig(), tmp_path / "solver").solve(
            TaskItem(
                task_id="TASK_1",
                case_id="UNIT-PROVENANCE",
                capability_id="unit_provenance_capability",
                title="网格来源能力",
            ),
            tc01_model_params(),
            MeshResult(
                success=True,
                mesh_file=mesh_file,
                metadata={"mesh_sha256": digest},
                provenance=provenance,
            ),
        )
    finally:
        unregister_capability("unit_provenance_capability")
        unregister_solver("unit-provenance-solver")

    assert summary.get("mesh_provenance") == provenance.model_dump(mode="json")


def test_solver_agent_revalidates_mesh_file_hash(tmp_path: Path) -> None:
    register_solver("unit-integrity-solver", _EvalDummySolver)
    register_capability(
        SimulationCapability(
            capability_id="unit_mesh_integrity_capability",
            task_case_id="UNIT-MESH-INTEGRITY",
            title="网格完整性能力",
            analysis_type="static",
            physics_domain="structural",
            parser=_unit_eval_parser,
            matcher=lambda _request: False,
            geometry_detector=lambda _request: "beam",
            evaluator=_unit_eval_evaluator,
            solver_name="unit-integrity-solver",
        )
    )
    mesh_file = tmp_path / "mesh.inp"
    mesh_file.write_text("*NODE\n1, 0, 0, 0\n", encoding="utf-8")
    mesh_sha256 = sha256(mesh_file)
    mesh_file.write_text("*NODE\n1, 1, 0, 0\n", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="SHA-256"):
            SolverAgent(MechAgentConfig(), tmp_path / "solver").solve(
                TaskItem(
                    task_id="TASK_1",
                    case_id="UNIT-MESH-INTEGRITY",
                    capability_id="unit_mesh_integrity_capability",
                    title="网格完整性能力",
                ),
                tc01_model_params(),
                MeshResult(
                    success=True,
                    mesh_file=mesh_file,
                    metadata={"mesh_sha256": mesh_sha256},
                ),
            )
    finally:
        unregister_capability("unit_mesh_integrity_capability")
        unregister_solver("unit-integrity-solver")


class _EvalDummySolver(AbstractSolver):
    def generate_input(self, _model_params: ModelParams) -> Path:
        input_file = self.config.work_dir / "unit_eval.inp"
        input_file.write_text("*HEADING\n", encoding="utf-8")
        return input_file

    def solve(self, _input_file: Path) -> SolverResult:
        return SolverResult(success=True, wall_time=0.0)

    def extract_results(self, _result: SolverResult) -> dict[str, Any]:
        return {"success": True}


def _unit_eval_parser(_request: str) -> ModelParams:
    return tc01_model_params()


def _tc01_tip_reference(params: ModelParams) -> float:
    dimensions = params.geometry.dimensions
    return cantilever_tip_deflection(
        abs(params.loads[0].magnitude),
        dimensions["length"],
        params.material.E,
        dimensions["width"],
        dimensions["height"],
    )


def _unit_eval_evaluator(context: ResultEvaluationContext) -> dict[str, Any]:
    return {
        **context.solver_result,
        "model_case_id": "EVALUATED-BY-CAPABILITY",
        "predicted": 42.0,
        "passed": True,
        "quantity": "custom_quantity",
        "unit": "unit",
        "solver": context.solver_name,
        "task_title": context.task_title,
    }

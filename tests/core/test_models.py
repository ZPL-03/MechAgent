"""核心 Pydantic 模型测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from mechagent.core.mesher import MeshConfig
from mechagent.core.models import (
    BCSpec,
    BCType,
    CompositeSpec,
    ElementType,
    GeometrySpec,
    GeometryType,
    LoadSpec,
    LoadType,
    MaterialSpec,
    MeshSpec,
    ModelParams,
)
from mechagent.core.solver import SolverResult
from mechagent.core.validation import tc01_model_params
from mechagent.orchestrator.llm_advisor import AgentLLMTrace
from mechagent.orchestrator.models import (
    ErrorRecord,
    PostProcessingSummary,
    SolverRunSummary,
    TaskItem,
    TaskRunRecord,
    WorkflowResult,
)


def test_tc01_model_params_is_valid() -> None:
    params = tc01_model_params()

    assert isinstance(params, ModelParams)
    assert params.geometry.type.value == "beam"
    assert params.material.E == 210000.0


def test_geometry_dimensions_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        GeometrySpec(type=GeometryType.BEAM, dimensions={"length": -1.0})


def test_core_numeric_specs_reject_non_finite_values() -> None:
    with pytest.raises(ValidationError, match="非有限尺寸"):
        GeometrySpec(type=GeometryType.BEAM, dimensions={"length": float("inf")})

    with pytest.raises(ValidationError, match="非有限数值"):
        MaterialSpec(E=float("inf"), nu=0.3, rho=1.0e-9)

    with pytest.raises(ValidationError, match="非有限角度"):
        CompositeSpec(layup=[float("nan")], ply_thickness=0.1)

    with pytest.raises(ValidationError, match="ply_thickness"):
        CompositeSpec(layup=[0.0], ply_thickness=float("inf"))

    with pytest.raises(ValidationError, match="magnitude"):
        LoadSpec(
            type=LoadType.FORCE, magnitude=float("inf"), region="tip", direction=(0.0, -1.0, 0.0)
        )

    with pytest.raises(ValidationError, match="direction"):
        LoadSpec(
            type=LoadType.FORCE, magnitude=1.0, region="tip", direction=(0.0, float("inf"), 0.0)
        )

    with pytest.raises(ValidationError, match="bcs.values"):
        BCSpec(type=BCType.FIXED, region="root", dofs=["ux"], values=[float("inf")])

    with pytest.raises(ValidationError, match="mesh.seed_size"):
        MeshSpec(element_type=ElementType.B31, seed_size=float("inf"))

    with pytest.raises(ValidationError, match="有限数值"):
        MeshConfig(seed_size=float("inf"))

    with pytest.raises(ValidationError, match="wall_time"):
        SolverResult(success=True, wall_time=float("inf"))


def test_line_load_type_is_valid() -> None:
    load = LoadSpec(type=LoadType.LINE_LOAD, magnitude=1.0, region="span", direction=(0, -1, 0))

    assert load.type is LoadType.LINE_LOAD


def test_material_spec_accepts_stable_negative_poisson_ratio() -> None:
    material = MaterialSpec(E=1000.0, nu=-0.2, rho=1.0e-9)

    assert material.nu == -0.2


def test_material_spec_rejects_unstable_poisson_ratio() -> None:
    with pytest.raises(ValidationError):
        MaterialSpec(E=1000.0, nu=-1.0, rho=1.0e-9)


def test_load_direction_must_be_nonzero() -> None:
    with pytest.raises(ValidationError, match="零向量"):
        LoadSpec(type=LoadType.FORCE, magnitude=1.0, region="tip", direction=(0.0, 0.0, 0.0))


def test_load_magnitude_must_be_nonzero() -> None:
    with pytest.raises(ValidationError, match="不能为 0"):
        LoadSpec(type=LoadType.FORCE, magnitude=0.0, region="tip", direction=(0.0, -1.0, 0.0))


def test_boundary_condition_dofs_must_not_be_blank() -> None:
    with pytest.raises(ValidationError, match="空白自由度"):
        BCSpec(type=BCType.FIXED, region="root", dofs=[" "], values=[0.0])


def test_model_params_requires_loads_and_boundary_conditions() -> None:
    params = tc01_model_params()

    with pytest.raises(ValidationError):
        ModelParams.model_validate(params.model_copy(update={"loads": []}).model_dump())

    with pytest.raises(ValidationError):
        ModelParams.model_validate(params.model_copy(update={"bcs": []}).model_dump())


def test_solver_run_summary_keeps_structured_and_extended_fields() -> None:
    trace = AgentLLMTrace(agent="SolverAgent", used=False)
    summary = SolverRunSummary.from_mapping(
        {
            "success": True,
            "passed": True,
            "model_case_id": "STATIC-BEAM",
            "quantity": "tip_deflection",
            "unit": "mm",
            "predicted": 1.2,
            "reference": 1.0,
            "relative_error": 0.2,
            "tolerance": 0.3,
            "tip_deflection_mm": 1.2,
            "output_files": ["run.frd"],
            "mesh_file": "beam_mesh.inp",
            "mesh_metadata": {"element_count": 100},
            "solver_llm_trace": trace.model_dump(mode="json"),
        }
    )

    assert summary.passed is True
    assert summary.verification_status == "passed"
    assert summary.mesh_file is not None
    assert summary.mesh_file.name == "beam_mesh.inp"
    assert summary["tip_deflection_mm"] == 1.2
    assert summary.to_mapping()["solver_llm_trace"]["agent"] == "SolverAgent"


def test_solver_run_summary_infers_predicted_from_quantity_field() -> None:
    summary = SolverRunSummary.from_mapping(
        {
            "success": True,
            "model_case_id": "UNIT-CUSTOM",
            "quantity": "custom_metric",
            "custom_metric": 42.0,
            "unit": "mm",
        }
    )

    assert summary.predicted == 42.0
    assert summary.verification_status == "unverified"


def test_solver_run_summary_parses_finite_numeric_string_result_fields() -> None:
    summary = SolverRunSummary.from_mapping(
        {
            "success": True,
            "model_case_id": "UNIT-CUSTOM",
            "quantity": "custom_metric",
            "custom_metric": "42.5",
            "unit": "mm",
            "reference": "40.0",
            "relative_error": "0.0625",
            "tolerance": "0.1",
            "passed": True,
        }
    )

    assert summary.predicted == 42.5
    assert summary.reference == 40.0
    assert summary.relative_error == 0.0625
    assert summary.tolerance == 0.1
    assert summary.verification_status == "passed"


def test_solver_run_summary_ignores_invalid_and_non_finite_numeric_strings() -> None:
    summary = SolverRunSummary.from_mapping(
        {
            "success": True,
            "model_case_id": "UNIT-CUSTOM",
            "quantity": "custom_metric",
            "custom_metric": "nan",
            "reference": "inf",
            "relative_error": "",
            "tolerance": "not-a-number",
            "passed": True,
        }
    )

    assert summary.predicted is None
    assert summary.reference is None
    assert summary.relative_error is None
    assert summary.tolerance is None
    assert summary.verification_status == "unverified"


def test_solver_run_summary_parses_string_boolean_result_fields() -> None:
    summary = SolverRunSummary.from_mapping(
        {
            "success": "true",
            "passed": "passed",
            "reference": "40.0",
            "relative_error": "0.0625",
            "tolerance": "0.1",
        }
    )

    assert summary.success is True
    assert summary.passed is True
    assert summary.verification_status == "passed"


def test_solver_run_summary_does_not_treat_false_text_as_true() -> None:
    summary = SolverRunSummary.from_mapping(
        {
            "success": "false",
            "passed": "false",
            "reference": "40.0",
            "relative_error": "0.0625",
            "tolerance": "0.1",
        }
    )

    assert summary.success is False
    assert summary.passed is False
    assert summary.verification_status == "failed"


def test_solver_run_summary_failed_success_overrides_conflicting_pass_fields() -> None:
    summary = SolverRunSummary.from_mapping(
        {
            "success": False,
            "passed": True,
            "verification_status": "passed",
            "reference": 1.0,
            "predicted": 1.0,
            "relative_error": 0.0,
            "tolerance": 0.01,
        }
    )

    assert summary.success is False
    assert summary.passed is False
    assert summary.verification_status == "failed"


def test_error_record_redacts_sensitive_tokens_from_exception_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_KEY", "sk-env-secret-token")
    exc = RuntimeError(
        "provider failed with sk-env-secret-token, sk-provider-secret-123456, "
        "tp-provider-secret-123456, Bearer abc.def-123 and "
        "https://example.com/v1?api_key=query-secret&x=1"
    )

    record = ErrorRecord.from_exception("solver", exc)

    assert record.code == "solver_failed"
    assert "sk-env-secret-token" not in record.message
    assert "sk-provider-secret-123456" not in record.message
    assert "tp-provider-secret-123456" not in record.message
    assert "abc.def-123" not in record.message
    assert "query-secret" not in record.message
    assert "sk-***" in record.message
    assert "tp-***" in record.message
    assert "Bearer ***" in record.message
    assert "api_key=***" in record.message


def test_post_processing_summary_preserves_agent_traces() -> None:
    solver_summary = SolverRunSummary.from_mapping(
        {"success": True, "passed": True, "predicted": 1.2, "tip_deflection_mm": 1.2}
    )
    post_trace = AgentLLMTrace(agent="PostProcAgent", used=False)
    analyst_trace = AgentLLMTrace(agent="AnalystAgent", used=False)

    summary = PostProcessingSummary.from_solver_summary(solver_summary, post_trace)
    summary.analyst_llm_trace = analyst_trace

    assert summary.get("tip_deflection_mm") == 1.2
    assert summary.verification_status == "unverified"
    assert summary.to_mapping()["postproc_llm_trace"]["agent"] == "PostProcAgent"
    assert summary.to_mapping()["analyst_llm_trace"]["agent"] == "AnalystAgent"


def test_post_processing_summary_uses_postprocessor_scalars() -> None:
    solver_summary = SolverRunSummary.from_mapping(
        {"success": True, "passed": True, "predicted": 1.2, "tip_deflection_mm": 1.2}
    )
    post_trace = AgentLLMTrace(agent="PostProcAgent", used=False)

    summary = PostProcessingSummary.from_solver_summary(
        solver_summary,
        post_trace,
        {"derived_metric": 2.4},
    )

    assert summary.get("derived_metric") == 2.4
    assert summary.get("tip_deflection_mm") == 1.2


def test_workflow_summary_redacts_llm_prompt_and_response_text() -> None:
    trace = AgentLLMTrace(
        agent="Planner",
        used=True,
        prompt="private prompt payload",
        response="private model response",
    )
    solver_trace = AgentLLMTrace(
        agent="SolverAgent",
        used=True,
        prompt="solver private prompt",
        response="solver private response",
    )
    solver_summary = SolverRunSummary.from_mapping(
        {
            "success": True,
            "passed": True,
            "solver_llm_trace": solver_trace.model_dump(mode="json"),
        }
    )
    post_trace = AgentLLMTrace(
        agent="PostProcAgent",
        used=True,
        prompt="post private prompt",
        response="post private response",
    )
    post_summary = PostProcessingSummary.from_solver_summary(solver_summary, post_trace)
    post_summary.analyst_llm_trace = trace
    reporter_trace = AgentLLMTrace(
        agent="ReporterAgent",
        used=True,
        prompt="reporter private prompt",
        response="reporter private response",
    )
    result = WorkflowResult(
        success=True,
        request="run",
        reporter_llm_trace=reporter_trace,
        tasks=[
            TaskRunRecord(
                task=TaskItem(
                    task_id="TASK_1",
                    case_id="STATIC-STRUCTURAL",
                    title="结构静力分析",
                    planner_llm_trace=trace,
                ),
                designer_llm_trace=trace,
                mesh_llm_trace=trace,
                solver_result=solver_summary,
                post_summary=post_summary,
            )
        ],
    )

    summary_text = str(result.summary())
    task_summary = result.summary()["tasks"][0]

    assert "private prompt" not in summary_text
    assert "private response" not in summary_text
    assert result.summary()["reporter_llm_trace"]["agent"] == "ReporterAgent"
    assert result.summary()["reporter_llm_trace"]["prompt_chars"] == len(reporter_trace.prompt)
    assert task_summary["planner_llm_trace"]["agent"] == "Planner"
    assert task_summary["planner_llm_trace"]["prompt_chars"] == len(trace.prompt)
    assert task_summary["solver_result"]["solver_llm_trace"]["agent"] == "SolverAgent"
    assert task_summary["solver_result"]["values"]["solver_llm_trace"]["response_chars"] == len(
        solver_trace.response
    )


def test_workflow_summary_redacts_sensitive_tokens_from_trace_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_KEY", "sk-env-summary-secret")
    trace = AgentLLMTrace(
        agent="Planner",
        used=True,
        error=(
            "provider failed with sk-env-summary-secret, tp-summary-secret-123456, "
            "Bearer summary.token and https://example.com?token=query-secret"
        ),
    )
    result = WorkflowResult(
        success=False,
        request="run",
        reporter_llm_trace=trace,
        tasks=[
            TaskRunRecord(
                task=TaskItem(
                    task_id="TASK_1",
                    case_id="STATIC-STRUCTURAL",
                    title="结构静力分析",
                    planner_llm_trace=trace,
                )
            )
        ],
    )

    summary_text = str(result.summary())

    assert "sk-env-summary-secret" not in summary_text
    assert "tp-summary-secret-123456" not in summary_text
    assert "summary.token" not in summary_text
    assert "query-secret" not in summary_text
    assert "tp-***" in summary_text
    assert "Bearer ***" in summary_text
    assert "token=***" in summary_text


def test_workflow_summary_recursively_redacts_llm_traces_in_extension_fields() -> None:
    trace = AgentLLMTrace(
        agent="PluginAgent",
        used=True,
        prompt="nested private prompt",
        response="nested private response",
    )
    solver_summary = SolverRunSummary.from_mapping(
        {
            "success": True,
            "predicted": 1.0,
            "custom_trace": trace,
            "nested": {
                "trace": trace.model_dump(mode="json"),
                "outputs": [Path("run.frd")],
            },
        }
    )
    post_trace = AgentLLMTrace(agent="PostProcAgent", used=False)
    post_summary = PostProcessingSummary.from_solver_summary(
        solver_summary,
        post_trace,
        {"post_nested": {"trace": trace}},
    )
    result = WorkflowResult(
        success=True,
        request="run",
        tasks=[
            TaskRunRecord(
                task=TaskItem(task_id="TASK_1", case_id="UNIT-CUSTOM", title="自定义能力"),
                solver_result=solver_summary,
                post_summary=post_summary,
            )
        ],
    )

    summary = result.summary()
    summary_text = str(summary)
    task_summary = summary["tasks"][0]

    assert "nested private prompt" not in summary_text
    assert "nested private response" not in summary_text
    assert task_summary["solver_result"]["values"]["custom_trace"]["prompt_chars"] == len(
        trace.prompt
    )
    assert task_summary["solver_result"]["values"]["nested"]["trace"]["response_chars"] == len(
        trace.response
    )
    assert task_summary["solver_result"]["values"]["nested"]["outputs"] == ["run.frd"]
    assert task_summary["post_summary"]["scalars"]["post_nested"]["trace"]["agent"] == (
        "PluginAgent"
    )


def test_summary_to_mapping_redacts_trace_text_and_serializes_extension_values() -> None:
    trace = AgentLLMTrace(
        agent="PluginAgent",
        used=True,
        prompt="mapping private prompt",
        response="mapping private response",
    )
    solver_summary = SolverRunSummary.from_mapping(
        {
            "success": True,
            "predicted": 1.0,
            "solver_llm_trace": trace.model_dump(mode="json"),
            "custom_trace": trace,
            "output_path": Path("run.frd"),
        }
    )
    post_summary = PostProcessingSummary.from_solver_summary(
        solver_summary,
        AgentLLMTrace(agent="PostProcAgent", used=False),
        {"post_trace": trace},
    )

    solver_mapping = solver_summary.to_mapping()
    post_mapping = post_summary.to_mapping()
    mapping_text = str({"solver": solver_mapping, "post": post_mapping})

    assert "mapping private prompt" not in mapping_text
    assert "mapping private response" not in mapping_text
    assert solver_mapping["solver_llm_trace"]["prompt_chars"] == len(trace.prompt)
    assert solver_mapping["custom_trace"]["response_chars"] == len(trace.response)
    assert solver_mapping["output_path"] == "run.frd"
    assert post_mapping["post_trace"]["agent"] == "PluginAgent"

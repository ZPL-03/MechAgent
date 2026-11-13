"""核心 Pydantic 模型测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mechagent.core.exceptions import SolverError
from mechagent.core.mesher import (
    MeshConfig,
    MeshLocalSizeProvenance,
    MeshProvenance,
    MeshQualityGate,
)
from mechagent.core.models import (
    BCSpec,
    BCType,
    CompositeSpec,
    CoordinateSystem,
    ElementType,
    GeometrySpec,
    GeometryType,
    LoadSpec,
    LoadStepSpec,
    LoadType,
    MaterialSpec,
    MeshSizeFieldSpec,
    MeshSpec,
    ModelParams,
    ResultFieldSpec,
    SimulationCase,
    UnitSystem,
)
from mechagent.core.solver import SolverResult, enrich_solver_result
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


def test_mesh_local_size_field_contract_is_finite_and_refining() -> None:
    field = MeshSizeFieldSpec(region="root", size=2.0, distance=8.0)
    mesh = MeshSpec(
        element_type=ElementType.C3D4,
        seed_size=10.0,
        local_size_fields=[field],
    )

    assert mesh.local_size_fields[0].size == 2.0
    with pytest.raises(ValidationError, match="distance"):
        MeshSizeFieldSpec(region="root", size=8.0, distance=2.0)
    with pytest.raises(ValidationError, match="不能大于全局"):
        MeshSpec(
            element_type=ElementType.C3D4,
            seed_size=5.0,
            local_size_fields=[MeshSizeFieldSpec(region="root", size=6.0, distance=8.0)],
        )
    with pytest.raises(ValidationError, match="region 不能重复"):
        MeshSpec(
            element_type=ElementType.C3D4,
            seed_size=10.0,
            local_size_fields=[
                MeshSizeFieldSpec(region="root", size=2.0, distance=8.0),
                MeshSizeFieldSpec(region="x_min", size=3.0, distance=8.0),
            ],
        )


def test_unit_conversion_scales_mesh_local_size_fields() -> None:
    params = tc01_model_params().model_copy(
        update={
            "mesh": MeshSpec(
                element_type=ElementType.B31,
                seed_size=1.0,
                local_size_fields=[MeshSizeFieldSpec(region="root", size=0.5, distance=2.0)],
            )
        }
    )

    converted = UnitSystem(length="cm").to_canonical_model(params)

    assert converted.mesh.seed_size == pytest.approx(10.0)
    assert converted.mesh.local_size_fields[0].size == pytest.approx(5.0)
    assert converted.mesh.local_size_fields[0].distance == pytest.approx(20.0)


def test_mesh_provenance_rejects_inconsistent_local_size_fields() -> None:
    base: dict[str, Any] = {
        "case_id": "CAD-BOX",
        "geometry_type": "solid",
        "mesher": "gmsh-cad-inp",
        "seed_size_mm": 10.0,
        "element_type": "C3D4",
        "mesh_sha256": "a" * 64,
        "quality_metrics": {"min_sicn": 0.4},
        "quality_gate": MeshQualityGate(
            threshold=0.3,
            lower_bound_metrics=["min_sicn"],
            status="passed",
        ),
    }
    with pytest.raises(ValidationError, match="不能大于 seed_size"):
        MeshProvenance(
            **base,
            local_size_fields=[
                MeshLocalSizeProvenance(
                    region="root",
                    topology_ids=["face:1"],
                    topology_dimensions=[2],
                    size_mm=12.0,
                    distance_mm=20.0,
                )
            ],
        )

    with pytest.raises(ValidationError, match="region 不能重复"):
        MeshProvenance(
            **base,
            local_size_fields=[
                MeshLocalSizeProvenance(
                    region="root",
                    topology_ids=["face:1"],
                    topology_dimensions=[2],
                    size_mm=2.0,
                    distance_mm=8.0,
                ),
                MeshLocalSizeProvenance(
                    region="ROOT",
                    topology_ids=["face:2"],
                    topology_dimensions=[2],
                    size_mm=3.0,
                    distance_mm=8.0,
                ),
            ],
        )

    with pytest.raises(ValidationError, match="topology_ids 不能包含重复"):
        MeshProvenance(
            **base,
            local_size_fields=[
                MeshLocalSizeProvenance(
                    region="root",
                    topology_ids=["face:1", "face:1"],
                    topology_dimensions=[2],
                    size_mm=2.0,
                    distance_mm=8.0,
                )
            ],
        )


def test_solver_result_records_relative_artifact_hashes(tmp_path: Path) -> None:
    input_file = tmp_path / "case.inp"
    output_file = tmp_path / "case.frd"
    input_file.write_text("*HEADING\n", encoding="utf-8")
    output_file.write_bytes(b"result")

    enriched = enrich_solver_result(
        SolverResult(success=True, wall_time=0.1, output_files=[output_file]), input_file
    )

    assert enriched.input_sha256 == hashlib.sha256(input_file.read_bytes()).hexdigest()
    assert [item.path for item in enriched.artifacts] == ["case.frd", "case.inp"]
    assert all(len(item.sha256) == 64 for item in enriched.artifacts)


def test_solver_result_resolves_filename_relative_to_work_directory(tmp_path: Path) -> None:
    input_file = tmp_path / "case.inp"
    output_file = tmp_path / "case.frd"
    input_file.write_text("*HEADING\n", encoding="utf-8")
    output_file.write_bytes(b"result")

    enriched = enrich_solver_result(
        SolverResult(success=True, wall_time=0.1, output_files=[Path(output_file.name)]),
        input_file,
    )

    assert [item.path for item in enriched.artifacts] == ["case.frd", "case.inp"]


def test_solver_result_rejects_artifact_outside_work_directory(tmp_path: Path) -> None:
    input_file = tmp_path / "case.inp"
    outside = tmp_path.parent / "outside.frd"
    input_file.write_text("*HEADING\n", encoding="utf-8")
    outside.write_text("result", encoding="utf-8")
    try:
        with pytest.raises(SolverError, match="超出工作目录"):
            enrich_solver_result(
                SolverResult(success=True, wall_time=0.1, output_files=[outside]), input_file
            )
    finally:
        outside.unlink(missing_ok=True)


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


def test_simulation_case_wraps_legacy_model_with_explicit_provenance() -> None:
    params = tc01_model_params()
    case = SimulationCase.from_model_params(
        params,
        raw_request="长1000mm钢悬臂梁静力分析",
        parser="test-parser",
        parser_version="1",
    )

    assert case.schema_version == 1
    assert case.units.length == "mm"
    assert case.coordinate_system.handedness == "right"
    assert set(case.regions) == {"root", "tip"}
    assert case.request is not None and case.request.parser == "test-parser"
    restored = case.to_model_params()
    assert restored.geometry == params.geometry
    assert restored.metadata["case_schema_version"] == 1
    assert [step.step_id for step in case.load_steps] == ["step-1"]
    assert case.load_steps[0].result_fields == ["displacement"]
    assert case.result_fields[0].quantity == "U"
    assert restored.metadata["load_steps"][0]["step_id"] == "step-1"
    assert restored.metadata["result_fields"][0]["name"] == "displacement"


def test_simulation_case_validates_load_step_result_field_references() -> None:
    params = tc01_model_params()
    payload = SimulationCase.from_model_params(params).model_dump(mode="json")
    payload["result_fields"] = [
        ResultFieldSpec(
            name="stress",
            quantity="S",
            location="integration_point",
            invariant="mises",
            unit="MPa",
        ).model_dump(mode="json")
    ]
    payload["load_steps"][0]["result_fields"] = ["displacement"]

    with pytest.raises(ValidationError, match="未知结果字段"):
        SimulationCase.model_validate(payload)


def test_simulation_case_rejects_non_legacy_multi_step_projection() -> None:
    params = tc01_model_params()
    case = SimulationCase.from_model_params(params)
    second_step = LoadStepSpec(
        step_id="step-2",
        sequence=2,
        analysis=params.analysis.type,
        result_fields=["displacement"],
    )
    multi_step = case.model_copy(update={"load_steps": [case.load_steps[0], second_step]})

    with pytest.raises(ValueError, match="只支持 1 个"):
        multi_step.to_model_params()


def test_result_field_rejects_component_and_invariant_together() -> None:
    with pytest.raises(ValidationError, match="component 与 invariant"):
        ResultFieldSpec(
            name="stress",
            quantity="S",
            location="integration_point",
            component="S11",
            invariant="mises",
        )


def test_load_step_rejects_output_interval_larger_than_increments() -> None:
    with pytest.raises(ValidationError, match="output_interval"):
        LoadStepSpec(increments=2, output_interval=3)


def test_simulation_case_rejects_non_default_step_duration_projection() -> None:
    params = tc01_model_params()
    case = SimulationCase.from_model_params(params)
    step = case.load_steps[0].model_copy(update={"duration": 2.0})
    non_default = case.model_copy(update={"load_steps": [step]})

    with pytest.raises(ValueError, match="duration"):
        non_default.to_model_params()


def test_simulation_case_requires_explicit_provenance_confidence_for_execution() -> None:
    params = tc01_model_params()
    legacy_case = SimulationCase.from_model_params(params)

    assert legacy_case.execution_ready is False
    readiness = legacy_case.execution_readiness()
    assert readiness.ready is False
    assert readiness.lowest_confidence is None
    assert any("provenance.geometry.confidence 缺失" in item for item in readiness.blockers)
    with pytest.raises(ValueError, match="执行前检查失败"):
        legacy_case.ensure_execution_ready()

    low_confidence_case = SimulationCase.from_model_params(
        params,
        provenance_confidence=0.79,
    )
    assert low_confidence_case.execution_readiness().lowest_confidence == pytest.approx(0.79)
    with pytest.raises(ValueError, match="低于 0.800"):
        low_confidence_case.ensure_execution_ready()

    executable_case = SimulationCase.from_model_params(
        params,
        provenance_confidence=0.8,
    )
    assert executable_case.execution_ready is True
    assert executable_case.ensure_execution_ready() is executable_case


def test_simulation_case_rejects_invalid_execution_confidence() -> None:
    with pytest.raises(ValueError, match="provenance_confidence"):
        SimulationCase.from_model_params(tc01_model_params(), provenance_confidence=1.1)


def test_simulation_case_rejects_future_schema_and_unknown_units() -> None:
    params = tc01_model_params()
    payload = SimulationCase.from_model_params(params).model_dump(mode="json")
    payload["schema_version"] = 99
    with pytest.raises(ValidationError):
        SimulationCase.model_validate(payload)
    payload = SimulationCase.from_model_params(params).model_dump(mode="json")
    payload["units"]["length"] = "yard"
    with pytest.raises(ValidationError):
        SimulationCase.model_validate(payload)


def test_simulation_case_converts_declared_units_to_solver_baseline() -> None:
    params = tc01_model_params()
    model = params.model_copy(
        update={
            "geometry": params.geometry.model_copy(
                update={"dimensions": {"length": 1.0, "width": 0.02, "height": 0.04}}
            ),
            "material": params.material.model_copy(update={"E": 210.0, "rho": 7850.0}),
            "loads": [params.loads[0].model_copy(update={"magnitude": 1.0})],
            "bcs": [params.bcs[0].model_copy(update={"values": [0.001, 0.0, 0.0, 0.0, 0.0, 0.0]})],
            "mesh": params.mesh.model_copy(update={"seed_size": 0.01}),
        }
    )
    case = SimulationCase.from_model_params(model).model_copy(
        update={
            "units": UnitSystem(length="m", force="kN", stress="GPa", density="kg/m^3"),
            "coordinate_system": CoordinateSystem(origin=(1.0, 2.0, 3.0)),
        }
    )

    restored = case.to_model_params()

    assert restored.geometry.dimensions == {"length": 1000.0, "width": 20.0, "height": 40.0}
    assert pytest.approx(210000.0) == restored.material.E
    assert pytest.approx(7.85e-9) == restored.material.rho
    assert pytest.approx(1000.0) == restored.loads[0].magnitude
    assert restored.bcs[0].values[0] == pytest.approx(1.0)
    assert restored.mesh.seed_size == pytest.approx(10.0)
    assert restored.metadata["canonical_coordinate_system"]["origin"] == [1000.0, 2000.0, 3000.0]


def test_unit_conversion_scales_load_quantities_by_physical_dimension() -> None:
    params = tc01_model_params()
    model = params.model_copy(
        update={
            "loads": [
                LoadSpec(
                    type=LoadType.LINE_LOAD, magnitude=1.0, region="span", direction=(0, -1, 0)
                ),
                LoadSpec(
                    type=LoadType.PRESSURE, magnitude=1.0, region="surface", direction=(0, 0, -1)
                ),
                LoadSpec(
                    type=LoadType.DISPLACEMENT, magnitude=1.0, region="tip", direction=(1, 0, 0)
                ),
                LoadSpec(type=LoadType.MOMENT, magnitude=1.0, region="tip", direction=(0, 0, 1)),
            ]
        }
    )

    converted = UnitSystem(length="m", force="kN").to_canonical_model(model)

    assert converted.loads[0].magnitude == pytest.approx(1.0)
    assert converted.loads[1].magnitude == pytest.approx(0.001)
    assert converted.loads[2].magnitude == pytest.approx(1000.0)
    assert converted.loads[3].magnitude == pytest.approx(1_000_000.0)


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


def test_solver_run_summary_normalizes_equilibrium_after_solver_failure() -> None:
    summary = SolverRunSummary.from_mapping(
        {
            "success": False,
            "equilibrium": {
                "status": "passed",
                "applied_resultant": [0.0, -100.0, 0.0],
                "reaction_resultant": [0.0, 100.0, 0.0],
                "residual": [0.0, 0.0, 0.0],
                "tolerance": {"relative": 0.01, "absolute": 0.005},
            },
        }
    )

    assert summary.verification_status == "failed"
    assert summary.equilibrium is not None
    assert summary.equilibrium.status == "failed"
    assert summary.equilibrium.reason == "求解结果失败，不能进行反力平衡校核。"
    assert summary.to_mapping()["equilibrium"]["status"] == "failed"


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


def test_workflow_summary_limits_solver_paths_to_portable_names(tmp_path: Path) -> None:
    private_root = tmp_path / "private-engineering-workdir"
    solver_summary = SolverRunSummary.from_mapping(
        {
            "success": True,
            "output_files": [
                str(private_root / "case.inp"),
                r"C:\Users\工程师\runs\case.frd",
                r"\\server\share\case.odb",
            ],
            "mesh_file": str(private_root / "mesh.inp"),
            "field_json": str(private_root / "case.fields.json"),
            "odb": str(private_root / "case.odb"),
            "artifacts": [{"path": "case.inp", "size": 1, "sha256": "a" * 64}],
        }
    )
    result = WorkflowResult(
        success=True,
        request="run",
        tasks=[
            TaskRunRecord(
                task=TaskItem(task_id="TASK_1", case_id="UNIT", title="结构静力分析"),
                solver_result=solver_summary,
            )
        ],
    )

    summary = result.summary()
    public_solver = summary["tasks"][0]["solver_result"]

    assert str(private_root) not in str(summary)
    assert public_solver["output_files"] == ["case.inp", "case.frd", "case.odb"]
    assert public_solver["mesh_file"] == "mesh.inp"
    assert public_solver["values"]["field_json"] == "case.fields.json"
    assert public_solver["values"]["odb"] == "case.odb"


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

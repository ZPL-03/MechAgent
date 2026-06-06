"""仿真能力注册表测试。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mechagent.config import LLMSettings, MechAgentConfig, OrchestratorSettings
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
from mechagent.core.validation import tc01_model_params
from mechagent.orchestrator.agents import DesignerAgent, PlannerAgent
from mechagent.orchestrator.capabilities import (
    SimulationCapability,
    all_capabilities,
    get_capability,
    match_capabilities,
    register_capability,
    registered_capability_ids,
    unregister_capability,
)
from mechagent.orchestrator.evaluation import ResultEvaluationContext
from mechagent.orchestrator.intent import SimulationIntent
from mechagent.orchestrator.models import TaskItem

_COMPOUND_STATIC_REQUEST = (
    "求解梁长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，"
    "沿梁竖向向下1kN/m均布线载荷的静力响应；"
    "矩形板300mmx200mmx5mm，材料铝，四边简支，承受0.01MPa均布压力静力分析"
)


def test_capability_registry_exposes_structural_static() -> None:
    capability = get_capability("structural_static")

    assert capability.task_case_id == "STATIC-STRUCTURAL"
    assert capability.title == "结构静力分析"
    assert capability.analysis_type == "static"
    assert capability.solver_name == "calculix"
    assert capability.mesher_name == "calculix-inp"
    assert capability.execution_validator is not None
    assert capability.geometry_detector("长1000mm 的悬臂梁静力分析") == "beam"
    assert capability.evaluator(
        ResultEvaluationContext(
            model_params=tc01_model_params(),
            solver_result={"success": True, "tip_deflection_mm": 14.880952380952381},
            solver_name="unit",
            task_case_id=capability.task_case_id,
            task_title=capability.title,
        )
    )["passed"]


def test_match_capabilities_returns_intent() -> None:
    intents = match_capabilities("求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，向下1000N")

    assert len(intents) == 1
    assert intents[0].capability_id == "structural_static"
    assert intents[0].geometry_type == "beam"
    assert intents[0].complete


def test_planner_uses_capability_task_descriptor() -> None:
    capability = get_capability("structural_static")

    task = PlannerAgent().plan("求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，向下1000N")[
        0
    ]

    assert task.case_id == capability.task_case_id
    assert task.title == capability.title


def test_planner_uses_llm_capability_intent_when_local_match_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_completion(prompt: str, _config: object) -> str:
        assert "已注册能力编号" in prompt
        assert "结构线弹性静力分析" in prompt
        assert "钢制悬臂梁" in prompt
        return """
        {
          "capability_id": "structural_static",
          "analysis_type": "static",
          "physics_domain": "structural",
          "geometry_type": "beam",
          "missing_fields": [],
          "confidence": 0.91
        }
        """

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )

    task = PlannerAgent(config).plan("请处理这根钢梁模型")[0]

    assert task.capability_id == "structural_static"
    assert task.task_id == "TASK_1"
    assert task.intent is not None
    assert task.intent.geometry_type == "beam"
    assert task.intent.source == "llm"
    assert not task.intent.complete
    assert task.intent.missing_fields == ["梁长", "矩形截面尺寸", "固支边界", "载荷"]
    assert task.planner_llm_trace is not None
    assert task.planner_llm_trace.used is True


def test_planner_uses_custom_capability_descriptors_in_llm_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_completion(prompt: str, _config: object) -> str:
        assert "unit custom planner description" in prompt
        assert "unit-custom-keyword" in prompt
        assert "unit custom example request" in prompt
        return """
        {
          "capability_id": "unit_test_planner_descriptor",
          "analysis_type": "static",
          "physics_domain": "structural",
          "geometry_type": "shell",
          "missing_fields": [],
          "confidence": 0.88
        }
        """

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    capability = SimulationCapability(
        capability_id="unit_test_planner_descriptor",
        task_case_id="UNIT-TEST-PLANNER-DESCRIPTOR",
        title="单元测试 Planner 描述符能力",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_shell_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: "shell",
        evaluator=_unit_test_evaluator,
        planner_description="unit custom planner description",
        planner_keywords=("unit-custom-keyword",),
        example_requests=("unit custom example request",),
    )
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )

    register_capability(capability)
    try:
        task = PlannerAgent(config).plan("unit ambiguous request")[0]

        assert task.capability_id == "unit_test_planner_descriptor"
        assert task.intent is not None
        assert task.intent.geometry_type == "shell"
    finally:
        unregister_capability("unit_test_planner_descriptor")


def test_match_capabilities_returns_solid_intent() -> None:
    intents = match_capabilities(
        "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
    )

    assert len(intents) == 1
    assert intents[0].capability_id == "structural_static"
    assert intents[0].geometry_type == "solid"
    assert intents[0].complete


def test_match_capabilities_splits_compound_static_request() -> None:
    intents = match_capabilities(_COMPOUND_STATIC_REQUEST)

    assert len(intents) == 2
    assert [intent.capability_id for intent in intents] == [
        "structural_static",
        "structural_static",
    ]
    assert [intent.geometry_type for intent in intents] == ["beam", "plate"]
    assert all(intent.complete for intent in intents)
    assert "；" not in intents[0].raw_request
    assert "；" not in intents[1].raw_request


def test_match_capabilities_applies_custom_splitter_before_matcher() -> None:
    capability = SimulationCapability(
        capability_id="unit_test_split_before_match",
        task_case_id="UNIT-TEST-SPLIT-BEFORE-MATCH",
        title="单元测试拆分优先能力",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda request: request.startswith("unit-task:"),
        geometry_detector=lambda request: "beam" if "beam" in request else "plate",
        evaluator=_unit_test_evaluator,
        request_splitter=lambda request: tuple(
            item.strip() for item in request.split(";") if item.strip()
        ),
    )

    register_capability(capability)
    try:
        intents = match_capabilities("header text; unit-task: beam; ignored; unit-task: plate")

        unit_intents = [
            intent for intent in intents if intent.capability_id == "unit_test_split_before_match"
        ]
        assert [intent.geometry_type for intent in unit_intents] == ["beam", "plate"]
        assert [intent.raw_request for intent in unit_intents] == [
            "unit-task: beam",
            "unit-task: plate",
        ]
    finally:
        unregister_capability("unit_test_split_before_match")


def test_planner_outputs_independent_tasks_for_compound_static_request() -> None:
    tasks = PlannerAgent().plan(_COMPOUND_STATIC_REQUEST)

    assert [task.task_id for task in tasks] == ["TASK_1", "TASK_2"]
    assert [task.case_id for task in tasks] == ["STATIC-STRUCTURAL", "STATIC-STRUCTURAL"]
    assert [task.intent.geometry_type if task.intent else None for task in tasks] == [
        "beam",
        "plate",
    ]
    assert tasks[0].intent is not None
    assert "悬臂梁" in tasks[0].intent.raw_request
    assert tasks[1].intent is not None
    assert "矩形板" in tasks[1].intent.raw_request


def test_match_capabilities_reports_missing_fields_without_blocking_planner() -> None:
    intents = match_capabilities("求解一个悬臂梁一端固支，一端垂直受压50KN/m的受力情况")

    assert len(intents) == 1
    assert "梁长" in intents[0].missing_fields
    assert "矩形截面尺寸" in intents[0].missing_fields
    assert "材料" in intents[0].missing_fields
    assert not intents[0].complete


def test_all_capabilities_are_unique() -> None:
    ids = [capability.capability_id for capability in all_capabilities()]
    task_case_ids = [capability.task_case_id for capability in all_capabilities()]

    assert len(ids) == len(set(ids))
    assert len(task_case_ids) == len(set(task_case_ids))
    assert "structural_static" in registered_capability_ids()


def test_register_custom_capability_participates_in_matching() -> None:
    capability = SimulationCapability(
        capability_id="unit_test_static",
        task_case_id="UNIT-TEST-STATIC",
        title="单元测试能力",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda request: "unit-test-request" in request,
        geometry_detector=lambda _request: "beam",
        evaluator=_unit_test_evaluator,
    )

    register_capability(capability)
    try:
        intents = match_capabilities("unit-test-request")

        assert intents[-1].capability_id == "unit_test_static"
        assert intents[-1].geometry_type == "beam"
    finally:
        unregister_capability("unit_test_static")

    assert "unit_test_static" not in registered_capability_ids()


def test_designer_does_not_apply_structural_static_contract_to_custom_capability() -> None:
    capability = SimulationCapability(
        capability_id="unit_test_shell_static",
        task_case_id="UNIT-TEST-SHELL-STATIC",
        title="单元测试壳静力能力",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_shell_parser,
        matcher=lambda request: "unit-test-shell" in request,
        geometry_detector=lambda _request: "shell",
        evaluator=_unit_test_evaluator,
    )

    register_capability(capability)
    try:
        params = DesignerAgent().design(_unit_test_task(capability, "unit-test-shell"))

        assert params.geometry.type is GeometryType.SHELL
    finally:
        unregister_capability("unit_test_shell_static")


def test_designer_uses_capability_llm_contract_for_custom_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_completion(prompt: str, _config: object) -> str:
        assert "unit shell LLM contract" in prompt
        assert "UNIT-SHELL" in prompt
        assert "STATIC-BEAM" not in prompt
        return json.dumps(_unit_shell_llm_payload(), ensure_ascii=False)

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    capability = SimulationCapability(
        capability_id="unit_test_shell_llm",
        task_case_id="UNIT-TEST-SHELL-LLM",
        title="单元测试壳 LLM 能力",
        analysis_type="static",
        physics_domain="structural",
        parser=_llm_only_parser,
        matcher=lambda request: "unit-test-shell-llm" in request,
        geometry_detector=lambda _request: "shell",
        evaluator=_unit_test_evaluator,
        llm_model_contract="unit shell LLM contract",
        model_case_ids=("UNIT-SHELL",),
    )
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )

    register_capability(capability)
    try:
        output = DesignerAgent(config).design_with_trace(
            _unit_test_task(capability, "unit-test-shell-llm")
        )

        assert output.designer_llm_trace.used is True
        assert output.designer_llm_trace.error is None
        assert output.model_params.geometry.type is GeometryType.SHELL
        assert output.model_params.case_id == "UNIT-SHELL"
        assert output.model_params.metadata["source"] == "llm_structured"
    finally:
        unregister_capability("unit_test_shell_llm")


def test_designer_uses_llm_params_when_intent_has_missing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_completion(prompt: str, _config: object) -> str:
        assert "\nAgent: Designer\n" in prompt
        return json.dumps(_unit_shell_llm_payload(), ensure_ascii=False)

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    capability = SimulationCapability(
        capability_id="unit_test_shell_llm_missing_intent",
        task_case_id="UNIT-TEST-SHELL-LLM-MISSING-INTENT",
        title="单元测试壳 LLM 缺参补齐能力",
        analysis_type="static",
        physics_domain="structural",
        parser=_llm_only_parser,
        matcher=lambda request: "unit-test-shell-llm-missing" in request,
        geometry_detector=lambda _request: "shell",
        evaluator=_unit_test_evaluator,
        llm_model_contract="unit shell LLM contract",
        model_case_ids=("UNIT-SHELL",),
    )
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )
    task = _unit_test_task(capability, "unit-test-shell-llm-missing")
    assert task.intent is not None
    task = task.model_copy(
        update={
            "intent": task.intent.model_copy(
                update={"missing_fields": ["壳厚", "载荷"], "confidence": 0.75}
            )
        }
    )

    register_capability(capability)
    try:
        output = DesignerAgent(config).design_with_trace(task)

        assert output.designer_llm_trace.used is True
        assert output.designer_llm_trace.error is None
        assert output.model_params.geometry.type is GeometryType.SHELL
        assert output.model_params.case_id == "UNIT-SHELL"
    finally:
        unregister_capability("unit_test_shell_llm_missing_intent")


def test_designer_rejects_parser_model_case_outside_capability_declaration() -> None:
    capability = SimulationCapability(
        capability_id="unit_test_model_case_contract",
        task_case_id="UNIT-TEST-MODEL-CASE",
        title="单元测试模型编号契约",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_shell_parser,
        matcher=lambda request: "unit-test-model-case" in request,
        geometry_detector=lambda _request: "shell",
        evaluator=_unit_test_evaluator,
        model_case_ids=("UNIT-OTHER",),
    )

    register_capability(capability)
    try:
        with pytest.raises(ValueError, match="模型编号不在能力声明范围"):
            DesignerAgent().design(_unit_test_task(capability, "unit-test-model-case"))
    finally:
        unregister_capability("unit_test_model_case_contract")


def test_designer_rejects_llm_model_case_outside_capability_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_completion(prompt: str, _config: object) -> str:
        assert "UNIT-SHELL" in prompt
        return json.dumps(_unit_shell_llm_payload(case_id="UNIT-DRIFT"), ensure_ascii=False)

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    capability = SimulationCapability(
        capability_id="unit_test_llm_model_case_contract",
        task_case_id="UNIT-TEST-LLM-MODEL-CASE",
        title="单元测试 LLM 模型编号契约",
        analysis_type="static",
        physics_domain="structural",
        parser=_llm_only_parser,
        matcher=lambda request: "unit-test-llm-model-case" in request,
        geometry_detector=lambda _request: "shell",
        evaluator=_unit_test_evaluator,
        llm_model_contract="unit shell LLM contract",
        model_case_ids=("UNIT-SHELL",),
    )
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )

    register_capability(capability)
    try:
        with pytest.raises(ValueError, match="模型编号不在能力声明范围"):
            DesignerAgent(config).design(_unit_test_task(capability, "unit-test-llm-model-case"))
    finally:
        unregister_capability("unit_test_llm_model_case_contract")


def test_designer_runs_capability_execution_validator() -> None:
    def reject_model(_params: ModelParams) -> None:
        raise ValueError("unit capability execution validator rejected model")

    capability = SimulationCapability(
        capability_id="unit_test_validator",
        task_case_id="UNIT-TEST-VALIDATOR",
        title="单元测试执行契约",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda request: "unit-test-validator" in request,
        geometry_detector=lambda _request: "beam",
        evaluator=_unit_test_evaluator,
        execution_validator=reject_model,
    )

    register_capability(capability)
    try:
        with pytest.raises(ValueError, match="unit capability execution validator"):
            DesignerAgent().design(_unit_test_task(capability, "unit-test-validator"))
    finally:
        unregister_capability("unit_test_validator")


def test_capability_missing_field_detector_is_independent_from_parser() -> None:
    capability = SimulationCapability(
        capability_id="unit_test_missing_detector",
        task_case_id="UNIT-TEST-MISSING",
        title="单元测试缺参诊断",
        analysis_type="static",
        physics_domain="structural",
        parser=_parser_should_not_run,
        matcher=lambda request: "unit-test-missing" in request,
        geometry_detector=lambda _request: "beam",
        evaluator=_unit_test_evaluator,
        missing_field_detector=lambda _request: ["材料"],
    )

    register_capability(capability)
    try:
        intents = match_capabilities("unit-test-missing")

        assert intents[-1].capability_id == "unit_test_missing_detector"
        assert intents[-1].missing_fields == ["材料"]
        assert not intents[-1].complete
    finally:
        unregister_capability("unit_test_missing_detector")


def test_duplicate_capability_task_case_is_rejected() -> None:
    capability = SimulationCapability(
        capability_id="unit_test_duplicate_task",
        task_case_id="STATIC-STRUCTURAL",
        title="重复任务类别",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
    )

    with pytest.raises(ValueError, match="任务类别编号已注册"):
        register_capability(capability)


def test_register_capability_rejects_unclean_descriptor_fields() -> None:
    blank_title = SimulationCapability(
        capability_id="unit_test_blank_title",
        task_case_id="UNIT-TEST-BLANK-TITLE",
        title="",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
    )
    padded_id = SimulationCapability(
        capability_id=" unit_test_padded ",
        task_case_id="UNIT-TEST-PADDED",
        title="首尾空白编号",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
    )

    with pytest.raises(ValueError, match="title 不能为空"):
        register_capability(blank_title)
    with pytest.raises(ValueError, match="capability_id 不能包含首尾空白"):
        register_capability(padded_id)


def test_register_capability_rejects_unclean_planner_descriptors() -> None:
    padded_description = SimulationCapability(
        capability_id="unit_test_padded_description",
        task_case_id="UNIT-TEST-PADDED-DESCRIPTION",
        title="首尾空白描述",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
        planner_description=" padded ",
    )
    blank_keyword = SimulationCapability(
        capability_id="unit_test_blank_keyword",
        task_case_id="UNIT-TEST-BLANK-KEYWORD",
        title="空白关键词",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
        planner_keywords=(" ",),
    )
    padded_solver = SimulationCapability(
        capability_id="unit_test_padded_solver",
        task_case_id="UNIT-TEST-PADDED-SOLVER",
        title="首尾空白求解器",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
        solver_name=" unit-solver ",
    )
    padded_mesher = SimulationCapability(
        capability_id="unit_test_padded_mesher",
        task_case_id="UNIT-TEST-PADDED-MESHER",
        title="首尾空白网格器",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
        mesher_name=" unit-mesher ",
    )

    with pytest.raises(ValueError, match="planner_description 不能包含首尾空白"):
        register_capability(padded_description)
    with pytest.raises(ValueError, match="planner_keywords 不能包含空白条目"):
        register_capability(blank_keyword)
    with pytest.raises(ValueError, match="solver_name 不能包含首尾空白"):
        register_capability(padded_solver)
    with pytest.raises(ValueError, match="mesher_name 不能包含首尾空白"):
        register_capability(padded_mesher)


def test_register_capability_rejects_unregistered_tool_names() -> None:
    unknown_solver = SimulationCapability(
        capability_id="unit_test_unknown_solver",
        task_case_id="UNIT-TEST-UNKNOWN-SOLVER",
        title="未知求解器",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
        solver_name="unit-missing-solver",
    )
    unknown_mesher = SimulationCapability(
        capability_id="unit_test_unknown_mesher",
        task_case_id="UNIT-TEST-UNKNOWN-MESHER",
        title="未知网格器",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
        mesher_name="unit-missing-mesher",
    )

    with pytest.raises(ValueError, match="solver_name 未注册"):
        register_capability(unknown_solver)
    with pytest.raises(ValueError, match="mesher_name 未注册"):
        register_capability(unknown_mesher)


def test_register_capability_normalizes_default_tool_names() -> None:
    capability = SimulationCapability(
        capability_id="unit_test_tool_name_normalization",
        task_case_id="UNIT-TEST-TOOL-NAME-NORMALIZATION",
        title="工具名称规范化",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
        solver_name="CALCULIX",
        mesher_name="CALCULIX-INP",
    )

    register_capability(capability)
    try:
        stored = get_capability("unit_test_tool_name_normalization")

        assert stored.solver_name == "calculix"
        assert stored.mesher_name == "calculix-inp"
    finally:
        unregister_capability("unit_test_tool_name_normalization")


def test_register_capability_rejects_unclean_model_case_ids() -> None:
    blank_model_case = SimulationCapability(
        capability_id="unit_test_blank_model_case",
        task_case_id="UNIT-TEST-BLANK-MODEL-CASE",
        title="空白模型编号",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
        model_case_ids=(" ",),
    )
    padded_model_case = SimulationCapability(
        capability_id="unit_test_padded_model_case",
        task_case_id="UNIT-TEST-PADDED-MODEL-CASE",
        title="首尾空白模型编号",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
        model_case_ids=(" UNIT ",),
    )

    with pytest.raises(ValueError, match="model_case_ids 不能包含空白条目"):
        register_capability(blank_model_case)
    with pytest.raises(ValueError, match="model_case_ids 不能包含首尾空白"):
        register_capability(padded_model_case)


def test_get_capability_accepts_padded_lookup_text() -> None:
    assert get_capability(" structural_static ").capability_id == "structural_static"


def test_replace_capability_rejects_other_capability_task_case() -> None:
    capability = SimulationCapability(
        capability_id="unit_test_replace_collision",
        task_case_id="STATIC-STRUCTURAL",
        title="覆盖冲突",
        analysis_type="static",
        physics_domain="structural",
        parser=_unit_test_parser,
        matcher=lambda _request: False,
        geometry_detector=lambda _request: None,
        evaluator=_unit_test_evaluator,
    )

    with pytest.raises(ValueError, match="任务类别编号已注册"):
        register_capability(capability, replace=True)


def test_simulation_intent_complete_property() -> None:
    intent = SimulationIntent(raw_request="x", capability_id="structural_static")

    assert intent.complete


def _unit_test_parser(_request: str) -> ModelParams:
    return tc01_model_params()


def _unit_test_shell_parser(_request: str) -> ModelParams:
    return ModelParams(
        geometry=GeometrySpec(
            type=GeometryType.SHELL,
            dimensions={"length": 100.0, "width": 50.0, "thickness": 2.0},
        ),
        material=MaterialSpec(E=210000.0, nu=0.3, rho=7.85e-9),
        loads=[
            LoadSpec(
                type=LoadType.PRESSURE,
                magnitude=0.01,
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
        mesh=MeshSpec(element_type=ElementType.S4, seed_size=1.0),
        analysis=AnalysisSpec(type=AnalysisType.STATIC, nlgeom=False),
        case_id="UNIT-SHELL",
        load_case="unit_shell_pressure",
    )


def _unit_shell_llm_payload(case_id: str = "UNIT-SHELL") -> dict[str, Any]:
    return {
        "geometry": {
            "type": "shell",
            "dimensions": {"length": 120.0, "width": 60.0, "thickness": 2.0},
        },
        "material": {"E": 210000.0, "nu": 0.3, "rho": 7.85e-9},
        "loads": [
            {
                "type": "pressure",
                "magnitude": 0.01,
                "region": "top_surface",
                "direction": [0.0, 0.0, -1.0],
            }
        ],
        "bcs": [
            {
                "type": "simple_support",
                "region": "all_edges",
                "dofs": ["uz"],
                "values": [0.0],
            }
        ],
        "mesh": {"element_type": "S4", "seed_size": 2.0},
        "analysis": {"type": "static", "nlgeom": False},
        "case_id": case_id,
        "load_case": "unit_shell_pressure",
        "metadata": {},
    }


def _llm_only_parser(_request: str) -> ModelParams:
    raise ValueError("unit capability requires LLM structured parameters")


def _unit_test_task(capability: SimulationCapability, raw_request: str) -> TaskItem:
    return TaskItem(
        task_id="TASK_1",
        case_id=capability.task_case_id,
        capability_id=capability.capability_id,
        title=capability.title,
        analysis_type=capability.analysis_type,
        intent=SimulationIntent(
            raw_request=raw_request,
            capability_id=capability.capability_id,
        ),
    )


def _parser_should_not_run(_request: str) -> ModelParams:
    pytest.fail("parser should not run during intent diagnostics")


def _unit_test_evaluator(context: ResultEvaluationContext) -> dict[str, Any]:
    return {
        **context.solver_result,
        "model_case_id": context.model_params.case_id or context.task_case_id,
        "passed": True,
        "quantity": "unit",
        "unit": "",
        "solver": context.solver_name,
        "task_title": context.task_title,
    }

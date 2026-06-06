"""LLM 结构化仿真参数解析测试。"""

from __future__ import annotations

import json

import pytest

from mechagent.orchestrator.capabilities import all_capabilities, get_capability
from mechagent.orchestrator.llm_advisor import AgentLLMTrace
from mechagent.orchestrator.llm_structured import (
    capability_intent_payload,
    parse_llm_capability_intent,
    parse_llm_model_params,
)


def test_parse_llm_model_params_preserves_zero_poisson_ratio_and_false_nlgeom() -> None:
    trace = AgentLLMTrace(
        agent="Designer",
        used=True,
        response=json.dumps(
            {
                "geometry": {"type": "beam", "length": "1000", "width": "20", "height": "40"},
                "material": {"E": "210000", "nu": "0.0", "rho": "7.85e-9"},
                "loads": [{"type": "force", "magnitude": "1000", "direction": "downward"}],
                "bcs": [{"type": "fixed"}],
                "mesh": {"element_type": "B31", "seed_size": "10"},
                "analysis": {"type": "static", "nlgeom": "false"},
                "metadata": {},
            }
        ),
    )

    capability = get_capability("structural_static")
    params, parsed_trace = parse_llm_model_params(
        trace,
        "梁端部集中力静力分析",
        normalizer=capability.model_normalizer,
    )

    assert parsed_trace.error is None
    assert params is not None
    assert params.case_id == "STATIC-BEAM"
    assert params.geometry.dimensions == {"length": 1000.0, "width": 20.0, "height": 40.0}
    assert params.material.nu == 0.0
    assert params.analysis.nlgeom is False
    assert params.loads[0].direction == (0.0, -1.0, 0.0)


def test_capability_intent_payload_includes_planner_descriptors() -> None:
    payload = json.loads(capability_intent_payload("静力梁分析", all_capabilities()))
    structural = [
        item for item in payload["capabilities"] if item["capability_id"] == "structural_static"
    ][0]

    assert "结构线弹性静力分析" in structural["description"]
    assert "梁" in structural["keywords"]
    assert structural["solver_name"] == "calculix"
    assert structural["mesher_name"] == "calculix-inp"
    assert structural["example_requests"]


def test_parse_llm_capability_intent_normalizes_common_string_outputs() -> None:
    trace = AgentLLMTrace(
        agent="Planner",
        used=True,
        response=json.dumps(
            {
                "capability_id": "Structural Static",
                "analysis_type": "static",
                "physics_domain": "structural",
                "geometry_type": "beam",
                "missing_fields": "材料、梁长",
                "confidence": "1.2",
            },
            ensure_ascii=False,
        ),
    )

    intent, parsed_trace = parse_llm_capability_intent(
        trace,
        "悬臂梁受力分析",
        all_capabilities(),
    )

    assert parsed_trace.error is None
    assert intent is not None
    assert intent.capability_id == "structural_static"
    assert intent.missing_fields == ["材料", "梁长"]
    assert intent.confidence == 1.0


def test_parse_llm_model_params_accepts_compact_plate_payload() -> None:
    trace = AgentLLMTrace(
        agent="Designer",
        used=True,
        response=json.dumps(
            {
                "geometry": {
                    "type": "plate",
                    "size": {"x": "300", "y": "200", "thickness": "5"},
                },
                "material": {
                    "type": "steel",
                    "elastic": {"young_modulus": "210000", "poisson_ratio": "0.3"},
                    "density": "7.85e-9",
                },
                "loads": [{"type": "pressure", "value": "0.01", "direction": "-z"}],
                "bcs": [{"type": "simple_support"}],
                "mesh": {"element_type": "S4", "size": "5"},
                "analysis": {"type": "static"},
                "case_id": "plate_case",
                "load_case": "pressure_case",
                "metadata": {},
            }
        ),
    )

    capability = get_capability("structural_static")
    params, parsed_trace = parse_llm_model_params(
        trace,
        "矩形板静力分析",
        normalizer=capability.model_normalizer,
    )

    assert parsed_trace.error is None
    assert params is not None
    assert params.case_id == "STATIC-PLATE"
    assert params.geometry.dimensions == {"length": 300.0, "width": 200.0, "thickness": 5.0}
    assert params.material.type.value == "isotropic"
    assert params.loads[0].magnitude == 0.01
    assert params.loads[0].direction == (0.0, 0.0, -1.0)
    assert params.bcs[0].region == "all_edges"


def test_parse_llm_model_params_accepts_compact_solid_payload() -> None:
    trace = AgentLLMTrace(
        agent="Designer",
        used=True,
        response=json.dumps(
            {
                "geometry": {"type": "solid", "dimensions": {"x": "200", "y": "20", "z": "20"}},
                "material": {"E": "210000", "nu": "0.3", "rho": "7.85e-9"},
                "loads": [{"type": "force", "amount": "4000", "direction": "tension"}],
                "bcs": [{"type": "fixed"}],
                "mesh": {"element_type": "C3D8R", "element_size": "10"},
                "analysis": {"type": "static"},
                "metadata": {},
            }
        ),
    )

    capability = get_capability("structural_static")
    params, parsed_trace = parse_llm_model_params(
        trace,
        "矩形实体轴向拉伸",
        normalizer=capability.model_normalizer,
    )

    assert parsed_trace.error is None
    assert params is not None
    assert params.case_id == "STATIC-SOLID"
    assert params.load_case == "fixed_solid_axial_force"
    assert params.geometry.dimensions == {"length": 200.0, "width": 20.0, "height": 20.0}
    assert params.loads[0].region == "end_face"
    assert params.loads[0].direction == (1.0, 0.0, 0.0)
    assert params.bcs[0].dofs == ["ux", "uy", "uz"]


def test_parse_llm_model_params_normalizes_explicit_unit_payload() -> None:
    trace = AgentLLMTrace(
        agent="Designer",
        used=True,
        response=json.dumps(
            {
                "geometry": {
                    "type": "plate",
                    "dimensions": {
                        "x": {"value": 0.3, "unit": "m"},
                        "y": {"value": 20, "unit": "cm"},
                        "thickness": "5 mm",
                    },
                },
                "material": {
                    "E": "70 GPa",
                    "nu": "0.33",
                    "density": {"value": 2700, "unit": "kg/m^3"},
                },
                "loads": [{"type": "pressure", "value": "10 kPa", "direction": "-z"}],
                "bcs": [{"type": "simple_support"}],
                "mesh": {"element_type": "S4", "seed_size": {"value": 0.5, "unit": "cm"}},
                "analysis": {"type": "static"},
                "metadata": {},
            },
            ensure_ascii=False,
        ),
    )

    capability = get_capability("structural_static")
    params, parsed_trace = parse_llm_model_params(
        trace,
        "矩形板显式单位静力分析",
        normalizer=capability.model_normalizer,
    )

    assert parsed_trace.error is None
    assert params is not None
    assert params.case_id == "STATIC-PLATE"
    assert params.geometry.dimensions == {"length": 300.0, "width": 200.0, "thickness": 5.0}
    assert params.material.E == 70000.0
    assert params.material.rho == pytest.approx(2.7e-9)
    assert params.loads[0].magnitude == 0.01
    assert params.mesh.seed_size == 5.0


def test_parse_llm_model_params_normalizes_chinese_structured_payloads() -> None:
    capability = get_capability("structural_static")
    cases = [
        (
            {
                "geometry": {
                    "type": "梁",
                    "dimensions": {"长度": "1000", "截面宽": "20", "截面高": "40"},
                },
                "material": {"弹性模量": "210000", "泊松比": "0.3", "密度": "7.85e-9"},
                "load": {"type": "集中力", "大小": "1000", "direction": "向下"},
                "boundary_condition": {"type": "固支"},
                "mesh": {"element_type": "B31", "seed_size": "10"},
                "analysis": {"type": "static"},
                "metadata": {},
            },
            "中文悬臂梁端部集中力静力分析",
            "STATIC-BEAM",
            "cantilever_tip_force",
            "force",
            {"length": 1000.0, "width": 20.0, "height": 40.0},
            (0.0, -1.0, 0.0),
        ),
        (
            {
                "geometry": {
                    "type": "矩形板",
                    "dimensions": {"长度": "300", "宽度": "200", "厚度": "5"},
                },
                "material": {"弹性模量": "210000", "泊松比": "0.3", "密度": "7.85e-9"},
                "loads": [{"type": "均布压力", "压力": "0.01", "direction": "向下"}],
                "bcs": [{"type": "简支"}],
                "mesh": {"element_type": "S4", "seed_size": "5"},
                "analysis": {"type": "static"},
                "metadata": {},
            },
            "矩形板四边简支均布压力静力分析",
            "STATIC-PLATE",
            "simply_supported_pressure",
            "pressure",
            {"length": 300.0, "width": 200.0, "thickness": 5.0},
            (0.0, 0.0, -1.0),
        ),
        (
            {
                "geometry": {
                    "type": "长方体",
                    "dimensions": {"长度": "200", "宽度": "20", "高度": "20"},
                },
                "material": {"弹性模量": "210000", "泊松比": "0.3", "密度": "7.85e-9"},
                "loads": [{"type": "压力", "压力": "10", "direction": "受压"}],
                "bcs": [{"type": "固定"}],
                "mesh": {"element_type": "C3D8R", "seed_size": "10"},
                "analysis": {"type": "static"},
                "metadata": {},
            },
            "长方体实体左端固定右端受压静力分析",
            "STATIC-SOLID",
            "fixed_solid_axial_pressure",
            "pressure",
            {"length": 200.0, "width": 20.0, "height": 20.0},
            (-1.0, 0.0, 0.0),
        ),
    ]

    for payload, request, case_id, load_case, load_type, dimensions, direction in cases:
        trace = AgentLLMTrace(
            agent="Designer",
            used=True,
            response=json.dumps(payload, ensure_ascii=False),
        )
        params, parsed_trace = parse_llm_model_params(
            trace,
            request,
            normalizer=capability.model_normalizer,
        )

        assert parsed_trace.error is None
        assert params is not None
        assert params.case_id == case_id
        assert params.load_case == load_case
        assert params.geometry.dimensions == dimensions
        assert params.material.E == 210000.0
        assert params.material.nu == 0.3
        assert params.material.rho == 7.85e-9
        assert params.loads[0].type.value == load_type
        assert params.loads[0].direction == direction
        assert params.metadata["source"] == "llm_structured"
        assert params.metadata["raw_request"] == request


def test_parse_llm_model_params_normalizes_load_and_dof_aliases() -> None:
    trace = AgentLLMTrace(
        agent="Designer",
        used=True,
        response=json.dumps(
            {
                "geometry": {
                    "type": "beam",
                    "dimensions": {"length": "1200", "width": "30", "height": "50"},
                },
                "material": {"E": "210000", "nu": "0.3", "rho": "7.85e-9"},
                "loads": [
                    {
                        "type": "concentrated",
                        "magnitude": "1200",
                        "region": "tip",
                        "direction": "downward",
                    }
                ],
                "bcs": [
                    {
                        "type": "clamped",
                        "region": "root",
                        "dofs": [1, 2, 3, 4, 5, 6],
                        "values": [0, 0, 0, 0, 0, 0],
                    }
                ],
                "mesh": {"element_type": "B31", "seed_size": "12"},
                "analysis": {"type": "static"},
                "metadata": {},
            },
            ensure_ascii=False,
        ),
    )

    capability = get_capability("structural_static")
    params, parsed_trace = parse_llm_model_params(
        trace,
        "中文数字悬臂梁静力分析",
        normalizer=capability.model_normalizer,
    )

    assert parsed_trace.error is None
    assert params is not None
    assert params.loads[0].type.value == "force"
    assert params.bcs[0].type.value == "fixed"
    assert params.bcs[0].dofs == ["ux", "uy", "uz", "rx", "ry", "rz"]


def test_parse_llm_model_params_normalizes_linear_nlgeom_text_as_false() -> None:
    trace = AgentLLMTrace(
        agent="Designer",
        used=True,
        response=json.dumps(
            {
                "geometry": {
                    "type": "beam",
                    "dimensions": {"length": "1000", "width": "20", "height": "40"},
                },
                "material": {"E": "210000", "nu": "0.3", "rho": "7.85e-9"},
                "loads": [{"type": "force", "magnitude": "1000", "direction": "downward"}],
                "bcs": [{"type": "fixed"}],
                "mesh": {"element_type": "B31", "seed_size": "10"},
                "analysis": {"type": "static", "nlgeom": "linear"},
                "metadata": {},
            },
            ensure_ascii=False,
        ),
    )

    capability = get_capability("structural_static")
    params, parsed_trace = parse_llm_model_params(
        trace,
        "线性静力悬臂梁",
        normalizer=capability.model_normalizer,
    )

    assert parsed_trace.error is None
    assert params is not None
    assert params.analysis.nlgeom is False


def test_parse_llm_model_params_accepts_single_load_and_boundary_objects() -> None:
    trace = AgentLLMTrace(
        agent="Designer",
        used=True,
        response=json.dumps(
            {
                "geometry": {
                    "type": "beam",
                    "dimensions": {"length": "1000", "width": "20", "height": "40"},
                },
                "material": {"E": "210000", "nu": "0.3", "rho": "7.85e-9"},
                "load": {"type": "force", "magnitude": "1000", "direction": "downward"},
                "boundary_conditions": {"type": "fixed"},
                "mesh": {"element_type": "B31", "seed_size": "10"},
                "analysis": {"type": "static"},
                "metadata": {},
            },
            ensure_ascii=False,
        ),
    )

    capability = get_capability("structural_static")
    params, parsed_trace = parse_llm_model_params(
        trace,
        "单载荷单边界对象格式的悬臂梁",
        normalizer=capability.model_normalizer,
    )

    assert parsed_trace.error is None
    assert params is not None
    assert len(params.loads) == 1
    assert len(params.bcs) == 1
    assert params.loads[0].type.value == "force"
    assert params.bcs[0].dofs == ["ux", "uy", "uz", "rx", "ry", "rz"]


def test_parse_llm_model_params_prefers_non_empty_single_objects_over_empty_lists() -> None:
    trace = AgentLLMTrace(
        agent="Designer",
        used=True,
        response=json.dumps(
            {
                "geometry": {
                    "type": "beam",
                    "dimensions": {"length": "1000", "width": "20", "height": "40"},
                },
                "material": {"E": "210000", "nu": "0.3", "rho": "7.85e-9"},
                "loads": [],
                "load_condition": {
                    "type": "force",
                    "magnitude": "1000",
                    "direction": "downward",
                },
                "bcs": [],
                "boundary_condition": {"type": "fixed"},
                "mesh": {"element_type": "B31", "seed_size": "10"},
                "analysis": {"type": "static"},
                "metadata": {},
            },
            ensure_ascii=False,
        ),
    )

    capability = get_capability("structural_static")
    params, parsed_trace = parse_llm_model_params(
        trace,
        "空数组和单对象混合格式的悬臂梁",
        normalizer=capability.model_normalizer,
    )

    assert parsed_trace.error is None
    assert params is not None
    assert len(params.loads) == 1
    assert len(params.bcs) == 1
    assert params.loads[0].magnitude == 1000.0
    assert params.bcs[0].region == "root"


def test_parse_llm_model_params_reports_unsupported_explicit_unit() -> None:
    trace = AgentLLMTrace(
        agent="Designer",
        used=True,
        response=json.dumps(
            {
                "geometry": {"type": "beam", "length": "40 inch", "width": 20, "height": 40},
                "material": {"E": "210000", "nu": "0.3", "rho": "7.85e-9"},
                "loads": [{"type": "force", "magnitude": "1000", "direction": "downward"}],
                "bcs": [{"type": "fixed"}],
                "mesh": {"element_type": "B31", "seed_size": "10"},
                "analysis": {"type": "static"},
                "metadata": {},
            }
        ),
    )

    params, parsed_trace = parse_llm_model_params(trace, "英制单位梁静力分析")

    assert params is None
    assert parsed_trace.error is not None
    assert "不支持的长度单位" in parsed_trace.error


def test_parse_llm_model_params_without_normalizer_preserves_case_ids() -> None:
    trace = AgentLLMTrace(
        agent="Designer",
        used=True,
        response=json.dumps(
            {
                "geometry": {"type": "beam", "length": "1000", "width": "20", "height": "40"},
                "material": {"E": "210000", "nu": "0.3", "rho": "7.85e-9"},
                "loads": [{"type": "force", "magnitude": "1000", "direction": "downward"}],
                "bcs": [{"type": "fixed"}],
                "mesh": {"element_type": "B31", "seed_size": "10"},
                "analysis": {"type": "static"},
                "case_id": "CUSTOM-BEAM",
                "load_case": "custom_tip_force",
                "metadata": {},
            }
        ),
    )

    params, parsed_trace = parse_llm_model_params(trace, "自定义梁能力")

    assert parsed_trace.error is None
    assert params is not None
    assert params.case_id == "CUSTOM-BEAM"
    assert params.load_case == "custom_tip_force"
    assert params.metadata["source"] == "llm_structured"

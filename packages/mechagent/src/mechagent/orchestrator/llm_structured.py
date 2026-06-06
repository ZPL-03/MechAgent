"""LLM 结构化仿真意图与参数解析。"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Callable, Optional

from pydantic import ValidationError

from mechagent.core.models import BCType, GeometryType, LoadType, MaterialType, ModelParams
from mechagent.orchestrator.capabilities import SimulationCapability
from mechagent.orchestrator.intent import SimulationIntent
from mechagent.orchestrator.llm_advisor import AgentLLMTrace
from mechagent.orchestrator.llm_json import parse_json_object

_NUMBER = r"[-+]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:e[-+]?\d+)?"
_NUMBER_WITH_UNIT = re.compile(rf"^\s*({_NUMBER})\s*([^\d\s].*)?\s*$", re.IGNORECASE)


def capability_intent_contract(capabilities: tuple[SimulationCapability, ...]) -> str:
    """生成 Planner LLM 能力识别输出契约。"""

    capability_ids = ", ".join(item.capability_id for item in capabilities)
    return (
        "只输出一个 JSON 对象。字段: "
        "`capability_id` 为已注册能力编号或 null；"
        "`analysis_type`、`physics_domain`、`geometry_type` 为字符串或 null；"
        "`missing_fields` 为字符串数组；`confidence` 为 0 到 1 的数字。"
        f"已注册能力编号: {capability_ids}。"
    )


def capability_intent_payload(request: str, capabilities: tuple[SimulationCapability, ...]) -> str:
    """生成 Planner LLM 能力识别上下文。"""

    data = {
        "request": request,
        "capabilities": [
            {
                "capability_id": item.capability_id,
                "title": item.title,
                "analysis_type": item.analysis_type,
                "physics_domain": item.physics_domain,
                "solver_name": item.solver_name,
                "mesher_name": item.mesher_name,
                "description": item.planner_description,
                "keywords": list(item.planner_keywords),
                "example_requests": list(item.example_requests),
            }
            for item in capabilities
        ],
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def parse_llm_capability_intent(
    trace: AgentLLMTrace,
    request: str,
    capabilities: tuple[SimulationCapability, ...],
) -> tuple[Optional[SimulationIntent], AgentLLMTrace]:
    """从 Planner LLM 响应解析标准化仿真意图。"""

    if not trace.used or trace.error or not trace.response.strip():
        return None, trace
    capability_by_id = {item.capability_id: item for item in capabilities}
    try:
        data = parse_json_object(trace.response)
    except ValueError as exc:
        return None, _trace_with_error(trace, f"LLM 任务识别响应无法解析: {exc}")

    try:
        capability_id = _capability_id_value(data.get("capability_id"), capability_by_id)
    except ValueError as exc:
        return None, _trace_with_error(trace, str(exc))
    if capability_id is None:
        return None, trace

    capability = capability_by_id[capability_id]
    missing_fields = _string_list(data.get("missing_fields"))
    confidence = _confidence(data.get("confidence"))
    return (
        SimulationIntent(
            raw_request=request,
            capability_id=capability_id,
            analysis_type=_optional_str(data.get("analysis_type")) or capability.analysis_type,
            physics_domain=_optional_str(data.get("physics_domain")) or capability.physics_domain,
            geometry_type=_optional_str(data.get("geometry_type")),
            missing_fields=missing_fields,
            confidence=confidence,
            source="llm",
        ),
        trace,
    )


ModelParamsNormalizer = Callable[[ModelParams, str], ModelParams]


def model_params_contract(capability: SimulationCapability | None = None) -> str:
    """生成 Designer LLM `ModelParams` 输出契约。"""

    base_contract = (
        "只输出一个 JSON 对象，字段必须符合 ModelParams。"
        "所有长度单位统一为 mm，弹性模量为 MPa，力为 N，压力为 MPa。"
        "`geometry.type` 使用项目 GeometryType 枚举；"
        "`geometry` 必须包含 `dimensions` 字典；"
        "`material` 必须包含 `E`、`nu`、`rho`，rho 使用 tonne/mm^3；"
        "`loads[].type` 使用项目 LoadType 枚举；"
        "`loads[]` 必须包含 `magnitude`、`region`、`direction`；"
        "`bcs[].type` 使用项目 BCType 枚举；"
        "`bcs[]` 必须包含 `region`、`dofs`、`values`；"
        "`mesh.element_type` 使用项目 ElementType 枚举，"
        "`mesh.seed_size` 根据几何尺度自动给出正值。"
        "JSON 必须包含 geometry、material、loads、bcs、mesh、analysis、"
        "case_id、load_case、metadata。不得输出 solver 或其他未在 schema 中定义的字段。"
    )
    if capability is None or not capability.llm_model_contract:
        return base_contract
    return f"{base_contract}能力补充契约: {capability.llm_model_contract}"


def model_params_payload(
    request: str,
    capability: SimulationCapability,
    draft: Optional[ModelParams] = None,
) -> str:
    """生成 Designer LLM 结构化参数抽取上下文。"""

    data = {
        "request": request,
        "capability": {
            "capability_id": capability.capability_id,
            "title": capability.title,
            "analysis_type": capability.analysis_type,
            "physics_domain": capability.physics_domain,
            "model_case_ids": list(capability.model_case_ids),
            "llm_model_contract": capability.llm_model_contract,
        },
    }
    if draft is not None:
        data["validated_local_draft"] = draft.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def parse_llm_model_params(
    trace: AgentLLMTrace,
    request: str,
    normalizer: ModelParamsNormalizer | None = None,
) -> tuple[Optional[ModelParams], AgentLLMTrace]:
    """从 Designer LLM 响应解析 `ModelParams`。"""

    if not trace.used or trace.error or not trace.response.strip():
        return None, trace
    try:
        data = parse_json_object(trace.response)
        payload = data.get("model_params", data)
        if not isinstance(payload, dict):
            msg = "ModelParams JSON 必须是对象。"
            raise ValueError(msg)
        params = ModelParams.model_validate(_coerce_model_params_payload(payload))
    except (ValueError, ValidationError) as exc:
        return None, _trace_with_error(trace, f"LLM 结构化参数无法解析: {exc}")

    if normalizer is not None:
        return normalizer(params, request), trace
    return _normalize_llm_model_params_metadata(params, request), trace


def _normalize_llm_model_params_metadata(params: ModelParams, request: str) -> ModelParams:
    metadata = dict(params.metadata)
    metadata["source"] = "llm_structured"
    metadata["raw_request"] = request
    return params.model_copy(update={"metadata": metadata})


def _coerce_model_params_payload(payload: dict[str, Any]) -> dict[str, Any]:
    geometry = _coerce_geometry(_dict_value(payload.get("geometry")))
    geometry_type = str(geometry.get("type", ""))
    loads = [
        _coerce_load(_dict_value(item), geometry_type)
        for item in _object_list_value(
            _first_present_object_list_raw(
                payload,
                ("loads", "load", "loadings", "load_condition", "load_conditions"),
            )
        )
        if isinstance(item, dict)
    ]
    bcs = [
        _coerce_bc(_dict_value(item), geometry_type)
        for item in _object_list_value(
            _first_present_object_list_raw(
                payload,
                (
                    "bcs",
                    "bc",
                    "boundary_conditions",
                    "boundary_condition",
                    "boundaries",
                    "boundary",
                ),
            )
        )
        if isinstance(item, dict)
    ]
    return {
        "geometry": geometry,
        "material": _coerce_material(_dict_value(payload.get("material"))),
        "loads": loads,
        "bcs": bcs,
        "mesh": _coerce_mesh(_dict_value(payload.get("mesh"))),
        "analysis": _coerce_analysis(_dict_value(payload.get("analysis"))),
        "case_id": str(payload.get("case_id", "")),
        "load_case": str(payload.get("load_case", "")),
        "metadata": _dict_value(payload.get("metadata")),
    }


def _coerce_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    geometry_type = _geometry_type(geometry.get("type"))
    dimensions = _dict_value(
        geometry.get("dimensions")
        or geometry.get("size")
        or geometry.get("shape")
        or geometry.get("geometry")
    )
    if not dimensions and geometry_type == "beam":
        section = _dict_value(geometry.get("section") or geometry.get("cross_section"))
        dimensions = {
            "length": _quantity_value(geometry, _length_names("beam"), "length"),
            "width": _first_present_number(
                _quantity_value(section, _width_names("beam"), "length"),
                _quantity_value(geometry, _width_names("beam"), "length"),
            ),
            "height": _first_present_number(
                _quantity_value(section, _height_names("beam"), "length"),
                _quantity_value(geometry, _height_names("beam"), "length"),
            ),
        }
    elif not dimensions and geometry_type == "plate":
        dimensions = {
            "length": _quantity_value(geometry, _length_names("plate"), "length"),
            "width": _quantity_value(geometry, _width_names("plate"), "length"),
            "thickness": _quantity_value(geometry, _thickness_names(), "length"),
        }
    elif not dimensions and geometry_type == "solid":
        dimensions = {
            "length": _quantity_value(geometry, _length_names("solid"), "length"),
            "width": _quantity_value(geometry, _width_names("solid"), "length"),
            "height": _quantity_value(geometry, _height_names("solid"), "length"),
        }
    dimensions = _normalized_dimensions(dimensions, geometry_type)
    return {
        "type": geometry_type,
        "dimensions": {key: value for key, value in dimensions.items() if value is not None},
    }


def _coerce_material(material: dict[str, Any]) -> dict[str, Any]:
    elastic = _dict_value(material.get("elastic") or material.get("elasticity"))
    return {
        "type": _material_type(material.get("type")),
        "E": _first_present_number(
            _quantity_value(
                material,
                (
                    "E",
                    "elastic_modulus",
                    "youngs_modulus",
                    "young_modulus",
                    "young",
                    "弹性模量",
                    "杨氏模量",
                ),
                "modulus",
            ),
            _quantity_value(
                elastic,
                (
                    "E",
                    "elastic_modulus",
                    "youngs_modulus",
                    "young_modulus",
                    "弹性模量",
                    "杨氏模量",
                ),
                "modulus",
            ),
        ),
        "nu": _first_present_number(
            _number_value(material, ("nu", "poisson_ratio", "poissons_ratio", "泊松比")),
            _number_value(elastic, ("nu", "poisson_ratio", "poissons_ratio", "泊松比")),
        ),
        "rho": _quantity_value(material, ("rho", "density", "密度"), "density"),
    }


def _coerce_load(load: dict[str, Any], geometry_type: str) -> dict[str, Any]:
    load_type = _load_type(load.get("type"))
    return {
        "type": load_type,
        "magnitude": _quantity_value(
            load,
            ("magnitude", "value", "amount", "大小", "幅值", "载荷", "荷载", "力", "压力"),
            load_type,
        ),
        "region": load.get("region") or _default_load_region(geometry_type, load_type),
        "direction": _direction_value(
            load.get("direction") or load.get("vector") or load.get("components"),
            geometry_type,
        ),
    }


def _coerce_bc(bc: dict[str, Any], geometry_type: str) -> dict[str, Any]:
    bc_type = _bc_type(bc.get("type"))
    dofs = _dof_list_value(bc.get("dofs")) or _default_bc_dofs(geometry_type, bc_type)
    return {
        "type": bc_type,
        "region": bc.get("region") or _default_bc_region(bc_type),
        "dofs": dofs,
        "values": _list_value(bc.get("values")) or [0.0 for _ in dofs],
    }


def _coerce_mesh(mesh: dict[str, Any]) -> dict[str, Any]:
    return {
        "element_type": mesh.get("element_type"),
        "seed_size": _quantity_value(mesh, ("seed_size", "size", "element_size"), "length"),
    }


def _coerce_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": analysis.get("type", "static"),
        "nlgeom": _bool_value(analysis.get("nlgeom", False)),
    }


def _default_load_region(geometry_type: str, load_type: str) -> str:
    if geometry_type == "beam":
        return "span" if load_type == "line_load" else "tip"
    if geometry_type == "solid":
        return "end_face"
    return "top_surface"


def _material_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    allowed = {item.value for item in MaterialType}
    return text if text in allowed else MaterialType.ISOTROPIC.value


def _geometry_type(value: Any) -> str:
    text = _normalized_token(value)
    aliases = {
        GeometryType.BEAM.value: {
            "beam",
            "line_beam",
            "cantilever",
            "cantilever_beam",
            "梁",
            "悬臂梁",
            "梁结构",
            "杆",
            "杆件",
        },
        GeometryType.PLATE.value: {
            "plate",
            "thin_plate",
            "rectangular_plate",
            "板",
            "薄板",
            "矩形板",
            "平板",
        },
        GeometryType.SOLID.value: {
            "solid",
            "block",
            "prism",
            "rectangular_solid",
            "实体",
            "实体块",
            "长方体",
            "矩形体",
            "块体",
        },
        GeometryType.SHELL.value: {"shell", "壳", "壳体"},
        GeometryType.STIFFENED_PANEL.value: {
            "stiffened_panel",
            "加筋板",
            "加筋壁板",
        },
        GeometryType.RVE.value: {"rve", "代表体元", "代表性体积单元"},
    }
    for canonical, candidates in aliases.items():
        if text in candidates:
            return canonical
    return text


def _load_type(value: Any) -> str:
    text = _normalized_token(value)
    aliases = {
        LoadType.FORCE.value: {
            "force",
            "concentrated",
            "concentrated_force",
            "point_force",
            "point_load",
            "nodal_force",
            "tip_force",
            "end_force",
            "集中力",
            "点载荷",
            "点力",
            "端部力",
            "端部集中力",
            "节点力",
        },
        LoadType.LINE_LOAD.value: {
            "line_load",
            "uniform_line_load",
            "distributed_line_load",
            "uniform_distributed_load",
            "udl",
            "线载荷",
            "线荷载",
            "均布线载荷",
            "均布线荷载",
            "分布线载荷",
            "全跨均布载荷",
        },
        LoadType.PRESSURE.value: {
            "pressure",
            "surface_pressure",
            "uniform_pressure",
            "distributed_pressure",
            "压力",
            "面载荷",
            "面荷载",
            "面压力",
            "均布压力",
            "表面压力",
        },
        LoadType.DISPLACEMENT.value: {
            "displacement",
            "prescribed_displacement",
            "位移",
            "强制位移",
            "给定位移",
        },
        LoadType.MOMENT.value: {
            "moment",
            "torque",
            "concentrated_moment",
            "弯矩",
            "力矩",
            "扭矩",
        },
        LoadType.TEMPERATURE.value: {"temperature", "thermal", "温度", "热载荷"},
    }
    for canonical, candidates in aliases.items():
        if text in candidates:
            return canonical
    return text


def _bc_type(value: Any) -> str:
    text = _normalized_token(value)
    aliases = {
        BCType.FIXED.value: {
            "fixed",
            "fixed_support",
            "clamped",
            "clamp",
            "固定",
            "固支",
            "夹持",
            "全约束",
        },
        BCType.ENCASTRE.value: {"encastre", "encastre_support"},
        BCType.PINNED.value: {"pinned", "pin", "铰支", "铰接", "销接"},
        BCType.SIMPLE_SUPPORT.value: {
            "simple_support",
            "simply_supported",
            "simple_supported",
            "roller_support",
            "简支",
            "四边简支",
            "简单支承",
            "滚动支承",
        },
        BCType.SYMMETRY.value: {"symmetry", "symmetric", "对称", "对称边界"},
    }
    for canonical, candidates in aliases.items():
        if text in candidates:
            return canonical
    return text


def _dof_list_value(value: Any) -> list[str]:
    dof_aliases = {
        "1": "ux",
        "2": "uy",
        "3": "uz",
        "4": "rx",
        "5": "ry",
        "6": "rz",
        "u1": "ux",
        "u2": "uy",
        "u3": "uz",
        "ur1": "rx",
        "ur2": "ry",
        "ur3": "rz",
        "x": "ux",
        "y": "uy",
        "z": "uz",
        "ux": "ux",
        "uy": "uy",
        "uz": "uz",
        "rx": "rx",
        "ry": "ry",
        "rz": "rz",
    }
    result: list[str] = []
    for item in _list_value(value):
        key = _normalized_token(item)
        mapped = dof_aliases.get(key)
        result.append(mapped if mapped is not None else str(item).strip().lower())
    return [item for item in result if item]


def _normalized_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _direction_value(value: Any, geometry_type: str = "") -> Any:
    if isinstance(value, list):
        return [_coerce_numeric_item(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_coerce_numeric_item(item) for item in value)
    text = _normalized_token(value)
    if text in {"down", "downward", "向下", "下", "竖向向下", "垂直向下"}:
        return [0.0, 0.0, -1.0] if geometry_type == "plate" else [0.0, -1.0, 0.0]
    if text in {"up", "upward", "向上", "上", "竖向向上", "垂直向上"}:
        return [0.0, 0.0, 1.0] if geometry_type == "plate" else [0.0, 1.0, 0.0]
    if text in {"-y", "_y", "negative_y", "y负向", "负y"}:
        return [0.0, -1.0, 0.0]
    if text in {"+y", "positive_y", "y正向", "正y"}:
        return [0.0, 1.0, 0.0]
    if text in {"-z", "_z", "negative_z", "z负向", "负z"}:
        return [0.0, 0.0, -1.0]
    if text in {"+z", "positive_z", "z正向", "正z"}:
        return [0.0, 0.0, 1.0]
    if text in {"x", "+x", "positive_x", "x正向", "正x", "tension", "拉伸", "受拉", "向右"}:
        return [1.0, 0.0, 0.0]
    if text in {"-x", "_x", "negative_x", "x负向", "负x", "compression", "压缩", "受压", "向左"}:
        return [-1.0, 0.0, 0.0]
    return value


def _normalized_dimensions(dimensions: dict[str, Any], geometry_type: str) -> dict[str, Any]:
    if not dimensions:
        return {}
    if geometry_type == "beam":
        return {
            "length": _quantity_value(dimensions, _length_names("beam"), "length"),
            "width": _quantity_value(dimensions, _width_names("beam"), "length"),
            "height": _quantity_value(dimensions, _height_names("beam"), "length"),
        }
    if geometry_type == "plate":
        return {
            "length": _quantity_value(dimensions, _length_names("plate"), "length"),
            "width": _quantity_value(dimensions, _width_names("plate"), "length"),
            "thickness": _quantity_value(dimensions, _thickness_names(), "length"),
        }
    if geometry_type == "solid":
        return {
            "length": _quantity_value(dimensions, _length_names("solid"), "length"),
            "width": _quantity_value(dimensions, _width_names("solid"), "length"),
            "height": _quantity_value(dimensions, _height_names("solid"), "length"),
        }
    return dimensions


def _length_names(geometry_type: str) -> tuple[str, ...]:
    return ("length", "l", "x", "长度", "长", f"{geometry_type}_length", "梁长", "板长", "实体长")


def _width_names(geometry_type: str) -> tuple[str, ...]:
    return (
        "width",
        "b",
        "w",
        "y",
        "宽度",
        "宽",
        f"{geometry_type}_width",
        "截面宽",
        "截面宽度",
        "板宽",
        "实体宽",
    )


def _height_names(geometry_type: str) -> tuple[str, ...]:
    return (
        "height",
        "h",
        "z",
        "高度",
        "高",
        f"{geometry_type}_height",
        "截面高",
        "截面高度",
        "实体高",
    )


def _thickness_names() -> tuple[str, ...]:
    return ("thickness", "t", "height", "h", "z", "厚度", "厚", "板厚")


def _default_bc_region(bc_type: str) -> str:
    if bc_type == "simple_support":
        return "all_edges"
    return "root"


def _default_bc_dofs(geometry_type: str, bc_type: str) -> list[str]:
    if bc_type == "simple_support":
        return ["uz"]
    if geometry_type == "beam":
        return ["ux", "uy", "uz", "rx", "ry", "rz"]
    return ["ux", "uy", "uz"]


def _number_value(mapping: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        number = _numeric_value(mapping.get(name))
        if number is not None:
            return number
    return None


def _quantity_value(mapping: dict[str, Any], names: tuple[str, ...], quantity: str) -> Any:
    for name in names:
        if name not in mapping:
            continue
        number = _quantity_numeric_value(
            mapping.get(name),
            quantity,
            _unit_hint(mapping, name, quantity),
        )
        if number is not None:
            return number
    return None


def _quantity_numeric_value(value: Any, quantity: str, unit_hint: str | None) -> float | None:
    if isinstance(value, dict):
        raw_value = _first_present_raw(
            value,
            (
                "value",
                "magnitude",
                "amount",
                "number",
                "E",
                "rho",
                "density",
                "length",
                "width",
                "height",
                "thickness",
                "seed_size",
            ),
        )
        unit = _optional_unit(value.get("unit") or value.get("units")) or unit_hint
        return _convert_quantity(_numeric_value(raw_value), unit, quantity)
    if isinstance(value, str):
        parsed = _numeric_string_with_unit(value)
        if parsed is not None:
            number, unit = parsed
            return _convert_quantity(number, unit or unit_hint, quantity)
    return _convert_quantity(_numeric_value(value), unit_hint, quantity)


def _first_present_raw(mapping: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _first_present_object_list_raw(mapping: dict[str, Any], names: tuple[str, ...]) -> Any:
    fallback: Any = None
    for name in names:
        if name not in mapping:
            continue
        value = mapping[name]
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value:
            return value
        if fallback is None:
            fallback = value
    return fallback


def _unit_hint(mapping: dict[str, Any], name: str, quantity: str) -> str | None:
    units = _dict_value(mapping.get("units"))
    for key in (name, quantity):
        unit = _optional_unit(units.get(key))
        if unit is not None:
            return unit
    for key in (f"{name}_unit", f"{name}_units", f"{quantity}_unit", f"{quantity}_units"):
        unit = _optional_unit(mapping.get(key))
        if unit is not None:
            return unit
    unit = _optional_unit(mapping.get("unit"))
    if unit is not None and _unit_matches_quantity(unit, quantity):
        return unit
    return None


def _unit_matches_quantity(unit: str, quantity: str) -> bool:
    try:
        _convert_quantity(1.0, unit, quantity)
    except ValueError:
        return False
    return True


def _optional_unit(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _numeric_string_with_unit(value: str) -> tuple[float, str | None] | None:
    match = _NUMBER_WITH_UNIT.match(value)
    if match is None:
        return None
    unit = match.group(2).strip() if match.group(2) else None
    return float(match.group(1)), unit


def _convert_quantity(number: float | None, unit: str | None, quantity: str) -> float | None:
    if number is None:
        return None
    if unit is None:
        return number
    if quantity == "length":
        return _length_to_mm(number, unit)
    if quantity == "force":
        return _force_to_n(number, unit)
    if quantity == "line_load":
        return _line_load_to_n_per_mm(number, unit)
    if quantity in {"pressure", "modulus"}:
        return _pressure_to_mpa(number, unit)
    if quantity == "density":
        return _density_to_tonne_per_mm3(number, unit)
    return number


def _normalized_unit(unit: str) -> str:
    return (
        unit.strip()
        .lower()
        .replace(" ", "")
        .replace("²", "2")
        .replace("^2", "2")
        .replace("³", "3")
        .replace("^3", "3")
    )


def _length_to_mm(value: float, unit: str) -> float:
    normalized = _normalized_unit(unit)
    if normalized in {"mm", "毫米"}:
        return value
    if normalized in {"cm", "厘米"}:
        return value * 10.0
    if normalized in {"m", "米"}:
        return value * 1000.0
    raise ValueError(f"LLM 结构化参数包含不支持的长度单位: {unit}")


def _force_to_n(value: float, unit: str) -> float:
    normalized = _normalized_unit(unit)
    if normalized in {"n", "牛"}:
        return value
    if normalized in {"kn", "千牛"}:
        return value * 1000.0
    raise ValueError(f"LLM 结构化参数包含不支持的力单位: {unit}")


def _line_load_to_n_per_mm(value: float, unit: str) -> float:
    normalized = _normalized_unit(unit)
    if normalized in {"n/mm", "牛/毫米"}:
        return value
    if normalized in {"n/cm", "牛/厘米"}:
        return value / 10.0
    if normalized in {"n/m", "牛/米"}:
        return value / 1000.0
    if normalized in {"kn/mm", "千牛/毫米"}:
        return value * 1000.0
    if normalized in {"kn/cm", "千牛/厘米"}:
        return value * 100.0
    if normalized in {"kn/m", "千牛/米"}:
        return value
    raise ValueError(f"LLM 结构化参数包含不支持的线载荷单位: {unit}")


def _pressure_to_mpa(value: float, unit: str) -> float:
    normalized = _normalized_unit(unit)
    if normalized in {"mpa", "n/mm2", "n/平方毫米", "兆帕"}:
        return value
    if normalized in {"gpa", "吉帕"}:
        return value * 1000.0
    if normalized in {"kpa", "千帕"}:
        return value * 0.001
    if normalized in {"pa", "帕"}:
        return value * 1.0e-6
    if normalized in {"n/cm2", "n/平方厘米"}:
        return value * 0.01
    if normalized in {"n/m2", "n/平方米"}:
        return value * 1.0e-6
    if normalized in {"kn/m2", "kn/平方米"}:
        return value * 0.001
    raise ValueError(f"LLM 结构化参数包含不支持的压力或模量单位: {unit}")


def _density_to_tonne_per_mm3(value: float, unit: str) -> float:
    normalized = _normalized_unit(unit)
    if normalized in {"tonne/mm3", "ton/mm3", "t/mm3", "吨/mm3", "吨/毫米3"}:
        return value
    if normalized in {"tonne/m3", "ton/m3", "t/m3", "吨/m3", "吨/米3"}:
        return value * 1.0e-9
    if normalized in {"kg/mm3", "千克/mm3", "千克/毫米3"}:
        return value * 0.001
    if normalized in {"kg/m3", "千克/m3", "千克/米3"}:
        return value * 1.0e-12
    if normalized in {"g/cm3", "克/cm3", "克/厘米3"}:
        return value * 1.0e-9
    raise ValueError(f"LLM 结构化参数包含不支持的密度单位: {unit}")


def _first_present_number(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _coerce_numeric_item(value: Any) -> Any:
    number = _numeric_value(value)
    return number if number is not None else value


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = _normalized_token(value)
        if text in {
            "true",
            "yes",
            "1",
            "on",
            "nonlinear",
            "non_linear",
            "geometrically_nonlinear",
            "large_deformation",
            "large_strain",
            "nlgeom",
        }:
            return True
        if text in {
            "false",
            "no",
            "0",
            "off",
            "",
            "linear",
            "linear_static",
            "geometrically_linear",
            "small_deformation",
            "small_strain",
        }:
            return False
    return False


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _object_list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _trace_with_error(trace: AgentLLMTrace, error: str) -> AgentLLMTrace:
    return trace.model_copy(update={"error": error})


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "unsupported"}:
        return None
    return text


def _capability_id_value(
    value: Any,
    capability_by_id: dict[str, SimulationCapability],
) -> Optional[str]:
    text = _optional_str(value)
    if text is None:
        return None
    candidates = (
        text,
        text.lower(),
        _normalized_token(text),
    )
    for candidate in candidates:
        if candidate in capability_by_id:
            return candidate
    raise_value = text
    msg = f"LLM 返回未注册能力: {raise_value}"
    raise ValueError(msg)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[、,，;；\n]+", value) if item.strip()]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _confidence(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return max(0.0, min(number, 1.0)) if math.isfinite(number) else 0.75
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return 0.75
        return max(0.0, min(number, 1.0)) if math.isfinite(number) else 0.75
    return 0.75

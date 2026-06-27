"""结构静力自然语言解析器。"""

from __future__ import annotations

import re
from typing import Optional

from mechagent.core.cad import GeometryCandidate
from mechagent.core.materials import match_builtin_material
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

_NUMBER = r"[-+]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:e[-+]?\d+)?"
_LENGTH_UNITS = "毫米|厘米|米|mm|cm|m"
_FORCE_UNITS = "千牛|牛|kn|n"
_DIMENSION_SEPARATOR = r"[xX×*]"
_PLATE_KEYWORDS = "矩形薄板|矩形板|薄板|板|plate"
_SOLID_KEYWORDS = "长方体|矩形体|实体|块体|solid|block|prism"
_PRESSURE_UNITS = (
    r"n\s*/\s*mm(?:\^?2|²)|n\s*/\s*cm(?:\^?2|²)|n\s*/\s*m(?:\^?2|²)|"
    r"kn\s*/\s*m(?:\^?2|²)|n\s*/\s*平方毫米|n\s*/\s*平方厘米|"
    r"n\s*/\s*平方米|kn\s*/\s*平方米|mpa|kpa|pa|兆帕|千帕|帕"
)


def looks_like_static_request(request: str) -> bool:
    """判断请求是否属于结构静力分析。

    Args:
        request: 用户自然语言请求。

    Returns:
        bool: 属于结构静力分析时返回 True。

    Raises:
        无。

    Example:
        >>> looks_like_static_request("长1000mm 的悬臂梁静力分析")
        True
    """

    text = _normalized(request)
    has_static = any(
        keyword in request
        for keyword in (
            "静力",
            "受力",
            "载荷",
            "荷载",
            "受压",
            "受拉",
            "均布",
            "压力",
            "固支",
            "简支",
            "固定",
            "挠度",
            "位移",
            "应力",
            "应变",
            "变形",
        )
    )
    has_static = has_static or any(
        keyword in text
        for keyword in (
            "static",
            "load",
            "force",
            "deflection",
            "displacement",
            "stress",
            "strain",
            "deformation",
        )
    )
    has_static = has_static or _extract_line_load(request) is not None
    has_static = has_static or _extract_point_force(request) is not None
    has_static = has_static or _extract_pressure(request) is not None
    has_geometry = bool(_detect_geometry_types(request))
    has_action = any(
        keyword in request
        for keyword in (
            "求",
            "求解",
            "分析",
            "计算",
            "仿真",
            "输出",
            "给出",
            "报告",
            "评估",
            "校核",
        )
    )
    has_action = has_action or any(
        keyword in text
        for keyword in (
            "solve",
            "analyze",
            "simulate",
            "compute",
            "calculate",
            "report",
            "evaluate",
        )
    )
    return has_static and (has_geometry or has_action)


def parse_static_model_params(request: str) -> ModelParams:
    """将结构静力自然语言请求转换为结构化仿真参数。

    Args:
        request: 用户自然语言请求。

    Returns:
        ModelParams: 可传递给网格器和求解器的结构化参数。

    Raises:
        ValueError: 当请求不属于结构静力分析或缺少必要参数时抛出。

    Example:
        >>> params = parse_static_model_params(
        ...     "长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，向下1000N"
        ... )
        >>> params.geometry.type.value
        'beam'
    """

    if not looks_like_static_request(request):
        msg = "自然语言入口支持结构静力分析请求。"
        raise ValueError(msg)

    geometry_types = _detect_geometry_types(request)
    if len(geometry_types) > 1:
        msg = (
            "结构静力分析请求包含多个几何类型: "
            f"{'、'.join(_geometry_type_label(item) for item in geometry_types)}。"
            "请拆分为单个仿真任务，或用分号、句号、换行分隔多个完整任务。"
        )
        raise ValueError(msg)

    geometry_type = geometry_types[0] if geometry_types else None
    if geometry_type is GeometryType.BEAM:
        return parse_static_beam_model_params(request)
    if geometry_type is GeometryType.PLATE:
        return parse_static_plate_model_params(request)
    if geometry_type is GeometryType.SOLID:
        return parse_static_solid_model_params(request)

    msg = "结构静力分析缺少必要参数: 几何类型。"
    raise ValueError(msg)


def build_static_request_from_geometry(candidate: GeometryCandidate, completion: str) -> str:
    """由 CAD 几何候选与自然语言补全合成结构静力请求。

    把几何候选的包围盒尺寸按几何类型重新解释（梁取最长边为长度、其余两边为截面；板取最薄边为厚度；
    实体取长宽高），与用户补全的材料、载荷与边界文本拼接为完整自然语言请求，复用既有结构静力解析器。

    Args:
        candidate: 由 CAD 几何摘要派生的几何候选。
        completion: 描述材料、载荷与边界的自然语言补全。

    Returns:
        str: 可由 `parse_static_model_params` 解析的结构静力请求。

    Raises:
        ValueError: 当几何类型不支持 CAD 到求解链路或补全为空时抛出。

    Example:
        >>> request = build_static_request_from_geometry(candidate, "材料钢，一端固支，端部1000N")
        >>> "悬臂梁" in request
        True
    """

    ordered = sorted(candidate.dimensions.values(), reverse=True)
    if len(ordered) < 3:
        msg = "几何候选尺寸不足以合成求解请求。"
        raise ValueError(msg)
    large = _format_length(ordered[0])
    mid = _format_length(ordered[1])
    small = _format_length(ordered[2])
    completion_text = completion.strip().rstrip("。.，,")
    if not completion_text:
        msg = "缺少材料、载荷与边界的自然语言补全。"
        raise ValueError(msg)

    if candidate.geometry_type is GeometryType.BEAM:
        phrase = f"长{large}mm、截面{mid}mmx{small}mm的悬臂梁"
    elif candidate.geometry_type is GeometryType.PLATE:
        phrase = f"长{large}mm、宽{mid}mm、厚{small}mm的矩形板"
    elif candidate.geometry_type is GeometryType.SOLID:
        phrase = f"长方体实体{large}mmx{mid}mmx{small}mm"
    else:
        msg = f"几何类型 {candidate.geometry_type.value} 暂不支持 CAD 到求解链路。"
        raise ValueError(msg)

    request = f"{phrase}，{completion_text}"
    if not any(keyword in request for keyword in ("分析", "求解", "求")):
        request = f"{request}静力分析"
    return request


def parse_static_model_params_from_geometry(
    candidate: GeometryCandidate, completion: str
) -> ModelParams:
    """将 CAD 几何候选与自然语言补全合并解析为结构化仿真参数。

    Args:
        candidate: 由 CAD 几何摘要派生的几何候选。
        completion: 描述材料、载荷与边界的自然语言补全。

    Returns:
        ModelParams: 可传递给网格器和求解器的结构化参数，`metadata.geometry_source` 标记为 ``cad``。

    Raises:
        ValueError: 当合成请求缺少必要仿真参数或几何类型不支持时抛出。
    """

    request = build_static_request_from_geometry(candidate, completion)
    params = parse_static_model_params(request)
    return params.model_copy(update={"metadata": {**params.metadata, "geometry_source": "cad"}})


def _format_length(value: float) -> str:
    return f"{value:g}"


def detect_static_geometry_type(request: str) -> Optional[str]:
    """识别结构静力请求中的几何类型。

    Args:
        request: 用户自然语言请求。

    Returns:
        Optional[str]: 识别到的几何类型，未识别时返回 None。

    Raises:
        无。

    Example:
        >>> detect_static_geometry_type("矩形板静力分析")
        'plate'
    """

    geometry_type = _detect_geometry_type(request)
    return geometry_type.value if geometry_type is not None else None


def split_static_simulation_requests(request: str) -> tuple[str, ...]:
    """将复合结构静力请求拆分为多个单一仿真请求。

    Args:
        request: 用户自然语言请求。

    Returns:
        tuple[str, ...]: 每个元素对应一个可独立解析的结构静力请求。

    Raises:
        无。

    Example:
        >>> split_static_simulation_requests("梁长1000mm，端部1000N；矩形板300mmx200mmx5mm")
        ('梁长1000mm，端部1000N', '矩形板300mmx200mmx5mm')
    """

    segments = _split_request_clauses(request)
    executable_segments = tuple(
        segment
        for segment in segments
        if _detect_geometry_type(segment) is not None and looks_like_static_request(segment)
    )
    if len(executable_segments) >= 2:
        return executable_segments
    return (request.strip(),)


def detect_static_missing_fields(request: str) -> list[str]:
    """识别结构静力请求缺少的必要字段。

    Args:
        request: 用户自然语言请求。

    Returns:
        list[str]: 缺少字段名称。

    Raises:
        无。

    Example:
        >>> detect_static_missing_fields("悬臂梁一端固支，端部向下1000N")
        ['梁长', '矩形截面尺寸', '材料']
    """

    geometry_types = _detect_geometry_types(request)
    if len(geometry_types) > 1:
        return ["单一几何类型"]

    geometry_type = geometry_types[0] if geometry_types else None
    if geometry_type is GeometryType.BEAM:
        return _missing_beam_fields(request)
    if geometry_type is GeometryType.PLATE:
        return _missing_plate_fields(request)
    if geometry_type is GeometryType.SOLID:
        return _missing_solid_fields(request)
    return ["几何类型"]


def parse_static_beam_model_params(request: str) -> ModelParams:
    """将静力梁自然语言请求转换为结构化仿真参数。

    Args:
        request: 用户自然语言请求，需包含梁长、矩形截面、材料、固支边界和载荷。

    Returns:
        ModelParams: 可传递给网格器和求解器的结构化参数。

    Raises:
        ValueError: 当请求缺少必要仿真参数或能力不支持时抛出。

    Example:
        >>> params = parse_static_beam_model_params(
        ...     "长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，向下50kN/m"
        ... )
        >>> params.loads[0].type.value
        'line_load'
    """

    if _detect_geometry_type(request) is not GeometryType.BEAM:
        msg = "自然语言解析器支持结构静力梁分析请求。"
        raise ValueError(msg)

    missing = _missing_beam_fields(request)
    length = _extract_named_length(request, ("梁长", "长度", "长", "length", "l"))
    section = _extract_rectangular_section(request)
    material = _extract_material(request)
    load = _extract_load(request)

    if missing:
        msg = f"静力梁分析缺少必要参数: {'、'.join(missing)}。"
        raise ValueError(msg)

    assert length is not None
    assert section is not None
    assert material is not None
    assert load is not None

    width, height = section
    load_case = (
        "cantilever_uniform_line_load"
        if load.type is LoadType.LINE_LOAD
        else "cantilever_tip_force"
    )
    return ModelParams(
        geometry=GeometrySpec(
            type=GeometryType.BEAM,
            dimensions={"length": length, "width": width, "height": height},
        ),
        material=material,
        loads=[load],
        bcs=[
            BCSpec(
                type=BCType.FIXED,
                region="root",
                dofs=["ux", "uy", "uz", "rx", "ry", "rz"],
                values=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
        ],
        mesh=MeshSpec(element_type=ElementType.B31, seed_size=max(length / 100.0, 1.0)),
        analysis=AnalysisSpec(type=AnalysisType.STATIC, nlgeom=False),
        case_id="STATIC-BEAM",
        load_case=load_case,
        metadata={
            "source": "natural_language",
            "raw_request": request,
        },
    )


def parse_static_plate_model_params(request: str) -> ModelParams:
    """将静力板自然语言请求转换为结构化仿真参数。

    Args:
        request: 用户自然语言请求，需包含板长、板宽、板厚、材料、支承和面载荷。

    Returns:
        ModelParams: 可传递给网格器和求解器的结构化参数。

    Raises:
        ValueError: 当请求缺少必要仿真参数或能力不支持时抛出。

    Example:
        >>> params = parse_static_plate_model_params(
        ...     "长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力"
        ... )
        >>> params.geometry.type.value
        'plate'
    """

    if _detect_geometry_type(request) is not GeometryType.PLATE:
        msg = "自然语言解析器支持结构静力板分析请求。"
        raise ValueError(msg)

    missing = _missing_plate_fields(request)
    dimensions = _extract_plate_dimensions(request)
    material = _extract_material(request)
    pressure = _extract_pressure(request)

    if missing:
        msg = f"静力板分析缺少必要参数: {'、'.join(missing)}。"
        raise ValueError(msg)

    assert dimensions is not None
    assert material is not None
    assert pressure is not None

    length = dimensions["length"]
    width = dimensions["width"]
    load_case = (
        "perforated_plate_pressure"
        if _is_perforated_plate_dimensions(dimensions)
        else "simply_supported_pressure"
    )
    seed_size = _plate_seed_size(length, width, dimensions)
    return ModelParams(
        geometry=GeometrySpec(type=GeometryType.PLATE, dimensions=dimensions),
        material=material,
        loads=[
            LoadSpec(
                type=LoadType.PRESSURE,
                magnitude=pressure,
                region="top_surface",
                direction=_extract_plate_direction(request),
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
        mesh=MeshSpec(element_type=ElementType.S4, seed_size=seed_size),
        analysis=AnalysisSpec(type=AnalysisType.STATIC, nlgeom=False),
        case_id="STATIC-PERFORATED-PLATE"
        if load_case == "perforated_plate_pressure"
        else "STATIC-PLATE",
        load_case=load_case,
        metadata={
            "source": "natural_language",
            "raw_request": request,
        },
    )


def parse_static_solid_model_params(request: str) -> ModelParams:
    """将静力实体块自然语言请求转换为结构化仿真参数。

    Args:
        request: 用户自然语言请求，需包含长宽高、材料、固定端和端面载荷。

    Returns:
        ModelParams: 可传递给网格器和求解器的结构化参数。

    Raises:
        ValueError: 当请求缺少必要仿真参数或能力不支持时抛出。

    Example:
        >>> params = parse_static_solid_model_params(
        ...     "长方体实体100mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
        ... )
        >>> params.geometry.type.value
        'solid'
    """

    if _detect_geometry_type(request) is not GeometryType.SOLID:
        msg = "自然语言解析器支持结构静力实体块分析请求。"
        raise ValueError(msg)

    missing = _missing_solid_fields(request)
    dimensions = _extract_solid_dimensions(request)
    material = _extract_material(request)
    load = _extract_solid_load(request)

    if missing:
        msg = f"静力实体分析缺少必要参数: {'、'.join(missing)}。"
        raise ValueError(msg)

    assert dimensions is not None
    assert material is not None
    assert load is not None

    length = dimensions["length"]
    width = dimensions["width"]
    height = dimensions["height"]
    seed_size = max(min(length, width, height) / 2.0, 1.0)
    load_case = (
        "fixed_solid_axial_pressure"
        if load.type is LoadType.PRESSURE
        else "fixed_solid_axial_force"
    )
    return ModelParams(
        geometry=GeometrySpec(type=GeometryType.SOLID, dimensions=dimensions),
        material=material,
        loads=[load],
        bcs=[
            BCSpec(
                type=BCType.FIXED,
                region="root",
                dofs=["ux", "uy", "uz"],
                values=[0.0, 0.0, 0.0],
            )
        ],
        mesh=MeshSpec(element_type=ElementType.C3D8R, seed_size=seed_size),
        analysis=AnalysisSpec(type=AnalysisType.STATIC, nlgeom=False),
        case_id="STATIC-SOLID",
        load_case=load_case,
        metadata={
            "source": "natural_language",
            "raw_request": request,
        },
    )


def _detect_geometry_type(request: str) -> Optional[GeometryType]:
    geometry_types = _detect_geometry_types(request)
    if len(geometry_types) == 1:
        return geometry_types[0]
    return None


def _detect_geometry_types(request: str) -> tuple[GeometryType, ...]:
    text = _normalized(request)
    geometry_types: list[GeometryType] = []
    if any(keyword in request for keyword in ("实体", "块体", "长方体", "矩形体")) or any(
        keyword in text for keyword in ("solid", "block", "prism")
    ):
        geometry_types.append(GeometryType.SOLID)
    if any(keyword in request for keyword in ("板", "薄板", "矩形板")) or "plate" in text:
        geometry_types.append(GeometryType.PLATE)
    if any(keyword in request for keyword in ("梁", "悬臂梁")) or "beam" in text:
        geometry_types.append(GeometryType.BEAM)
    return tuple(geometry_types)


def _geometry_type_label(geometry_type: GeometryType) -> str:
    labels = {
        GeometryType.BEAM: "梁",
        GeometryType.PLATE: "板",
        GeometryType.SOLID: "实体",
    }
    return labels.get(geometry_type, geometry_type.value)


def _split_request_clauses(request: str) -> tuple[str, ...]:
    return tuple(
        segment.strip(" \t\r\n:：,，")
        for segment in re.split(r"[；;\n。]+", request)
        if segment.strip(" \t\r\n:：,，")
    )


def _missing_beam_fields(request: str) -> list[str]:
    missing: list[str] = []
    if _extract_named_length(request, ("梁长", "长度", "长", "length", "l")) is None:
        missing.append("梁长")
    if _extract_rectangular_section(request) is None:
        missing.append("矩形截面尺寸")
    if _extract_material(request) is None:
        missing.append("材料")
    if not _has_fixed_root(request):
        missing.append("固支边界")
    load = _extract_load(request)
    if load is None:
        missing.append("载荷")
    elif not _has_beam_load_direction(request):
        missing.append("载荷方向")
    return missing


def _missing_plate_fields(request: str) -> list[str]:
    missing: list[str] = []
    dimensions = _extract_plate_dimensions(request)
    if dimensions is None:
        missing.append("板长、板宽和板厚")
    if (
        _has_circular_hole(request)
        and dimensions is not None
        and not _is_perforated_plate_dimensions(dimensions)
    ):
        missing.append("圆孔直径或半径")
    if (
        _has_plate_slot(request)
        and dimensions is not None
        and not _is_slotted_plate_dimensions(dimensions)
    ):
        missing.append("槽孔长度和宽度")
    if _extract_material(request) is None:
        missing.append("材料")
    if not _has_simple_support(request):
        missing.append("支承边界")
    if _extract_pressure(request) is None:
        missing.append("面载荷")
    return missing


def _missing_solid_fields(request: str) -> list[str]:
    missing: list[str] = []
    if _extract_solid_dimensions(request) is None:
        missing.append("实体长、宽和高")
    if _extract_material(request) is None:
        missing.append("材料")
    if not _has_fixed_root(request):
        missing.append("固定边界")
    load = _extract_solid_load(request)
    if load is None:
        missing.append("端面载荷")
    elif not _has_solid_load_direction(request):
        missing.append("端面载荷方向")
    return missing


def _normalized(text: str) -> str:
    return text.strip().lower().replace("×", "x").replace("，", ",")


def _extract_named_length(text: str, names: tuple[str, ...]) -> Optional[float]:
    name_pattern = "|".join(re.escape(name) for name in names)
    pattern = re.compile(
        rf"(?:{name_pattern})\s*(?:为|是|=|:|：)?\s*({_NUMBER})\s*({_LENGTH_UNITS})",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None
    return _length_to_mm(float(match.group(1)), match.group(2))


def _extract_rectangular_section(text: str) -> Optional[tuple[float, float]]:
    section_pattern = re.compile(
        rf"(?:截面(?:尺寸)?|section)\s*(?:为|是|=|:|：)?\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*{_DIMENSION_SEPARATOR}\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?",
        re.IGNORECASE,
    )
    section_match = section_pattern.search(text)
    if section_match is not None:
        width_unit = section_match.group(2) or section_match.group(4) or "mm"
        height_unit = section_match.group(4) or section_match.group(2) or "mm"
        width = _length_to_mm(float(section_match.group(1)), width_unit)
        height = _length_to_mm(float(section_match.group(3)), height_unit)
        return (width, height)

    width_value = _extract_named_length(
        text,
        ("截面宽度", "截面宽", "宽度", "宽", "section width", "width", "w"),
    )
    height_value = _extract_named_length(
        text,
        ("截面高度", "截面高", "高度", "高", "section height", "height", "h"),
    )
    if width_value is None or height_value is None:
        return None
    return (width_value, height_value)


def _extract_plate_dimensions(text: str) -> Optional[dict[str, float]]:
    compact_pattern = re.compile(
        rf"(?:{_PLATE_KEYWORDS})[^0-9]{{0,20}}"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*{_DIMENSION_SEPARATOR}\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*{_DIMENSION_SEPARATOR}\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?",
        re.IGNORECASE,
    )
    match = compact_pattern.search(text)
    if match is not None:
        length, width, thickness = _extract_dimension_triplet(match)
        return _with_plate_features(
            text,
            {
                "length": length,
                "width": width,
                "thickness": thickness,
            },
        )

    trailing_compact_pattern = re.compile(
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*{_DIMENSION_SEPARATOR}\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*{_DIMENSION_SEPARATOR}\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*(?:的|de)?\s*(?:{_PLATE_KEYWORDS})",
        re.IGNORECASE,
    )
    match = trailing_compact_pattern.search(text)
    if match is not None:
        length, width, thickness = _extract_dimension_triplet(match)
        return _with_plate_features(
            text,
            {
                "length": length,
                "width": width,
                "thickness": thickness,
            },
        )

    named_length = _extract_named_length(text, ("板长", "长度", "长", "length", "l"))
    named_width = _extract_named_length(text, ("板宽", "宽度", "宽", "width", "b"))
    named_thickness = _extract_named_length(text, ("板厚", "厚度", "厚", "thickness", "t"))
    if named_length is None or named_width is None or named_thickness is None:
        return None
    return _with_plate_features(
        text,
        {"length": named_length, "width": named_width, "thickness": named_thickness},
    )


def _with_plate_features(text: str, dimensions: dict[str, float]) -> dict[str, float]:
    enriched = dict(dimensions)
    holes = _extract_plate_holes(text, dimensions["length"], dimensions["width"])
    if holes:
        first_radius, first_center_x, first_center_y = holes[0]
        enriched.update(
            {
                "hole_count": float(len(holes)),
                "hole_radius": first_radius,
                "hole_center_x": first_center_x,
                "hole_center_y": first_center_y,
            }
        )
        for index, (radius, center_x, center_y) in enumerate(holes, start=1):
            enriched[f"hole_{index}_radius"] = radius
            enriched[f"hole_{index}_center_x"] = center_x
            enriched[f"hole_{index}_center_y"] = center_y
    slot = _extract_plate_slot(text, dimensions["length"], dimensions["width"])
    if slot is not None:
        slot_length, slot_width, slot_center_x, slot_center_y = slot
        enriched.update(
            {
                "slot_count": 1.0,
                "slot_length": slot_length,
                "slot_width": slot_width,
                "slot_center_x": slot_center_x,
                "slot_center_y": slot_center_y,
                "slot_1_length": slot_length,
                "slot_1_width": slot_width,
                "slot_1_center_x": slot_center_x,
                "slot_1_center_y": slot_center_y,
            }
        )
    return enriched


def _has_circular_hole(text: str) -> bool:
    normalized = _normalized(text)
    return any(
        keyword in text for keyword in ("圆孔", "开孔", "孔径", "孔半径", "中心孔", "带孔", "多孔")
    ) or any(keyword in normalized for keyword in ("hole", "perforated", "circular opening"))


def _has_plate_slot(text: str) -> bool:
    normalized = _normalized(text)
    return any(
        keyword in text for keyword in ("槽孔", "长圆孔", "长圆槽孔", "腰型孔", "槽长", "槽宽")
    ) or any(
        keyword in normalized for keyword in ("slot", "slotted hole", "obround", "rounded slot")
    )


def _extract_plate_holes(
    text: str,
    length: float,
    width: float,
) -> tuple[tuple[float, float, float], ...]:
    if re.search(r"(?:孔|hole)\s*\d+", text, flags=re.IGNORECASE):
        return _extract_indexed_holes(text)

    hole_radius = _extract_hole_radius(text)
    if hole_radius is None:
        return ()
    center_x, center_y = _extract_hole_center(text, length, width)
    return ((hole_radius, center_x, center_y),)


def _extract_indexed_holes(text: str) -> tuple[tuple[float, float, float], ...]:
    markers = tuple(re.finditer(r"(?:孔|hole)\s*\d+", text, flags=re.IGNORECASE))
    holes: list[tuple[float, float, float]] = []
    for marker_index, marker in enumerate(markers):
        next_start = (
            markers[marker_index + 1].start() if marker_index + 1 < len(markers) else len(text)
        )
        segment = text[marker.start() : next_start]
        radius = _extract_hole_radius(segment)
        center_x = _extract_named_length(
            segment,
            ("孔中心x", "孔心x", "中心x", "hole center x", "center x", "hole_center_x", "x"),
        )
        center_y = _extract_named_length(
            segment,
            ("孔中心y", "孔心y", "中心y", "hole center y", "center y", "hole_center_y", "y"),
        )
        if radius is None or center_x is None or center_y is None:
            return ()
        holes.append((radius, center_x, center_y))
    return tuple(holes)


def _extract_hole_radius(text: str) -> Optional[float]:
    diameter_pattern = re.compile(
        rf"(?:孔径|孔直径|圆孔直径|hole\s*diameter|diameter)\s*(?:为|是|=|:|：)?\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})",
        re.IGNORECASE,
    )
    match = diameter_pattern.search(text)
    if match is not None:
        return _length_to_mm(float(match.group(1)), match.group(2)) / 2.0

    radius_pattern = re.compile(
        rf"(?:孔半径|圆孔半径|hole\s*radius|radius)\s*(?:为|是|=|:|：)?\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})",
        re.IGNORECASE,
    )
    match = radius_pattern.search(text)
    if match is not None:
        return _length_to_mm(float(match.group(1)), match.group(2))
    return None


def _extract_hole_center(text: str, length: float, width: float) -> tuple[float, float]:
    x_value = _extract_named_length(text, ("孔中心x", "孔心x", "hole center x", "hole_center_x"))
    y_value = _extract_named_length(text, ("孔中心y", "孔心y", "hole center y", "hole_center_y"))
    if x_value is not None and y_value is not None:
        return (x_value, y_value)
    return (length / 2.0, width / 2.0)


def _extract_plate_slot(
    text: str,
    length: float,
    width: float,
) -> Optional[tuple[float, float, float, float]]:
    if not _has_plate_slot(text):
        return None

    slot_length = _extract_named_length(
        text,
        (
            "槽孔长度",
            "槽孔长",
            "槽长",
            "长圆孔长度",
            "长圆孔长",
            "长圆槽孔长度",
            "长圆槽孔长",
            "腰型孔长度",
            "腰型孔长",
            "slot length",
            "slot_length",
            "obround length",
        ),
    )
    slot_width = _extract_named_length(
        text,
        (
            "槽孔宽度",
            "槽孔宽",
            "槽宽",
            "长圆孔宽度",
            "长圆孔宽",
            "长圆槽孔宽度",
            "长圆槽孔宽",
            "腰型孔宽度",
            "腰型孔宽",
            "slot width",
            "slot_width",
            "obround width",
        ),
    )
    if slot_length is None or slot_width is None:
        compact = _extract_compact_slot_size(text)
        if compact is not None:
            slot_length = slot_length if slot_length is not None else compact[0]
            slot_width = slot_width if slot_width is not None else compact[1]
    if slot_length is None or slot_width is None:
        return None

    center_x, center_y = _extract_slot_center(text, length, width)
    return (slot_length, slot_width, center_x, center_y)


def _extract_compact_slot_size(text: str) -> Optional[tuple[float, float]]:
    named_pair_pattern = re.compile(
        rf"(?:槽孔|长圆孔|长圆槽孔|腰型孔|slot|slotted\s+hole|obround)[^0-9]{{0,30}}"
        rf"(?:长|长度|槽长|槽孔长|槽孔长度|长圆孔长|长圆孔长度|长圆槽孔长|长圆槽孔长度|"
        rf"slot\s+length|slot_length|obround\s+length)\s*(?:为|是|=|:|：)?\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?[^0-9]{{0,20}}"
        rf"(?:宽|宽度|槽宽|槽孔宽|槽孔宽度|长圆孔宽|长圆孔宽度|长圆槽孔宽|长圆槽孔宽度|"
        rf"slot\s+width|slot_width|obround\s+width)\s*(?:为|是|=|:|：)?\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?",
        re.IGNORECASE,
    )
    match = named_pair_pattern.search(text)
    if match is not None:
        length_unit = match.group(2) or match.group(4) or "mm"
        width_unit = match.group(4) or match.group(2) or "mm"
        return (
            _length_to_mm(float(match.group(1)), length_unit),
            _length_to_mm(float(match.group(3)), width_unit),
        )

    pattern = re.compile(
        rf"(?:槽孔|长圆孔|长圆槽孔|腰型孔|slot|slotted\s+hole|obround)[^0-9]{{0,20}}"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*{_DIMENSION_SEPARATOR}\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None
    length_unit = match.group(2) or match.group(4) or "mm"
    width_unit = match.group(4) or match.group(2) or "mm"
    return (
        _length_to_mm(float(match.group(1)), length_unit),
        _length_to_mm(float(match.group(3)), width_unit),
    )


def _extract_slot_center(text: str, length: float, width: float) -> tuple[float, float]:
    x_value = _extract_named_length(
        text,
        (
            "槽孔中心x",
            "槽中心x",
            "长圆孔中心x",
            "长圆槽孔中心x",
            "slot center x",
            "slot_center_x",
        ),
    )
    y_value = _extract_named_length(
        text,
        (
            "槽孔中心y",
            "槽中心y",
            "长圆孔中心y",
            "长圆槽孔中心y",
            "slot center y",
            "slot_center_y",
        ),
    )
    if x_value is not None and y_value is not None:
        return (x_value, y_value)
    return (length / 2.0, width / 2.0)


def _is_perforated_plate_dimensions(dimensions: dict[str, float]) -> bool:
    return (
        "hole_radius" in dimensions
        or dimensions.get("hole_count", 0.0) >= 1.0
        or _is_slotted_plate_dimensions(dimensions)
    )


def _is_slotted_plate_dimensions(dimensions: dict[str, float]) -> bool:
    return "slot_length" in dimensions or dimensions.get("slot_count", 0.0) >= 1.0


def _plate_seed_size(length: float, width: float, dimensions: dict[str, float]) -> float:
    base = max(min(length, width) / 40.0, 1.0)
    hole_radii = _dimension_hole_radii(dimensions)
    if not hole_radii:
        return base
    return max(min(base, min(hole_radii) / 3.0), 0.75)


def _dimension_hole_radii(dimensions: dict[str, float]) -> tuple[float, ...]:
    hole_count = int(dimensions.get("hole_count", 0.0))
    radii = [
        radius
        for index in range(1, hole_count + 1)
        if (radius := dimensions.get(f"hole_{index}_radius")) is not None
    ]
    if (radius := dimensions.get("hole_radius")) is not None:
        radii.append(radius)
    slot_count = int(dimensions.get("slot_count", 0.0))
    for index in range(1, slot_count + 1):
        if (slot_width := dimensions.get(f"slot_{index}_width")) is not None:
            radii.append(slot_width / 2.0)
    if (slot_width := dimensions.get("slot_width")) is not None:
        radii.append(slot_width / 2.0)
    return tuple(radii)


def _extract_solid_dimensions(text: str) -> Optional[dict[str, float]]:
    compact_pattern = re.compile(
        rf"(?:{_SOLID_KEYWORDS})[^0-9]{{0,20}}"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*{_DIMENSION_SEPARATOR}\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*{_DIMENSION_SEPARATOR}\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?",
        re.IGNORECASE,
    )
    match = compact_pattern.search(text)
    if match is not None:
        length, width, height = _extract_dimension_triplet(match)
        return {
            "length": length,
            "width": width,
            "height": height,
        }

    trailing_compact_pattern = re.compile(
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*{_DIMENSION_SEPARATOR}\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*{_DIMENSION_SEPARATOR}\s*"
        rf"({_NUMBER})\s*({_LENGTH_UNITS})?\s*(?:的|de)?\s*(?:{_SOLID_KEYWORDS})",
        re.IGNORECASE,
    )
    match = trailing_compact_pattern.search(text)
    if match is not None:
        length, width, height = _extract_dimension_triplet(match)
        return {
            "length": length,
            "width": width,
            "height": height,
        }

    named_length = _extract_named_length(text, ("实体长", "块体长", "长度", "长", "length", "l"))
    named_width = _extract_named_length(text, ("实体宽", "块体宽", "宽度", "宽", "width", "b"))
    named_height = _extract_named_length(text, ("实体高", "块体高", "高度", "高", "height", "h"))
    if named_length is None or named_width is None or named_height is None:
        return None
    return {"length": named_length, "width": named_width, "height": named_height}


def _extract_dimension_triplet(match: re.Match[str]) -> tuple[float, float, float]:
    first_unit = match.group(2) or match.group(4) or match.group(6) or "mm"
    second_unit = match.group(4) or match.group(2) or match.group(6) or "mm"
    third_unit = match.group(6) or match.group(2) or match.group(4) or "mm"
    return (
        _length_to_mm(float(match.group(1)), first_unit),
        _length_to_mm(float(match.group(3)), second_unit),
        _length_to_mm(float(match.group(5)), third_unit),
    )


def _extract_material(text: str) -> Optional[MaterialSpec]:
    elastic_modulus = _extract_elastic_modulus(text)
    poisson_ratio = _extract_poisson_ratio(text)
    material = None if _has_unsupported_material_phrase(text) else match_builtin_material(text)

    if elastic_modulus is None and poisson_ratio is None:
        return material
    if material is None and (elastic_modulus is None or poisson_ratio is None):
        return None

    resolved_elastic_modulus = elastic_modulus
    resolved_poisson_ratio = poisson_ratio
    resolved_density = 1.0e-12
    if material is not None:
        if resolved_elastic_modulus is None:
            resolved_elastic_modulus = material.E
        if resolved_poisson_ratio is None:
            resolved_poisson_ratio = material.nu
        resolved_density = material.rho
    assert resolved_elastic_modulus is not None
    assert resolved_poisson_ratio is not None
    return MaterialSpec(
        E=resolved_elastic_modulus,
        nu=resolved_poisson_ratio,
        rho=resolved_density,
    )


def _has_unsupported_material_phrase(text: str) -> bool:
    normalized = _normalized(text)
    return any(
        phrase in text
        for phrase in (
            "钢筋混凝土",
            "混凝土",
            "复合材料",
            "碳纤维",
        )
    ) or any(
        phrase in normalized
        for phrase in (
            "reinforced concrete",
            "concrete",
            "composite",
            "carbon fiber",
            "carbon fibre",
        )
    )


def _extract_elastic_modulus(text: str) -> Optional[float]:
    pattern = re.compile(
        rf"(?:弹性模量|杨氏模量|young'?s modulus|\bE\b)\s*(?:为|是|=|:|：)?\s*"
        rf"({_NUMBER})\s*(gpa|mpa|n\s*/\s*mm(?:\^?2|²)|n\s*/\s*平方毫米|吉帕|兆帕)?",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None
    value = float(match.group(1))
    unit = match.group(2) or "mpa"
    normalized = unit.lower().replace(" ", "")
    if normalized in {"gpa", "吉帕"}:
        return value * 1000.0
    return value


def _extract_poisson_ratio(text: str) -> Optional[float]:
    pattern = re.compile(
        rf"(?:泊松比|poisson'?s ratio|nu|ν)\s*(?:为|是|=|:|：)?\s*({_NUMBER})",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None
    return float(match.group(1))


def _has_fixed_root(text: str) -> bool:
    normalized = _normalized(text)
    return any(keyword in text for keyword in ("固支", "固定", "夹持")) or any(
        keyword in normalized for keyword in ("fixed", "encastre", "cantilever")
    )


def _has_simple_support(text: str) -> bool:
    normalized = _normalized(text)
    return any(keyword in text for keyword in ("简支", "四边简支", "边界支承")) or any(
        keyword in normalized for keyword in ("simply supported", "simple support")
    )


def _has_beam_load_direction(text: str) -> bool:
    normalized = _normalized(text)
    return any(
        keyword in text
        for keyword in (
            "向上",
            "向下",
            "y正向",
            "y负向",
            "正y",
            "负y",
            "x向",
            "x 方向",
            "x方向",
            "z向",
            "z 方向",
            "z方向",
        )
    ) or any(
        keyword in normalized
        for keyword in (
            "upward",
            "downward",
            "positive y",
            "negative y",
            "positive x",
            "negative x",
            "positive z",
            "negative z",
        )
    )


def _has_solid_load_direction(text: str) -> bool:
    normalized = _normalized(text)
    return any(
        keyword in text
        for keyword in (
            "受压",
            "压缩",
            "受拉",
            "拉伸",
            "向左",
            "向右",
            "负x",
            "正x",
            "x负向",
            "x正向",
            "x向",
            "x 方向",
            "x方向",
        )
    ) or any(
        keyword in normalized
        for keyword in (
            "negative x",
            "positive x",
            "compression",
            "tension",
        )
    )


def _extract_load(text: str) -> Optional[LoadSpec]:
    direction = _extract_direction(text)
    line_load = _extract_line_load(text)
    if line_load is not None:
        return LoadSpec(
            type=LoadType.LINE_LOAD,
            magnitude=line_load,
            region="span",
            direction=direction,
        )

    point_force = _extract_point_force(text)
    if point_force is None:
        return None
    return LoadSpec(type=LoadType.FORCE, magnitude=point_force, region="tip", direction=direction)


def _extract_solid_load(text: str) -> Optional[LoadSpec]:
    direction = _extract_axial_direction(text)
    pressure = _extract_pressure(text)
    if pressure is not None:
        return LoadSpec(
            type=LoadType.PRESSURE,
            magnitude=pressure,
            region="end_face",
            direction=direction,
        )

    point_force = _extract_point_force(text)
    if point_force is None:
        return None
    return LoadSpec(
        type=LoadType.FORCE,
        magnitude=point_force,
        region="end_face",
        direction=direction,
    )


def _extract_direction(text: str) -> tuple[float, float, float]:
    normalized = _normalized(text)
    if "x向" in text or "x 方向" in text or "x方向" in text:
        return _extract_axial_direction(text)
    if "向上" in text or "y正向" in text or "正y" in text or "upward" in normalized:
        return (0.0, 1.0, 0.0)
    if "向下" in text or "y负向" in text or "负y" in text or "downward" in normalized:
        return (0.0, -1.0, 0.0)
    if "z向" in text or "z 方向" in text or "z方向" in text:
        return (0.0, 0.0, -1.0)
    return (0.0, -1.0, 0.0)


def _extract_plate_direction(text: str) -> tuple[float, float, float]:
    normalized = _normalized(text)
    if any(keyword in text for keyword in ("z正向", "正z", "向上")):
        return (0.0, 0.0, 1.0)
    if any(keyword in normalized for keyword in ("positive z", "upward")):
        return (0.0, 0.0, 1.0)
    if any(keyword in text for keyword in ("z负向", "负z", "向下")):
        return (0.0, 0.0, -1.0)
    if any(keyword in normalized for keyword in ("negative z", "downward")):
        return (0.0, 0.0, -1.0)
    return (0.0, 0.0, -1.0)


def _extract_axial_direction(text: str) -> tuple[float, float, float]:
    normalized = _normalized(text)
    if any(keyword in text for keyword in ("受压", "压缩", "向左", "负x", "x负向")):
        return (-1.0, 0.0, 0.0)
    if any(keyword in text for keyword in ("受拉", "拉伸", "向右", "正x", "x正向")):
        return (1.0, 0.0, 0.0)
    if "negative x" in normalized:
        return (-1.0, 0.0, 0.0)
    if "positive x" in normalized or "tension" in normalized:
        return (1.0, 0.0, 0.0)
    if "compression" in normalized:
        return (-1.0, 0.0, 0.0)
    return (1.0, 0.0, 0.0)


def _extract_line_load(text: str) -> Optional[float]:
    pattern = re.compile(
        rf"({_NUMBER})\s*({_FORCE_UNITS})\s*/\s*({_LENGTH_UNITS})(?![mM]|\s*(?:\^?2|²|平方))",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None
    force_n = abs(_force_to_n(float(match.group(1)), match.group(2)))
    length_mm = _length_to_mm(1.0, match.group(3))
    return force_n / length_mm


def _extract_point_force(text: str) -> Optional[float]:
    pattern = re.compile(rf"({_NUMBER})\s*({_FORCE_UNITS})(?!\s*/)", re.IGNORECASE)
    match = pattern.search(text)
    if match is None:
        return None
    return abs(_force_to_n(float(match.group(1)), match.group(2)))


def _extract_pressure(text: str) -> Optional[float]:
    pattern = re.compile(rf"({_NUMBER})\s*({_PRESSURE_UNITS})", re.IGNORECASE)
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 12) : match.start()].lower()
        if any(keyword in prefix for keyword in ("弹性模量", "杨氏模量", "young")):
            continue
        if re.search(r"\bE\s*(?:=|:|：)?\s*$", prefix, flags=re.IGNORECASE):
            continue
        return abs(_pressure_to_mpa(float(match.group(1)), match.group(2)))
    return None


def _length_to_mm(value: float, unit: str) -> float:
    normalized = unit.lower()
    if normalized in {"mm", "毫米"}:
        return value
    if normalized in {"cm", "厘米"}:
        return value * 10.0
    if normalized in {"m", "米"}:
        return value * 1000.0
    msg = f"不支持的长度单位: {unit}"
    raise ValueError(msg)


def _force_to_n(value: float, unit: str) -> float:
    normalized = unit.lower()
    if normalized in {"n", "牛"}:
        return value
    if normalized in {"kn", "千牛"}:
        return value * 1000.0
    msg = f"不支持的力单位: {unit}"
    raise ValueError(msg)


def _pressure_to_mpa(value: float, unit: str) -> float:
    normalized = unit.lower().replace(" ", "").replace("²", "2").replace("^2", "2")
    if normalized in {"n/mm2", "n/mm^2", "n/mm²", "n/平方毫米", "mpa", "兆帕"}:
        return value
    if normalized in {"n/cm2", "n/平方厘米"}:
        return value * 0.01
    if normalized in {"n/m2", "n/平方米"}:
        return value * 1.0e-6
    if normalized in {"kn/m2", "kn/平方米"}:
        return value * 0.001
    if normalized in {"kpa", "千帕"}:
        return value * 0.001
    if normalized in {"pa", "帕"}:
        return value * 1.0e-6
    msg = f"不支持的压力单位: {unit}"
    raise ValueError(msg)

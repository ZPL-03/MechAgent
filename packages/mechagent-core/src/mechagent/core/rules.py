"""仿真参数工程规则检查。"""

from __future__ import annotations

from dataclasses import dataclass

from mechagent.core.models import (
    AnalysisType,
    BCType,
    ElementType,
    GeometryType,
    LoadSpec,
    LoadType,
    MaterialType,
    ModelParams,
)


@dataclass(frozen=True)
class RuleViolation:
    """工程规则违规项。

    Args:
        field: 字段路径。
        value: 实际值。
        message: 违规说明。

    Returns:
        RuleViolation: 规则违规项。

    Raises:
        TypeError: 当字段类型不匹配时由 dataclass 构造阶段抛出。

    Example:
        >>> RuleViolation("geometry.length", 1.0, "too small").field
        'geometry.length'
    """

    field: str
    value: float
    message: str


_GEOMETRY_RANGES = {
    GeometryType.BEAM: {
        "length": (10.0, 10000.0),
        "width": (1.0, 1000.0),
        "height": (1.0, 1000.0),
    },
    GeometryType.PLATE: {
        "length": (10.0, 10000.0),
        "width": (10.0, 10000.0),
        "thickness": (0.1, 500.0),
    },
    GeometryType.SOLID: {
        "length": (1.0, 10000.0),
        "width": (1.0, 10000.0),
        "height": (1.0, 10000.0),
    },
}


def check_parameter_ranges(model_params: ModelParams) -> list[RuleViolation]:
    """检查仿真参数是否落在工程规则范围内。

    Args:
        model_params: 结构化仿真参数。

    Returns:
        list[RuleViolation]: 规则违规列表。

    Raises:
        无。

    Example:
        >>> from mechagent.core.validation import tc01_model_params
        >>> check_parameter_ranges(tc01_model_params())
        []
    """

    violations: list[RuleViolation] = []
    geometry_ranges = _GEOMETRY_RANGES.get(model_params.geometry.type, {})
    for name, (lower, upper) in geometry_ranges.items():
        value = model_params.geometry.dimensions.get(name)
        if value is None:
            continue
        if value < lower or value > upper:
            violations.append(
                RuleViolation(
                    field=f"geometry.dimensions.{name}",
                    value=value,
                    message=f"应位于 {lower:g} 至 {upper:g} mm。",
                )
            )
    _check_mesh_size(model_params, violations)
    return violations


def ensure_parameter_ranges(model_params: ModelParams) -> None:
    """检查参数范围并在违规时抛出异常。

    Args:
        model_params: 结构化仿真参数。

    Returns:
        无。

    Raises:
        ValueError: 当存在工程规则违规项时抛出。

    Example:
        >>> from mechagent.core.validation import tc01_model_params
        >>> ensure_parameter_ranges(tc01_model_params())
    """

    violations = check_parameter_ranges(model_params)
    if not violations:
        return
    detail = "；".join(
        f"{violation.field}={violation.value:g}: {violation.message}" for violation in violations
    )
    msg = f"仿真参数超出工程规则范围: {detail}"
    raise ValueError(msg)


def check_static_execution_contract(model_params: ModelParams) -> list[RuleViolation]:
    """检查内置结构静力执行路径支持的模型组合。

    Args:
        model_params: 结构化仿真参数。

    Returns:
        list[RuleViolation]: 执行契约违规列表。

    Raises:
        无。

    Example:
        >>> from mechagent.core.validation import tc01_model_params
        >>> check_static_execution_contract(tc01_model_params())
        []
    """

    violations: list[RuleViolation] = []
    if model_params.analysis.type is not AnalysisType.STATIC:
        violations.append(
            RuleViolation(
                field="analysis.type",
                value=0.0,
                message="内置执行路径支持 static 分析。",
            )
        )
    if model_params.analysis.nlgeom:
        violations.append(
            RuleViolation(
                field="analysis.nlgeom",
                value=1.0,
                message="内置执行路径支持线性静力分析，要求 nlgeom=False。",
            )
        )
    if (
        model_params.material.type is not MaterialType.ISOTROPIC
        or model_params.material.composite is not None
    ):
        violations.append(
            RuleViolation(
                field="material.type",
                value=0.0,
                message="内置执行路径支持各向同性线弹性材料。",
            )
        )

    if model_params.geometry.type is GeometryType.BEAM:
        _check_beam_contract(model_params, violations)
    elif model_params.geometry.type is GeometryType.PLATE:
        _check_plate_contract(model_params, violations)
    elif model_params.geometry.type is GeometryType.SOLID:
        _check_solid_contract(model_params, violations)
    else:
        violations.append(
            RuleViolation(
                field="geometry.type",
                value=0.0,
                message="内置结构静力执行路径支持 beam、plate 和 solid。",
            )
        )
    return violations


def ensure_static_execution_contract(model_params: ModelParams) -> None:
    """检查内置结构静力执行契约并在违规时抛出异常。

    Args:
        model_params: 结构化仿真参数。

    Returns:
        无。

    Raises:
        ValueError: 当模型组合超出内置结构静力执行路径时抛出。

    Example:
        >>> from mechagent.core.validation import tc01_model_params
        >>> ensure_static_execution_contract(tc01_model_params())
    """

    violations = check_static_execution_contract(model_params)
    if not violations:
        return
    detail = "；".join(f"{violation.field}: {violation.message}" for violation in violations)
    msg = f"仿真参数不满足结构静力执行契约: {detail}"
    raise ValueError(msg)


def _check_mesh_size(model_params: ModelParams, violations: list[RuleViolation]) -> None:
    representative_length = _representative_mesh_length(model_params)
    seed_size = model_params.mesh.seed_size
    if seed_size > representative_length:
        violations.append(
            RuleViolation(
                field="mesh.seed_size",
                value=seed_size,
                message="网格尺寸不应大于参与网格划分的代表长度。",
            )
        )


def _representative_mesh_length(model_params: ModelParams) -> float:
    dimensions = model_params.geometry.dimensions
    geometry_type = model_params.geometry.type
    if geometry_type is GeometryType.BEAM:
        return dimensions.get("length", min(dimensions.values()))
    if geometry_type in {
        GeometryType.PLATE,
        GeometryType.SHELL,
        GeometryType.STIFFENED_PANEL,
    }:
        in_plane = [dimensions[name] for name in ("length", "width") if name in dimensions]
        if in_plane:
            return min(in_plane)
    return min(dimensions.values())


def _check_beam_contract(
    model_params: ModelParams,
    violations: list[RuleViolation],
) -> None:
    _check_required_dimensions(model_params, ("length", "width", "height"), violations)
    if model_params.mesh.element_type is not ElementType.B31:
        violations.append(
            RuleViolation(
                field="mesh.element_type",
                value=0.0,
                message="梁静力执行路径使用 B31 单元。",
            )
        )
    if not _has_bc(
        model_params,
        types={BCType.FIXED, BCType.ENCASTRE},
        regions={"root", "fixed_end", "left_end"},
        dofs={"ux", "uy", "uz", "rx", "ry", "rz"},
    ):
        violations.append(
            RuleViolation(
                field="bcs",
                value=0.0,
                message="梁静力执行路径需要 root 固支边界并约束 ux/uy/uz/rx/ry/rz。",
            )
        )
    load = _single_supported_load(
        model_params,
        {
            LoadType.FORCE: {"tip", "free_end", "right_end"},
            LoadType.LINE_LOAD: {"span", "full_span"},
        },
    )
    if load is None:
        violations.append(
            RuleViolation(
                field="loads",
                value=0.0,
                message="梁静力执行路径支持 tip 集中力或 span 全跨均布线载荷。",
            )
        )
    elif not _is_axis_aligned(load.direction, 1):
        violations.append(
            RuleViolation(
                field="loads.direction",
                value=0.0,
                message="梁静力执行路径支持纯全局 Y 向横向载荷。",
            )
        )


def _check_plate_contract(
    model_params: ModelParams,
    violations: list[RuleViolation],
) -> None:
    _check_required_dimensions(model_params, ("length", "width", "thickness"), violations)
    _check_plate_hole_dimensions(model_params, violations)
    if model_params.mesh.element_type is not ElementType.S4:
        violations.append(
            RuleViolation(
                field="mesh.element_type",
                value=0.0,
                message="板静力执行路径使用 S4 壳单元。",
            )
        )
    if not _has_bc(
        model_params,
        types={BCType.SIMPLE_SUPPORT},
        regions={"all_edges", "edges"},
        dofs={"uz"},
    ):
        violations.append(
            RuleViolation(
                field="bcs",
                value=0.0,
                message="板静力执行路径需要 all_edges 简支边界并约束 uz。",
            )
        )
    load = _single_supported_load(
        model_params,
        {LoadType.PRESSURE: {"top_surface", "surface", "plate", "all"}},
    )
    if load is None:
        violations.append(
            RuleViolation(
                field="loads",
                value=0.0,
                message="板静力执行路径支持 top_surface 均布压力。",
            )
        )
    elif not _is_axis_aligned(load.direction, 2):
        violations.append(
            RuleViolation(
                field="loads.direction",
                value=0.0,
                message="板静力执行路径支持纯全局 Z 向面载荷。",
            )
        )


def _check_plate_hole_dimensions(
    model_params: ModelParams,
    violations: list[RuleViolation],
) -> None:
    dimensions = model_params.geometry.dimensions
    expected_count = int(dimensions.get("hole_count", 0.0))
    holes = _plate_holes_from_dimensions(dimensions)
    if not holes:
        if expected_count >= 1 or any(key.startswith("hole_") for key in dimensions):
            violations.append(
                RuleViolation(
                    field="geometry.dimensions.hole",
                    value=0.0,
                    message="圆孔参数需要同时包含半径和孔心 x/y 坐标。",
                )
            )
        return
    if "length" not in dimensions or "width" not in dimensions:
        return
    length = dimensions["length"]
    width = dimensions["width"]
    for index, (radius, center_x, center_y) in enumerate(holes, start=1):
        margin = min(center_x, length - center_x, center_y, width - center_y)
        if radius >= margin:
            field = (
                f"geometry.dimensions.hole_{index}_radius"
                if len(holes) > 1
                else "geometry.dimensions.hole_radius"
            )
            violations.append(
                RuleViolation(
                    field=field,
                    value=radius,
                    message="圆孔半径需要小于孔心到外边界的最小距离。",
                )
            )
    for left_index, left in enumerate(holes):
        left_radius, left_x, left_y = left
        for right_index, right in enumerate(holes[left_index + 1 :], start=left_index + 2):
            right_radius, right_x, right_y = right
            distance = ((left_x - right_x) ** 2 + (left_y - right_y) ** 2) ** 0.5
            if distance > left_radius + right_radius:
                continue
            violations.append(
                RuleViolation(
                    field=f"geometry.dimensions.hole_{right_index}_center",
                    value=distance,
                    message=(
                        f"第 {left_index + 1} 个圆孔与第 {right_index} 个圆孔"
                        "中心距需要大于两个孔半径之和。"
                    ),
                )
            )


def _plate_holes_from_dimensions(
    dimensions: dict[str, float],
) -> tuple[tuple[float, float, float], ...]:
    hole_count = int(dimensions.get("hole_count", 0.0))
    if hole_count >= 1:
        holes: list[tuple[float, float, float]] = []
        for index in range(1, hole_count + 1):
            radius = dimensions.get(f"hole_{index}_radius")
            center_x = dimensions.get(f"hole_{index}_center_x")
            center_y = dimensions.get(f"hole_{index}_center_y")
            if hole_count == 1:
                radius = radius if radius is not None else dimensions.get("hole_radius")
                center_x = center_x if center_x is not None else dimensions.get("hole_center_x")
                center_y = center_y if center_y is not None else dimensions.get("hole_center_y")
            if radius is None or center_x is None or center_y is None:
                return ()
            holes.append((radius, center_x, center_y))
        return tuple(holes)

    if all(name in dimensions for name in ("hole_radius", "hole_center_x", "hole_center_y")):
        return (
            (
                dimensions["hole_radius"],
                dimensions["hole_center_x"],
                dimensions["hole_center_y"],
            ),
        )
    return ()


def _check_solid_contract(
    model_params: ModelParams,
    violations: list[RuleViolation],
) -> None:
    _check_required_dimensions(model_params, ("length", "width", "height"), violations)
    if model_params.mesh.element_type is not ElementType.C3D8R:
        violations.append(
            RuleViolation(
                field="mesh.element_type",
                value=0.0,
                message="实体静力执行路径使用 C3D8R 单元。",
            )
        )
    if not _has_bc(
        model_params,
        types={BCType.FIXED, BCType.ENCASTRE},
        regions={"root", "fixed_end", "left_end"},
        dofs={"ux", "uy", "uz"},
    ):
        violations.append(
            RuleViolation(
                field="bcs",
                value=0.0,
                message="实体静力执行路径需要 root 固定边界并约束 ux/uy/uz。",
            )
        )
    load = _single_supported_load(
        model_params,
        {
            LoadType.PRESSURE: {"end_face", "right_end", "free_end"},
            LoadType.FORCE: {"end_face", "right_end", "free_end"},
        },
    )
    if load is None:
        violations.append(
            RuleViolation(
                field="loads",
                value=0.0,
                message="实体静力执行路径支持 end_face 轴向压力或端面合力。",
            )
        )
    elif not _is_axis_aligned(load.direction, 0):
        violations.append(
            RuleViolation(
                field="loads.direction",
                value=0.0,
                message="实体静力执行路径支持纯全局 X 向端面轴向载荷。",
            )
        )


def _has_bc(
    model_params: ModelParams,
    *,
    types: set[BCType],
    regions: set[str],
    dofs: set[str],
) -> bool:
    for bc in model_params.bcs:
        if bc.type not in types:
            continue
        if _normalized_key(bc.region) not in regions:
            continue
        if dofs.issubset({_normalized_key(dof) for dof in bc.dofs}):
            return True
    return False


def _check_required_dimensions(
    model_params: ModelParams,
    required: tuple[str, ...],
    violations: list[RuleViolation],
) -> None:
    missing = [name for name in required if name not in model_params.geometry.dimensions]
    for name in missing:
        violations.append(
            RuleViolation(
                field=f"geometry.dimensions.{name}",
                value=0.0,
                message="内置执行路径需要该几何尺寸字段。",
            )
        )


def _single_supported_load(
    model_params: ModelParams,
    allowed: dict[LoadType, set[str]],
) -> LoadSpec | None:
    if len(model_params.loads) != 1:
        return None
    load = model_params.loads[0]
    if load.type not in allowed:
        return None
    if _normalized_key(load.region) not in allowed[load.type]:
        return None
    return load


def _is_axis_aligned(direction: tuple[float, float, float], axis: int) -> bool:
    axis_value = abs(direction[axis])
    if axis_value <= 1.0e-12:
        return False
    tolerance = max(1.0e-12, axis_value * 1.0e-9)
    return all(abs(value) <= tolerance for index, value in enumerate(direction) if index != axis)


def _normalized_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")

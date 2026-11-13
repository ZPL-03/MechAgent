"""不同求解器结果的可复核差异比较。"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mechagent.core.models import GeometryType, LoadType, ModelParams
from mechagent.core.results import compute_mesh_digest


class ComparisonTolerance(BaseModel):
    """场量差异阈值。"""

    model_config = ConfigDict(extra="forbid")

    relative: float = Field(default=1.0e-3, ge=0.0)
    absolute: float = Field(default=1.0e-9, ge=0.0)
    coordinate: float = Field(default=1.0e-7, gt=0.0)


class FieldComparison(BaseModel):
    """单个结果字段的比较状态和证据摘要。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed", "unverified", "missing"]
    alignment: str | None = None
    reason: str | None = None
    compared_count: int = Field(default=0, ge=0)
    mapping: str | None = None
    left_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    right_coverage: float | None = Field(default=None, ge=0.0, le=1.0)


class BackendComparison(BaseModel):
    """两个适配器结果的差异比较。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed", "unverified"]
    left_backend: str
    right_backend: str
    field_source: Literal["requested_fields", "fields", "mapped_fields", "comparison_fields"] = (
        "requested_fields"
    )
    compared_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    unverified_fields: list[str] = Field(default_factory=list)
    alignment: dict[str, str] = Field(default_factory=dict)
    field_results: dict[str, FieldComparison] = Field(default_factory=dict)
    max_absolute_error: float = Field(default=0.0, ge=0.0)
    max_relative_error: float = Field(default=0.0, ge=0.0)
    tolerance: ComparisonTolerance
    differences: list[dict[str, Any]] = Field(default_factory=list)


class EquilibriumReport(BaseModel):
    """外加载荷与支撑反力的合力平衡校核。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed", "unverified"]
    load_types: list[str] = Field(default_factory=list)
    applied_resultant: tuple[float, float, float] | None = None
    reaction_resultant: tuple[float, float, float] | None = None
    residual: tuple[float, float, float] | None = None
    max_absolute_error: float = Field(default=0.0, ge=0.0)
    max_relative_error: float = Field(default=0.0, ge=0.0)
    tolerance: ComparisonTolerance
    source: str = "fields.reaction_force + mesh coordinates + model loads"
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_finite_vectors(self) -> "EquilibriumReport":
        for value in (self.applied_resultant, self.reaction_resultant, self.residual):
            if value is not None and any(not math.isfinite(item) for item in value):
                raise ValueError("平衡校核向量必须包含有限数值。")
        if not math.isfinite(self.max_absolute_error) or not math.isfinite(self.max_relative_error):
            raise ValueError("平衡校核误差必须是有限数值。")
        return self


def compare_backend_results(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_backend: str,
    right_backend: str,
    tolerance: ComparisonTolerance | None = None,
    field_source: Literal[
        "requested_fields", "fields", "mapped_fields", "comparison_fields"
    ] = "requested_fields",
) -> BackendComparison:
    """比较两个适配器的声明字段或原始场，并保留缺失与误差明细。

    ``requested_fields`` 适合验证案例契约选择器；``fields`` 用于后端原始场的
    交叉检查。原始场只有在位置、单位和离散映射可证明一致时才逐值比较；
    其他场标记为 ``unverified``，统一物理语义应通过 ``comparison_fields`` 提供。
    """

    selected_tolerance = tolerance or ComparisonTolerance()
    left_digest = left.get("case_digest")
    right_digest = right.get("case_digest")
    if left_digest is not None or right_digest is not None:
        if not isinstance(left_digest, str) or not isinstance(right_digest, str):
            return BackendComparison(
                status="failed",
                left_backend=left_backend,
                right_backend=right_backend,
                field_source=field_source,
                tolerance=selected_tolerance,
                differences=[
                    {
                        "reason": "case_digest_missing",
                        "left_case_digest": left_digest,
                        "right_case_digest": right_digest,
                    }
                ],
            )
        if left_digest != right_digest:
            return BackendComparison(
                status="failed",
                left_backend=left_backend,
                right_backend=right_backend,
                field_source=field_source,
                tolerance=selected_tolerance,
                differences=[
                    {
                        "reason": "case_digest_mismatch",
                        "left_case_digest": left_digest,
                        "right_case_digest": right_digest,
                    }
                ],
            )
    contract_mismatches = _result_contract_mismatches(left, right)
    if contract_mismatches:
        return BackendComparison(
            status="failed",
            left_backend=left_backend,
            right_backend=right_backend,
            field_source=field_source,
            tolerance=selected_tolerance,
            differences=contract_mismatches,
        )
    left_fields = left.get(field_source)
    right_fields = right.get(field_source)
    if not isinstance(left_fields, dict) or not isinstance(right_fields, dict):
        return BackendComparison(
            status="unverified",
            left_backend=left_backend,
            right_backend=right_backend,
            field_source=field_source,
            tolerance=selected_tolerance,
            differences=[{"reason": f"{field_source} 缺失"}],
        )
    names = sorted(set(left_fields) | set(right_fields))
    missing: list[str] = []
    unverified: list[str] = []
    compared: list[str] = []
    differences: list[dict[str, Any]] = []
    alignments: dict[str, str] = {}
    field_results: dict[str, FieldComparison] = {}
    max_abs = 0.0
    max_rel = 0.0

    def set_field_result(
        name: str,
        status: Literal["passed", "failed", "unverified", "missing"],
        *,
        alignment: str | None = None,
        reason: str | None = None,
        compared_count: int = 0,
        left_field: dict[str, Any] | None = None,
        right_field: dict[str, Any] | None = None,
    ) -> None:
        mapping = _field_mapping_name(left_field, right_field)
        field_results[name] = FieldComparison(
            status=status,
            alignment=alignment,
            reason=reason,
            compared_count=compared_count,
            mapping=mapping,
            left_coverage=_field_coverage(left_field),
            right_coverage=_field_coverage(right_field),
        )

    for name in names:
        left_field = left_fields.get(name)
        right_field = right_fields.get(name)
        if not isinstance(left_field, dict) or not isinstance(right_field, dict):
            missing.append(name)
            set_field_result(
                name,
                "missing",
                reason="field_missing",
                left_field=left_field,
                right_field=right_field,
            )
            continue
        left_values = left_field.get("values")
        right_values = right_field.get("values")
        if not isinstance(left_values, dict) or not isinstance(right_values, dict):
            missing.append(name)
            set_field_result(
                name,
                "missing",
                reason="field_values_missing",
                left_field=left_field,
                right_field=right_field,
            )
            continue
        field_semantics = _field_semantics_mismatch(left_field, right_field)
        if field_semantics is not None:
            if field_source in {"fields", "mapped_fields"}:
                unverified.append(name)
                alignments[name] = "unverified"
                set_field_result(
                    name,
                    "unverified",
                    alignment="unverified",
                    reason=str(field_semantics["reason"]),
                    left_field=left_field,
                    right_field=right_field,
                )
            else:
                differences.append({"field": name, **field_semantics})
                alignments[name] = "contract-mismatch"
                set_field_result(
                    name,
                    "failed",
                    alignment="contract-mismatch",
                    reason=str(field_semantics["reason"]),
                    left_field=left_field,
                    right_field=right_field,
                )
            continue
        mapping_issue = _mapping_coverage_mismatch(left_field, right_field, field_source)
        if mapping_issue is not None:
            unverified.append(name)
            alignments[name] = "unverified"
            set_field_result(
                name,
                "unverified",
                alignment="unverified",
                reason=mapping_issue,
                left_field=left_field,
                right_field=right_field,
            )
            continue
        location = str(left_field.get("location", ""))
        if location in {"element", "integration_point"} and not _mesh_digests_match(left, right):
            if not (
                isinstance(left_field.get("summary"), dict)
                and isinstance(right_field.get("summary"), dict)
            ):
                unverified.append(name)
                alignments[name] = "unverified"
                set_field_result(
                    name,
                    "unverified",
                    alignment="unverified",
                    reason="mesh_digest_mismatch",
                    left_field=left_field,
                    right_field=right_field,
                )
                continue
        elif location in {"element", "integration_point"}:
            labels = sorted(set(left_values) | set(right_values))
            exact_values = [
                (label, label, left_values[label], right_values[label])
                for label in labels
                if label in left_values and label in right_values
            ]
            exact_aligned = _compare_value_maps(
                name,
                exact_values,
                selected_tolerance,
                "element-key" if location == "element" else "integration-point-key",
            )
            compared.extend(exact_aligned[0])
            differences.extend(exact_aligned[1])
            max_abs = max(max_abs, exact_aligned[2])
            max_rel = max(max_rel, exact_aligned[3])
            missing.extend(f"{name}[{label}]" for label in labels if label not in left_values)
            missing.extend(f"{name}[{label}]" for label in labels if label not in right_values)
            alignments[name] = "element-key" if location == "element" else "integration-point-key"
            field_missing = any(item.startswith(f"{name}[") for item in missing)
            field_failed = any(item.get("field") == name for item in differences)
            set_field_result(
                name,
                "failed" if field_missing or field_failed else "passed",
                alignment=alignments[name],
                reason=(
                    "value_difference"
                    if field_failed
                    else "field_values_missing"
                    if field_missing
                    else None
                ),
                compared_count=_field_compared_count(name, compared),
                left_field=left_field,
                right_field=right_field,
            )
            continue
        labels = sorted(set(left_values) | set(right_values))
        coordinate_pairs = _coordinate_pairs(
            left,
            right,
            selected_tolerance.coordinate,
            location=str(left_field.get("location", "")),
        )
        if (
            coordinate_pairs
            and left_field.get("location") == right_field.get("location")
            and left_field.get("location") in {"node", "element_centroid"}
            and (
                field_source not in {"fields", "mapped_fields"}
                or _pairs_cover_fields(coordinate_pairs, left_values, right_values)
            )
        ):
            aligned = _compare_aligned_values(
                name,
                left_values,
                right_values,
                coordinate_pairs,
                selected_tolerance,
            )
            if aligned is None:
                missing.append(f"{name}[coordinate]")
            else:
                compared.extend(aligned[0])
                differences.extend(aligned[1])
                max_abs = max(max_abs, aligned[2])
                max_rel = max(max_rel, aligned[3])
            alignments[name] = (
                "element-centroid-coordinate"
                if left_field.get("location") == "element_centroid"
                else "node-coordinate"
            )
            field_failed = any(item.get("field") == name for item in differences)
            field_compared = _field_compared_count(name, compared)
            field_missing = any(item.startswith(f"{name}[") for item in missing)
            set_field_result(
                name,
                "failed"
                if field_failed or field_missing
                else "passed"
                if field_compared
                else "unverified",
                alignment=alignments[name],
                reason=(
                    "value_difference"
                    if field_failed
                    else "field_values_missing"
                    if field_missing
                    else None
                ),
                compared_count=field_compared,
                left_field=left_field,
                right_field=right_field,
            )
            continue
        line_aligned = _line_coordinate_values(
            left,
            right,
            left_values,
            right_values,
            left_field=left_field,
            right_field=right_field,
            field_name=name,
        )
        if (
            line_aligned is not None
            and left_field.get("location") == right_field.get("location") == "node"
            and field_source not in {"fields", "mapped_fields"}
        ):
            line_values, line_alignment = line_aligned
            aligned = _compare_value_maps(name, line_values, selected_tolerance, line_alignment)
            compared.extend(aligned[0])
            differences.extend(aligned[1])
            max_abs = max(max_abs, aligned[2])
            max_rel = max(max_rel, aligned[3])
            alignments[name] = line_alignment
            field_failed = any(item.get("field") == name for item in differences)
            set_field_result(
                name,
                "failed" if field_failed else "passed",
                alignment=line_alignment,
                reason="value_difference" if field_failed else None,
                compared_count=_field_compared_count(name, compared),
                left_field=left_field,
                right_field=right_field,
            )
            continue
        if isinstance(left_field.get("summary"), dict) and isinstance(
            right_field.get("summary"), dict
        ):
            summary_result = _compare_summaries(
                name,
                left_field.get("summary"),
                right_field.get("summary"),
                selected_tolerance,
            )
            if summary_result is None:
                missing.append(f"{name}[summary]")
            else:
                compared.extend(summary_result[0])
                differences.extend(summary_result[1])
                max_abs = max(max_abs, summary_result[2])
                max_rel = max(max_rel, summary_result[3])
                alignments[name] = "summary"
                field_failed = any(item.get("field") == name for item in differences)
                set_field_result(
                    name,
                    "failed" if field_failed else "passed",
                    alignment="summary",
                    reason="value_difference" if field_failed else None,
                    compared_count=_field_compared_count(name, compared),
                    left_field=left_field,
                    right_field=right_field,
                )
            if summary_result is None:
                set_field_result(
                    name,
                    "missing",
                    alignment="summary",
                    reason="summary_missing",
                    left_field=left_field,
                    right_field=right_field,
                )
            continue
        if field_source in {"fields", "mapped_fields"}:
            unverified.append(name)
            alignments[name] = "unverified"
            set_field_result(
                name,
                "unverified",
                alignment="unverified",
                reason="coordinate_alignment_unavailable",
                left_field=left_field,
                right_field=right_field,
            )
            continue
        direct_compared = False
        for label in labels:
            if label not in left_values or label not in right_values:
                missing.append(f"{name}[{label}]")
                continue
            left_value = _flatten(left_values[label])
            right_value = _flatten(right_values[label])
            if len(left_value) != len(right_value):
                missing.append(f"{name}[{label}]")
                continue
            compared.append(f"{name}[{label}]")
            direct_compared = True
            for index, (left_item, right_item) in enumerate(
                zip(left_value, right_value, strict=True)
            ):
                absolute = abs(left_item - right_item)
                scale = max(abs(left_item), abs(right_item), selected_tolerance.absolute)
                relative = absolute / scale
                max_abs = max(max_abs, absolute)
                max_rel = max(max_rel, relative)
                if (
                    absolute > selected_tolerance.absolute
                    and relative > selected_tolerance.relative
                ):
                    differences.append(
                        {
                            "field": name,
                            "label": label,
                            "component": index,
                            "left": left_item,
                            "right": right_item,
                            "absolute_error": absolute,
                            "relative_error": relative,
                        }
                    )
        if direct_compared:
            alignments[name] = "direct"
            field_failed = any(item.get("field") == name for item in differences)
            field_missing = any(item.startswith(f"{name}[") for item in missing)
            set_field_result(
                name,
                "failed" if field_failed or field_missing else "passed",
                alignment="direct",
                reason=(
                    "value_difference"
                    if field_failed
                    else "field_values_missing"
                    if field_missing
                    else None
                ),
                compared_count=_field_compared_count(name, compared),
                left_field=left_field,
                right_field=right_field,
            )
        else:
            set_field_result(
                name,
                "missing" if any(item.startswith(f"{name}[") for item in missing) else "unverified",
                alignment=alignments.get(name),
                reason="field_values_missing"
                if any(item.startswith(f"{name}[") for item in missing)
                else "no_comparable_values",
                left_field=left_field,
                right_field=right_field,
            )
    status: Literal["passed", "failed", "unverified"] = "passed"
    if missing or differences:
        status = "failed"
    elif not compared or unverified:
        status = "unverified"
    return BackendComparison(
        status=status,
        left_backend=left_backend,
        right_backend=right_backend,
        field_source=field_source,
        compared_fields=compared,
        missing_fields=sorted(set(missing)),
        unverified_fields=sorted(set(unverified)),
        alignment=alignments,
        field_results=field_results,
        max_absolute_error=max_abs,
        max_relative_error=max_rel,
        tolerance=selected_tolerance,
        differences=differences,
    )


def _field_mapping_name(left: dict[str, Any] | None, right: dict[str, Any] | None) -> str | None:
    values = [
        str(field["mapping"])
        for field in (left, right)
        if isinstance(field, dict) and isinstance(field.get("mapping"), str)
    ]
    if not values:
        return None
    if len(set(values)) == 1:
        return values[0]
    return " <-> ".join(dict.fromkeys(values))


def _field_coverage(field: dict[str, Any] | None) -> float | None:
    if not isinstance(field, dict) or "coverage" not in field:
        return None
    try:
        value = float(field["coverage"])
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None


def _mapping_coverage_mismatch(
    left: dict[str, Any], right: dict[str, Any], field_source: str
) -> str | None:
    if field_source != "mapped_fields":
        return None
    coverages = (_field_coverage(left), _field_coverage(right))
    complete_values = (left.get("complete"), right.get("complete"))
    if any(value is not None and value < 1.0 for value in coverages):
        return "mapping_incomplete"
    if any(value is False for value in complete_values):
        return "mapping_incomplete"
    return None


def _field_compared_count(name: str, compared: list[str]) -> int:
    return sum(1 for item in compared if item.startswith(f"{name}[") or item.startswith(f"{name}."))


def _field_semantics_mismatch(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    """返回两个字段的空间或单位契约冲突。

    原始场的位置或单位不一致时只能保持 ``unverified``；请求字段和统一语义
    字段的同类冲突属于比较契约失败。两侧都未声明单位时保留兼容行为。
    """

    left_location = str(left.get("location", ""))
    right_location = str(right.get("location", ""))
    if left_location != right_location:
        return {
            "reason": "field_location_mismatch",
            "left_location": left_location,
            "right_location": right_location,
        }
    left_unit = str(left.get("unit", ""))
    right_unit = str(right.get("unit", ""))
    if left_unit != right_unit and (left_unit or right_unit):
        return {
            "reason": "field_unit_mismatch",
            "left_unit": left_unit,
            "right_unit": right_unit,
        }
    return None


def _mesh_digests_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_digest = left.get("mesh_digest")
    right_digest = right.get("mesh_digest")
    left_computed = compute_mesh_digest(left)
    right_computed = compute_mesh_digest(right)
    if left_computed is None or right_computed is None:
        return False
    if left_computed != left_digest:
        return False
    if right_computed != right_digest:
        return False
    return isinstance(left_digest, str) and bool(left_digest) and left_digest == right_digest


def _result_contract_mismatches(
    left: dict[str, Any], right: dict[str, Any]
) -> list[dict[str, Any]]:
    """检查结果级单位和坐标契约是否一致。

    适配器结果通常携带案例级 ``units`` 和 ``coordinate_system``。两侧只要
    有一侧声明了这些字段，就必须同时声明并保持完全一致；缺失或不一致时
    不进入场量数值比较。两侧都未提供元数据时保留兼容行为，适用于脱离
    案例契约的低层比较工具。
    """

    missing = object()
    mismatches: list[dict[str, Any]] = []
    for key in ("units", "coordinate_system"):
        left_value = left.get(key, missing)
        right_value = right.get(key, missing)
        if left_value is missing and right_value is missing:
            continue
        if left_value is missing or right_value is missing:
            mismatches.append(
                {
                    "reason": f"{key}_missing",
                    "left": None if left_value is missing else left_value,
                    "right": None if right_value is missing else right_value,
                }
            )
            continue
        if not isinstance(left_value, dict) or not isinstance(right_value, dict):
            mismatches.append(
                {
                    "reason": f"{key}_invalid",
                    "left": left_value,
                    "right": right_value,
                }
            )
            continue
        if left_value != right_value:
            mismatches.append(
                {
                    "reason": f"{key}_mismatch",
                    "left": left_value,
                    "right": right_value,
                }
            )
    return mismatches


def evaluate_reaction_balance(
    result: dict[str, Any],
    model: ModelParams,
    *,
    tolerance: ComparisonTolerance | None = None,
) -> EquilibriumReport:
    """校核支撑反力合力是否平衡可计算的外加载荷合力。

    集中力、梁全跨线载荷以及参数化板/实体的已知面压力可以计算载荷合力。
    位移控制、力矩、温度载荷、未知 CAD 受载面积和不支持的区域保持
    ``unverified``，不以反力场存在替代载荷平衡证据。
    """

    selected_tolerance = tolerance or ComparisonTolerance()
    load_types = [load.type.value for load in model.loads]
    if result.get("success") is False or result.get("success") == "failed":
        return EquilibriumReport(
            status="failed",
            load_types=load_types,
            tolerance=selected_tolerance,
            reason="求解结果失败，不能进行反力平衡校核。",
        )
    if result.get("success") is not True:
        return EquilibriumReport(
            status="unverified",
            load_types=load_types,
            tolerance=selected_tolerance,
            reason="结果缺少 success=true，不能作为已完成求解结果校核。",
        )
    applied, load_reason = _applied_load_resultant(model)
    if applied is None:
        return EquilibriumReport(
            status="unverified",
            load_types=load_types,
            tolerance=selected_tolerance,
            reason=load_reason,
        )
    reaction = _result_reaction_resultant(result, model)
    if reaction is None:
        return EquilibriumReport(
            status="unverified",
            load_types=load_types,
            applied_resultant=applied,
            tolerance=selected_tolerance,
            reason="结果缺少可定位到支撑边界的 reaction_force 或节点坐标。",
        )
    residual = (
        reaction[0] + applied[0],
        reaction[1] + applied[1],
        reaction[2] + applied[2],
    )
    absolute_error = max(abs(value) for value in residual)
    scale = max(
        *(abs(value) for value in applied),
        *(abs(value) for value in reaction),
        selected_tolerance.absolute,
    )
    relative_error = absolute_error / scale
    passed = (
        absolute_error <= selected_tolerance.absolute
        or relative_error <= selected_tolerance.relative
    )
    return EquilibriumReport(
        status="passed" if passed else "failed",
        load_types=load_types,
        applied_resultant=applied,
        reaction_resultant=reaction,
        residual=residual,
        max_absolute_error=absolute_error,
        max_relative_error=relative_error,
        tolerance=selected_tolerance,
        reason=None if passed else "支撑反力合力未达到载荷平衡阈值。",
    )


def _applied_load_resultant(
    model: ModelParams,
) -> tuple[tuple[float, float, float] | None, str | None]:
    total = [0.0, 0.0, 0.0]
    for load in model.loads:
        direction = _unit_vector(load.direction)
        if direction is None:
            return None, f"载荷 {load.region} 的方向无法归一化。"
        factor: float | None
        if load.type is LoadType.FORCE:
            factor = load.magnitude
        elif load.type is LoadType.LINE_LOAD:
            length = model.geometry.dimensions.get("length")
            if model.geometry.type.value != "beam" or length is None:
                return None, "线载荷缺少可计算的梁长度。"
            factor = load.magnitude * length
        elif load.type is LoadType.PRESSURE:
            area = _known_pressure_area(model, load.region)
            if area is None:
                return None, f"压力区域 {load.region} 的面积未在当前契约中定义。"
            factor = load.magnitude * area
        else:
            return None, f"载荷类型 {load.type.value} 没有可计算的合力契约。"
        for index, component in enumerate(direction):
            total[index] += factor * component
    if not all(math.isfinite(value) for value in total):
        return None, "外加载荷合力不是有限数值。"
    return (total[0], total[1], total[2]), None


def _known_pressure_area(model: ModelParams, region: str) -> float | None:
    dimensions = model.geometry.dimensions
    key = region.strip().lower().replace("-", "_").replace(" ", "_")
    if model.geometry.type.value == "plate" and key in {
        "top_surface",
        "surface",
        "plate",
        "all",
    }:
        length, width = dimensions.get("length"), dimensions.get("width")
        return None if length is None or width is None else length * width
    if model.geometry.type.value == "solid" and key in {
        "end_face",
        "right_end",
        "free_end",
    }:
        width, height = dimensions.get("width"), dimensions.get("height")
        return None if width is None or height is None else width * height
    return None


def _result_reaction_resultant(
    result: dict[str, Any], model: ModelParams
) -> tuple[float, float, float] | None:
    fields = result.get("fields")
    reaction = fields.get("reaction_force") if isinstance(fields, dict) else None
    values = reaction.get("values") if isinstance(reaction, dict) else None
    vectors = {
        label: vector for label, vector in _finite_vectors(values).items() if len(vector) >= 3
    }
    nodes = _node_coordinates(result.get("nodes"))
    if not nodes:
        nodes = _node_coordinates(result.get("mesh_nodes"))
    support_labels = _support_reaction_labels(vectors, nodes, model)
    if support_labels:
        return _sum_vectors(vectors, support_labels)
    return _root_resultant(vectors, nodes)


def _support_reaction_labels(
    vectors: dict[str, tuple[float, ...]],
    nodes: dict[str, tuple[float, float, float]],
    model: ModelParams,
) -> list[str] | None:
    """返回当前边界契约对应的支撑节点，无法确定时返回 ``None``。"""

    if model.geometry.type is not GeometryType.PLATE:
        return None
    regions = {_normalized_region(boundary.region) for boundary in model.bcs}
    if not regions.intersection({"all_edges", "all_boundaries", "boundary", "edges"}):
        return None
    common = set(vectors) & set(nodes)
    if not common:
        return None
    points = [nodes[label] for label in common]
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    tolerance = max(
        1.0e-8, max(max(x_values) - min(x_values), max(y_values) - min(y_values)) * 1.0e-8
    )
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    labels = [
        label
        for label in common
        if (
            abs(nodes[label][0] - x_min) <= tolerance
            or abs(nodes[label][0] - x_max) <= tolerance
            or abs(nodes[label][1] - y_min) <= tolerance
            or abs(nodes[label][1] - y_max) <= tolerance
        )
    ]
    return labels or None


def _sum_vectors(
    vectors: dict[str, tuple[float, ...]], labels: list[str]
) -> tuple[float, float, float] | None:
    if not labels:
        return None
    resultant = [0.0, 0.0, 0.0]
    for label in labels:
        vector = vectors[label]
        for index in range(min(len(vector), 3)):
            resultant[index] += vector[index]
    return (resultant[0], resultant[1], resultant[2])


def _normalized_region(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _unit_vector(value: tuple[float, float, float]) -> tuple[float, float, float] | None:
    norm = math.sqrt(sum(component * component for component in value))
    if not math.isfinite(norm) or norm <= 1.0e-12:
        return None
    return (value[0] / norm, value[1] / norm, value[2] / norm)


def _pairs_cover_fields(
    pairs: dict[str, str], left_values: dict[str, Any], right_values: dict[str, Any]
) -> bool:
    """要求原始节点场的坐标映射覆盖两侧实际场值。"""

    return set(left_values).issubset(pairs) and set(right_values).issubset(set(pairs.values()))


def derive_comparison_fields(
    result: dict[str, Any], *, elastic_modulus: float, poisson_ratio: float
) -> dict[str, dict[str, Any]]:
    """从两个适配器均可得到的原始场生成统一语义比较字段。

    返回的应力字段为全场绝对最大分量，能量字段按各向同性线弹性本构从
    应力重建应变能密度摘要，反力字段为最大跨度方向根部区域的合力。每个
    字段都保留来源和推导说明；缺少必要原始场时，比较器报告 ``unverified``，字段列表保持为空。
    """

    if not math.isfinite(elastic_modulus) or elastic_modulus <= 0.0:
        raise ValueError("elastic_modulus 必须是正的有限数。")
    if not math.isfinite(poisson_ratio) or not -1.0 < poisson_ratio < 0.5:
        raise ValueError("poisson_ratio 必须位于 (-1, 0.5)。")
    fields = result.get("fields")
    if not isinstance(fields, dict):
        return {}
    derived: dict[str, dict[str, Any]] = {}
    stress = fields.get("stress")
    stress_values = stress.get("values") if isinstance(stress, dict) else None
    stress_vectors = _finite_vectors(stress_values)
    if stress_vectors:
        stress_numbers = [item for vector in stress_vectors.values() for item in vector]
        derived["stress_max_abs"] = {
            "location": "global",
            "unit": "MPa",
            "values": {"max_abs": max(abs(item) for item in stress_numbers)},
            "summary": {"max_abs": max(abs(item) for item in stress_numbers)},
            "source": "fields.stress",
            "derivation": "全场应力分量绝对最大值",
        }
        energy_density = [
            _strain_energy_density(vector, elastic_modulus, poisson_ratio)
            for vector in stress_vectors.values()
        ]
        derived["strain_energy_density"] = {
            "location": "global",
            "unit": "N/mm^2",
            "values": {
                "max_abs": max(energy_density),
                "mean": sum(energy_density) / len(energy_density),
            },
            "summary": {
                "max_abs": max(energy_density),
                "mean": sum(energy_density) / len(energy_density),
            },
            "source": "fields.stress",
            "derivation": "各向同性线弹性本构的 0.5*sigma:epsilon",
        }
    reaction = fields.get("reaction_force")
    reaction_values = reaction.get("values") if isinstance(reaction, dict) else None
    nodes = _node_coordinates(result.get("nodes"))
    reaction_vectors = _finite_vectors(reaction_values)
    root = _root_resultant(reaction_vectors, nodes)
    if root is not None:
        derived["reaction_resultant"] = {
            "location": "support_boundary",
            "unit": "N",
            "values": {"fx": root[0], "fy": root[1], "fz": root[2]},
            "source": "fields.reaction_force + nodes",
            "derivation": "最大跨度方向最小坐标边界区域反力合力",
        }
    return derived


def _finite_vectors(values: Any) -> dict[str, tuple[float, ...]]:
    if not isinstance(values, dict):
        return {}
    vectors: dict[str, tuple[float, ...]] = {}
    for label, value in values.items():
        if not isinstance(value, (list, tuple)):
            continue
        try:
            vector = tuple(float(item) for item in value)
        except (TypeError, ValueError):
            continue
        if vector and all(math.isfinite(item) for item in vector):
            vectors[str(label)] = vector
    return vectors


def _strain_energy_density(
    stress: tuple[float, ...], elastic_modulus: float, poisson_ratio: float
) -> float:
    if len(stress) < 3:
        raise ValueError("应力场至少需要三个正应力分量。")
    sxx, syy, szz = stress[:3]
    shear = stress[3:6]
    value = (
        sxx * sxx
        + syy * syy
        + szz * szz
        - 2.0 * poisson_ratio * (sxx * syy + syy * szz + szz * sxx)
    ) / (2.0 * elastic_modulus)
    if len(shear) == 3:
        value += (1.0 + poisson_ratio) / elastic_modulus * sum(item * item for item in shear)
    if value < -1.0e-12:
        raise ValueError("重建的应变能密度不能为负。")
    return max(0.0, value)


def _root_resultant(
    vectors: dict[str, tuple[float, ...]], nodes: dict[str, tuple[float, float, float]]
) -> tuple[float, float, float] | None:
    if not vectors or not nodes:
        return None
    common = set(vectors) & set(nodes)
    if not common:
        return None
    spans = [
        max(nodes[label][index] for label in common) - min(nodes[label][index] for label in common)
        for index in range(3)
    ]
    axis = max(range(3), key=lambda index: spans[index])
    minimum = min(nodes[label][axis] for label in common)
    tolerance = max(1.0e-8, max(spans) * 1.0e-8)
    labels = [label for label in common if abs(nodes[label][axis] - minimum) <= tolerance]
    if not labels:
        return None
    return _sum_vectors(vectors, labels)


def _coordinate_pairs(
    left: dict[str, Any],
    right: dict[str, Any],
    tolerance: float,
    *,
    location: str = "node",
) -> dict[str, str]:
    """按节点或单元质心坐标建立一一对应，禁止直接比较标签。"""

    coordinate_key = "element_centroids" if location == "element_centroid" else "nodes"
    left_nodes = _node_coordinates(left.get(coordinate_key))
    right_nodes = _node_coordinates(right.get(coordinate_key))
    if not left_nodes or not right_nodes:
        return {}
    available = set(right_nodes)
    pairs: dict[str, str] = {}
    for left_label, left_point in sorted(left_nodes.items()):
        candidates = [(label, _distance(left_point, right_nodes[label])) for label in available]
        if not candidates:
            break
        right_label, distance = min(candidates, key=lambda item: (item[1], item[0]))
        if distance > tolerance:
            continue
        pairs[left_label] = right_label
        available.remove(right_label)
    return pairs


def _node_coordinates(value: Any) -> dict[str, tuple[float, float, float]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, tuple[float, float, float]] = {}
    for label, point in value.items():
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            continue
        try:
            coordinates = (
                float(point[0]),
                float(point[1]),
                float(point[2]),
            )
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(item) for item in coordinates):
            result[str(label)] = coordinates
    return result


def _distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def _compare_aligned_values(
    field: str,
    left_values: dict[str, Any],
    right_values: dict[str, Any],
    pairs: dict[str, str],
    tolerance: ComparisonTolerance,
) -> tuple[list[str], list[dict[str, Any]], float, float] | None:
    compared: list[str] = []
    differences: list[dict[str, Any]] = []
    max_abs = 0.0
    max_rel = 0.0
    for left_label, right_label in pairs.items():
        if left_label not in left_values or right_label not in right_values:
            continue
        left_items = _flatten(left_values[left_label])
        right_items = _flatten(right_values[right_label])
        if len(left_items) != len(right_items):
            continue
        compared.append(f"{field}[{left_label}<->{right_label}]")
        for index, (left_item, right_item) in enumerate(zip(left_items, right_items, strict=True)):
            absolute = abs(left_item - right_item)
            scale = max(abs(left_item), abs(right_item), tolerance.absolute)
            relative = absolute / scale
            max_abs = max(max_abs, absolute)
            max_rel = max(max_rel, relative)
            if absolute > tolerance.absolute and relative > tolerance.relative:
                differences.append(
                    {
                        "field": field,
                        "label": left_label,
                        "right_label": right_label,
                        "component": index,
                        "left": left_item,
                        "right": right_item,
                        "absolute_error": absolute,
                        "relative_error": relative,
                        "alignment": "node-coordinate",
                    }
                )
    return (compared, differences, max_abs, max_rel) if compared else None


def _compare_value_maps(
    field: str,
    values: list[tuple[str, str, Any, Any]],
    tolerance: ComparisonTolerance,
    alignment: str,
) -> tuple[list[str], list[dict[str, Any]], float, float]:
    compared: list[str] = []
    differences: list[dict[str, Any]] = []
    max_abs = 0.0
    max_rel = 0.0
    for left_label, right_label, left_value, right_value in values:
        left_items = _flatten(left_value)
        right_items = _flatten(right_value)
        if len(left_items) != len(right_items):
            continue
        compared.append(f"{field}[{left_label}<->{right_label}]")
        for index, (left_item, right_item) in enumerate(zip(left_items, right_items, strict=True)):
            absolute = abs(left_item - right_item)
            scale = max(abs(left_item), abs(right_item), tolerance.absolute)
            relative = absolute / scale
            max_abs = max(max_abs, absolute)
            max_rel = max(max_rel, relative)
            if absolute > tolerance.absolute and relative > tolerance.relative:
                differences.append(
                    {
                        "field": field,
                        "label": left_label,
                        "right_label": right_label,
                        "component": index,
                        "left": left_item,
                        "right": right_item,
                        "absolute_error": absolute,
                        "relative_error": relative,
                        "alignment": alignment,
                    }
                )
    return compared, differences, max_abs, max_rel


def _line_coordinate_values(
    left: dict[str, Any],
    right: dict[str, Any],
    left_values: dict[str, Any],
    right_values: dict[str, Any],
    *,
    left_field: dict[str, Any],
    right_field: dict[str, Any],
    field_name: str,
) -> tuple[list[tuple[str, str, Any, Any]], str] | None:
    left_nodes = _node_coordinates(left.get("nodes"))
    right_nodes = _node_coordinates(right.get("nodes"))
    if not left_nodes or not right_nodes or not _is_line_mesh(left_nodes, right_nodes):
        return None
    raw_centerline = _raw_centerline_values(
        left,
        right,
        left_nodes,
        right_nodes,
        left_field=left_field,
        right_field=right_field,
        field_name=field_name,
    )
    if raw_centerline is not None:
        return raw_centerline, "line-coordinate-centerline"
    groups: dict[float, list[tuple[str, Any]]] = {}
    for label, point in left_nodes.items():
        if label in left_values:
            groups.setdefault(round(point[0], 8), []).append((label, left_values[label]))
    if len(groups) < 2:
        return None
    ordered = sorted(groups.items())
    result: list[tuple[str, str, Any, Any]] = []
    for right_label, point in right_nodes.items():
        if right_label not in right_values:
            continue
        x_key, items = min(ordered, key=lambda item: (abs(item[0] - point[0]), item[0]))
        flattened = [_flatten(value) for _label, value in items]
        width = len(flattened[0])
        if any(len(value) != width for value in flattened):
            continue
        averaged = [
            sum(value[index] for value in flattened) / len(flattened) for index in range(width)
        ]
        left_label = f"x={x_key:g}"
        result.append((left_label, right_label, averaged, right_values[right_label]))
    return (result, "line-coordinate") if result else None


def _raw_centerline_values(
    left: dict[str, Any],
    right: dict[str, Any],
    left_nodes: dict[str, tuple[float, float, float]],
    right_nodes: dict[str, tuple[float, float, float]],
    *,
    left_field: dict[str, Any],
    right_field: dict[str, Any],
    field_name: str,
) -> list[tuple[str, str, float, float]] | None:
    """Compare a scalar invariant reconstructed from raw vector values on a line.

    Beam solvers may emit section expansion nodes while another backend emits
    centerline nodes. For displacement magnitude, averaging the raw vector at
    each axial coordinate removes the cross-section rotation contribution and
    compares the same centerline translation in both results.
    """

    if field_name != "displacement":
        return None
    if left_field.get("selector") != "magnitude" or right_field.get("selector") != "magnitude":
        return None
    left_raw = _raw_node_vectors(left, "displacement")
    right_raw = _raw_node_vectors(right, "displacement")
    if not left_raw or not right_raw:
        return None
    grouped: dict[float, list[tuple[str, tuple[float, ...]]]] = {}
    for label, point in left_nodes.items():
        vector = left_raw.get(label)
        if vector is not None:
            grouped.setdefault(round(point[0], 8), []).append((label, vector))
    if len(grouped) < 2:
        return None
    result: list[tuple[str, str, float, float]] = []
    for right_label, point in right_nodes.items():
        right_vector = right_raw.get(right_label)
        if right_vector is None:
            continue
        x_key, vectors = min(grouped.items(), key=lambda item: (abs(item[0] - point[0]), item[0]))
        width = len(vectors[0][1])
        if width == 0 or any(len(vector) != width for _label, vector in vectors):
            continue
        average = [
            sum(vector[index] for _label, vector in vectors) / len(vectors)
            for index in range(width)
        ]
        left_value = math.sqrt(sum(item * item for item in average))
        right_value = math.sqrt(sum(item * item for item in right_vector))
        result.append((f"x={x_key:g}", right_label, left_value, right_value))
    return result if result else None


def _raw_node_vectors(result: dict[str, Any], field_name: str) -> dict[str, tuple[float, ...]]:
    fields = result.get("fields")
    if not isinstance(fields, dict):
        return {}
    field = fields.get(field_name)
    if not isinstance(field, dict) or not isinstance(field.get("values"), dict):
        return {}
    vectors: dict[str, tuple[float, ...]] = {}
    for label, value in field["values"].items():
        if not isinstance(value, (list, tuple)):
            continue
        try:
            vector = tuple(float(item) for item in value)
        except (TypeError, ValueError):
            continue
        if vector and all(math.isfinite(item) for item in vector):
            vectors[str(label)] = vector
    return vectors


def _is_line_mesh(
    left: dict[str, tuple[float, float, float]],
    right: dict[str, tuple[float, float, float]],
) -> bool:
    spans = []
    for nodes in (left, right):
        values = [
            max(point[index] for point in nodes.values())
            - min(point[index] for point in nodes.values())
            for index in range(3)
        ]
        ordered = sorted(values, reverse=True)
        if ordered[0] <= 0.0 or ordered[1] > ordered[0] * 0.1:
            return False
        spans.append(ordered[0])
    return abs(spans[0] - spans[1]) <= max(spans) * 1.0e-6


def _compare_summaries(
    field: str,
    left: Any,
    right: Any,
    tolerance: ComparisonTolerance,
) -> tuple[list[str], list[dict[str, Any]], float, float] | None:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return None
    # 网格不同会改变节点数量和极值位置；跨工具只比较可解释的场量幅值与均值。
    keys = sorted((set(left) & set(right)) & {"max_abs", "mean"})
    if not keys:
        return None
    compared: list[str] = []
    differences: list[dict[str, Any]] = []
    max_abs = 0.0
    max_rel = 0.0
    for key in keys:
        left_value = _finite_number(left[key])
        right_value = _finite_number(right[key])
        absolute = abs(left_value - right_value)
        scale = max(abs(left_value), abs(right_value), tolerance.absolute)
        relative = absolute / scale
        label = f"summary[{key}]"
        compared.append(f"{field}.{label}")
        max_abs = max(max_abs, absolute)
        max_rel = max(max_rel, relative)
        if absolute > tolerance.absolute and relative > tolerance.relative:
            differences.append(
                {
                    "field": field,
                    "label": label,
                    "component": 0,
                    "left": left_value,
                    "right": right_value,
                    "absolute_error": absolute,
                    "relative_error": relative,
                    "alignment": "summary",
                }
            )
    return compared, differences, max_abs, max_rel


def _finite_number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("结果字段值必须是有限数字。")
    return number


def _flatten(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return [float(value)]
    raise ValueError("结果字段值必须是有限数字或数字数组。")

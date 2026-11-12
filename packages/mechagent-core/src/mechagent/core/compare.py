"""不同求解器结果的可复核差异比较。"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ComparisonTolerance(BaseModel):
    """场量差异阈值。"""

    model_config = ConfigDict(extra="forbid")

    relative: float = Field(default=1.0e-3, ge=0.0)
    absolute: float = Field(default=1.0e-9, ge=0.0)
    coordinate: float = Field(default=1.0e-7, gt=0.0)


class BackendComparison(BaseModel):
    """双后端比较结果。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed", "unverified"]
    left_backend: str
    right_backend: str
    compared_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    alignment: dict[str, str] = Field(default_factory=dict)
    max_absolute_error: float = Field(default=0.0, ge=0.0)
    max_relative_error: float = Field(default=0.0, ge=0.0)
    tolerance: ComparisonTolerance
    differences: list[dict[str, Any]] = Field(default_factory=list)


def compare_backend_results(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_backend: str,
    right_backend: str,
    tolerance: ComparisonTolerance | None = None,
) -> BackendComparison:
    """比较两个适配器的 ``requested_fields``，并保留缺失与误差明细。"""

    selected_tolerance = tolerance or ComparisonTolerance()
    left_fields = left.get("requested_fields")
    right_fields = right.get("requested_fields")
    if not isinstance(left_fields, dict) or not isinstance(right_fields, dict):
        return BackendComparison(
            status="unverified",
            left_backend=left_backend,
            right_backend=right_backend,
            tolerance=selected_tolerance,
            differences=[{"reason": "requested_fields 缺失"}],
        )
    names = sorted(set(left_fields) | set(right_fields))
    missing: list[str] = []
    compared: list[str] = []
    differences: list[dict[str, Any]] = []
    alignments: dict[str, str] = {}
    max_abs = 0.0
    max_rel = 0.0
    for name in names:
        left_field = left_fields.get(name)
        right_field = right_fields.get(name)
        if not isinstance(left_field, dict) or not isinstance(right_field, dict):
            missing.append(name)
            continue
        left_values = left_field.get("values")
        right_values = right_field.get("values")
        if not isinstance(left_values, dict) or not isinstance(right_values, dict):
            missing.append(name)
            continue
        labels = sorted(set(left_values) | set(right_values))
        coordinate_pairs = _coordinate_pairs(left, right, selected_tolerance.coordinate)
        if coordinate_pairs and left_field.get("location") == right_field.get("location") == "node":
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
                alignments[name] = "node-coordinate"
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
        ):
            line_values, line_alignment = line_aligned
            aligned = _compare_value_maps(name, line_values, selected_tolerance, line_alignment)
            compared.extend(aligned[0])
            differences.extend(aligned[1])
            max_abs = max(max_abs, aligned[2])
            max_rel = max(max_rel, aligned[3])
            alignments[name] = line_alignment
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
            continue
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
    status: Literal["passed", "failed", "unverified"] = "passed"
    if not compared:
        status = "unverified"
    elif missing or differences:
        status = "failed"
    return BackendComparison(
        status=status,
        left_backend=left_backend,
        right_backend=right_backend,
        compared_fields=compared,
        missing_fields=sorted(set(missing)),
        alignment=alignments,
        max_absolute_error=max_abs,
        max_relative_error=max_rel,
        tolerance=selected_tolerance,
        differences=differences,
    )


def _coordinate_pairs(
    left: dict[str, Any], right: dict[str, Any], tolerance: float
) -> dict[str, str]:
    """按节点坐标建立一一对应，禁止用不同网格的节点标签直接比较。"""

    left_nodes = _node_coordinates(left.get("nodes"))
    right_nodes = _node_coordinates(right.get("nodes"))
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
    # 网格不同会改变节点数量和极值位置；跨后端只比较可解释的场量幅值与均值。
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

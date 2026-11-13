"""统一结果场字段选择与逐步结果归档。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from mechagent.core.exceptions import SolverError
from mechagent.core.models import LoadStepSpec, ResultFieldSpec, SimulationCase

_QUANTITY_ALIASES = {
    "U": "displacement",
    "DISPLACEMENT": "displacement",
    "S": "stress",
    "STRESS": "stress",
    "E": "strain",
    "STRAIN": "strain",
    "EVOL": "volume",
    "VOLUME": "volume",
    "SENER": "strain_energy_density",
    "STRAIN_ENERGY_DENSITY": "strain_energy_density",
    "RF": "reaction_force",
    "REACTION_FORCE": "reaction_force",
    "ENER": "energy",
    "ENERGY": "energy",
}
_COMPONENT_INDEX = {
    "ux": 0,
    "uy": 1,
    "uz": 2,
    "u1": 0,
    "u2": 1,
    "u3": 2,
    "sxx": 0,
    "syy": 1,
    "szz": 2,
    "sxy": 3,
    "syz": 4,
    "sxz": 5,
    "s11": 0,
    "s22": 1,
    "s33": 2,
    "s12": 3,
    "s23": 4,
    "s13": 5,
    "rf1": 0,
    "rf2": 1,
    "rf3": 2,
}


def attach_case_result_fields(extracted: dict[str, Any], case: SimulationCase) -> dict[str, Any]:
    """按案例字段契约生成请求字段，并保留每个输出步的字段场。

    适配器提供原始求解器字段；本函数只做确定性的字段别名、分量和不变量
    计算，不改变原始场值。缺失的必需字段会使作业失败，避免界面展示不完整
    的“成功”结果。
    """

    # The case fingerprint travels with every adapter result.  A backend
    # comparison can therefore reject results produced from different input
    # contracts before it compares numerical fields.
    case_payload = case.model_dump(mode="json")
    extracted["case_digest"] = hashlib.sha256(
        json.dumps(case_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    extracted["case_schema_version"] = case.schema_version
    extracted["case_id"] = case.case_id or case.model.case_id
    extracted["units"] = case.units.model_dump(mode="json")
    extracted["coordinate_system"] = case.coordinate_system.model_dump(mode="json")

    raw_fields = extracted.get("fields")
    if not isinstance(raw_fields, Mapping):
        raw_fields = {}
    requested = _select_fields(raw_fields, case.result_fields)
    history = extracted.get("field_history")
    step_results: list[dict[str, Any]] = []
    if isinstance(history, list):
        named_groups: dict[str, list[dict[str, Any]]] = {}
        for frame in history:
            if isinstance(frame, Mapping) and isinstance(frame.get("step_name"), str):
                named_groups.setdefault(str(frame["step_name"]), []).append(dict(frame))
        if named_groups:
            ordered_steps = sorted(case.load_steps, key=lambda item: item.sequence)
            for index, (step_name, frames) in enumerate(named_groups.items()):
                step = next((item for item in ordered_steps if item.step_id == step_name), None)
                if step is None and index < len(ordered_steps):
                    step = ordered_steps[index]
                specs = _step_result_specs(case, step)
                fields_frames = [
                    _select_fields(
                        {
                            key: value
                            for key, value in frame.items()
                            if key in _QUANTITY_ALIASES.values()
                        },
                        specs,
                        required=True,
                    )
                    for frame in frames
                ]
                payload: dict[str, Any] = {
                    "step_name": step_name,
                    "frames": [
                        {"frame_index": frame.get("frame_index"), "fields": selected}
                        for frame, selected in zip(frames, fields_frames, strict=True)
                    ],
                    "fields": fields_frames[-1] if fields_frames else {},
                }
                if step is not None:
                    payload.update(
                        {
                            "step_id": step.step_id,
                            "sequence": step.sequence,
                        }
                    )
                step_results.append(payload)
        ordinal_groups: dict[int, list[dict[str, Any]]] = {}
        if not named_groups:
            for frame in history:
                if isinstance(frame, Mapping) and isinstance(frame.get("step_index"), int):
                    ordinal_groups.setdefault(int(frame["step_index"]), []).append(dict(frame))
        if ordinal_groups:
            ordered_steps = sorted(case.load_steps, key=lambda item: item.sequence)
            for index, (step_number, frames) in enumerate(sorted(ordinal_groups.items())):
                step = next(
                    (item for item in ordered_steps if item.sequence == step_number),
                    ordered_steps[index] if index < len(ordered_steps) else None,
                )
                specs = _step_result_specs(case, step)
                fields_frames = [
                    _select_fields(
                        {
                            key: value
                            for key, value in frame.items()
                            if key in _QUANTITY_ALIASES.values()
                        },
                        specs,
                        required=True,
                    )
                    for frame in frames
                ]
                payload = {
                    "step_index": step_number,
                    "frames": [
                        {
                            "frame_index": frame.get("frame_index", frame_index),
                            "fields": selected,
                        }
                        for frame_index, (frame, selected) in enumerate(
                            zip(frames, fields_frames, strict=True)
                        )
                    ],
                    "fields": fields_frames[-1] if fields_frames else {},
                }
                if step is not None:
                    payload.update({"step_id": step.step_id, "sequence": step.sequence})
                step_results.append(payload)
        for index, frame in enumerate(history):
            if named_groups or ordinal_groups:
                break
            if not isinstance(frame, Mapping):
                continue
            frame_fields = {
                key: value for key, value in frame.items() if key in _QUANTITY_ALIASES.values()
            }
            if index < len(case.load_steps):
                step = case.load_steps[index]
                selected = _select_fields(
                    frame_fields,
                    _step_result_specs(case, step),
                    required=True,
                )
                step_results.append(
                    {
                        "step_id": step.step_id,
                        "sequence": step.sequence,
                        "fields": selected,
                    }
                )
            else:
                selected = _select_fields(frame_fields, case.result_fields, required=False)
            if index >= len(case.load_steps) and selected:
                step_results.append({"step_index": index + 1, "fields": selected})
    if not step_results and len(case.load_steps) == 1:
        # A backend may expose only a final field map for a single-step run.
        # Keep the result contract complete without inventing additional
        # frames; multi-step runs are required to expose every declared step.
        step = case.load_steps[0]
        step_results = [
            {
                "step_id": step.step_id,
                "sequence": step.sequence,
                "fields": _select_fields(
                    raw_fields,
                    _step_result_specs(case, step),
                    required=True,
                ),
            }
        ]
    if len(case.load_steps) > 1:
        expected = {step.step_id for step in case.load_steps}
        actual = {
            str(item.get("step_id"))
            for item in step_results
            if isinstance(item, Mapping) and item.get("step_id") is not None
        }
        if len(step_results) != len(case.load_steps) or actual != expected:
            raise SolverError(
                "多步结果缺少完整分析步字段："
                f"需要 {len(case.load_steps)} 步，实际 {len(step_results)} 步。"
            )
    extracted["requested_fields"] = requested
    extracted["step_results"] = step_results
    # ``result_steps`` is the stable name for the selected, per-step contract;
    # ``step_results`` remains for compatibility with existing reports.
    extracted["result_steps"] = step_results
    return extracted


def attach_mapped_result_fields(extracted: dict[str, Any], case: SimulationCase) -> dict[str, Any]:
    """生成具有明确空间语义的跨工具单元场。

    后端 ``fields`` 保留求解器原生位置和标签。本函数只对能够由单元拓扑、
    节点坐标和原始场值确定映射的字段生成 ``mapped_fields``：正应力/正应变
    的第一分量、单元体积，以及实体单元的应变能密度。梁求解器的截面展开
    节点可以生成轴向截面平均值，但不会伪装成完整截面场。
    """

    elements = _normalise_elements(extracted.get("elements"))
    element_centroids = _normalise_coordinates(extracted.get("element_centroids"))
    if not elements or not element_centroids:
        return extracted
    fields = extracted.get("fields")
    if not isinstance(fields, Mapping):
        return extracted

    mapped: dict[str, Any] = {}
    for name, quantity, component in (
        ("stress_sxx", "stress", "sxx"),
        ("strain_exx", "strain", "exx"),
    ):
        field = fields.get(quantity)
        values = _map_field_to_elements(field, elements, extracted, component_index=0)
        if values:
            mapped[name] = {
                "quantity": quantity,
                "component": component,
                "location": "element_centroid",
                "unit": "MPa" if quantity == "stress" else "",
                "values": values,
                "mapping": "element-connectivity-mean-or-axis-station-mean",
            }

    volume = fields.get("volume")
    volume_values: dict[str, float | list[float]] = _map_field_to_elements(
        volume, elements, extracted
    )
    if not volume_values and case.model.geometry.type.value == "beam":
        volume_values = dict(_beam_element_volumes(elements, extracted, case))
    if volume_values:
        mapped["volume"] = {
            "quantity": "volume",
            "location": "element_centroid",
            "unit": "mm^3",
            "values": volume_values,
            "mapping": "element-label-or-connectivity",
        }

    # Abaqus exposes SENER at integration points; CalculiX exposes the same
    # quantity at nodes for solid meshes. Beam section values have different
    # conventions and remain outside this normalized field.
    if case.model.geometry.type.value != "beam":
        energy = fields.get("strain_energy_density")
        energy_values = _map_field_to_elements(energy, elements, extracted)
        if energy_values:
            mapped["strain_energy_density"] = {
                "quantity": "strain_energy_density",
                "location": "element_centroid",
                "unit": "N/mm^2",
                "values": energy_values,
                "mapping": "element-connectivity-mean-or-integration-point-mean",
            }

    if mapped:
        extracted["mapped_fields"] = mapped
        extracted["element_centroids"] = {
            str(label): list(point) for label, point in sorted(element_centroids.items())
        }
    return extracted


def _map_field_to_elements(
    field: Any,
    elements: dict[str, tuple[str, ...]],
    extracted: Mapping[str, Any],
    *,
    component_index: int | None = None,
) -> dict[str, float | list[float]]:
    if not isinstance(field, Mapping) or not isinstance(field.get("values"), Mapping):
        return {}
    values = {str(label): value for label, value in field["values"].items()}
    location = str(field.get("location", ""))
    if location in {"element", "integration_point"}:
        grouped: dict[str, list[Any]] = {}
        for label, value in values.items():
            grouped.setdefault(label.split("@", 1)[0], []).append(value)
        result: dict[str, float | list[float]] = {}
        for element_id in elements:
            items = grouped.get(element_id)
            if items:
                result[element_id] = _mean_field_values(items, component_index)
        return result
    if location != "node":
        return {}

    result = {}
    direct = all(node in values for nodes in elements.values() for node in nodes)
    if direct:
        for element_id, nodes in elements.items():
            result[element_id] = _mean_field_values(
                [values[node] for node in nodes], component_index
            )
        return result

    # Beam FRD files may replace the input centerline nodes with section nodes.
    # Average values at the nearest axial station and retain that limitation in
    # the mapping metadata rather than pairing unrelated node labels.
    coordinates = _normalise_coordinates(extracted.get("nodes"))
    centroids = _normalise_coordinates(extracted.get("element_centroids"))
    if not coordinates or not centroids:
        return {}
    axes = [
        max(point[index] for point in coordinates.values())
        - min(point[index] for point in coordinates.values())
        for index in range(3)
    ]
    axis = max(range(3), key=lambda index: axes[index])
    stations: dict[float, list[Any]] = {}
    for label, value in values.items():
        point = coordinates.get(label)
        if point is not None:
            stations.setdefault(round(point[axis], 8), []).append(value)
    if not stations:
        return {}
    result = {}
    for element_id in elements:
        point = centroids.get(element_id)
        if point is None:
            continue
        station = min(stations, key=lambda value: (abs(value - point[axis]), value))
        result[element_id] = _mean_field_values(stations[station], component_index)
    return result


def _mean_field_values(values: Sequence[Any], component_index: int | None) -> float | list[float]:
    if not values:
        raise ValueError("结果场不能为空。")
    vectors: list[list[float]] = []
    for value in values:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            vector = [float(item) for item in value]
        else:
            vector = [float(value)]
        if not all(math.isfinite(item) for item in vector):
            raise SolverError("结果场映射值必须是有限数字。")
        vectors.append(vector)
    width = len(vectors[0])
    if any(len(vector) != width for vector in vectors):
        raise SolverError("结果场映射的分量数量不一致。")
    mean = [sum(vector[index] for vector in vectors) / len(vectors) for index in range(width)]
    if component_index is not None:
        if component_index >= len(mean):
            raise SolverError("结果场映射缺少请求分量。")
        return mean[component_index]
    return mean[0] if width == 1 else mean


def _beam_element_volumes(
    elements: dict[str, tuple[str, ...]], extracted: Mapping[str, Any], case: SimulationCase
) -> dict[str, float]:
    # CalculiX keeps the original mesh coordinates under ``mesh_nodes`` while
    # Abaqus ODB extraction exposes the same topology as ``nodes``.  Both are
    # valid sources for the deterministic beam volume calculation.
    nodes = _normalise_coordinates(extracted.get("mesh_nodes")) or _normalise_coordinates(
        extracted.get("nodes")
    )
    dimensions = case.model.geometry.dimensions
    width = dimensions.get("width")
    height = dimensions.get("height")
    if not nodes or width is None or height is None:
        return {}
    area = float(width) * float(height)
    volumes: dict[str, float] = {}
    for element_id, connectivity in elements.items():
        points = [nodes[node] for node in connectivity if node in nodes]
        if len(points) != len(connectivity) or len(points) < 2:
            continue
        length = math.sqrt(sum((points[1][index] - points[0][index]) ** 2 for index in range(3)))
        volumes[element_id] = length * area
    return volumes


def _normalise_elements(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for label, nodes in value.items():
        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
            continue
        normalized = tuple(str(node) for node in nodes)
        if normalized:
            result[str(label)] = normalized
    return result


def _normalise_coordinates(value: Any) -> dict[str, tuple[float, float, float]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, tuple[float, float, float]] = {}
    for label, point in value.items():
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) != 3:
            continue
        coordinates = (float(point[0]), float(point[1]), float(point[2]))
        if all(math.isfinite(item) for item in coordinates):
            result[str(label)] = coordinates
    return result


def _step_result_specs(case: SimulationCase, step: LoadStepSpec | None) -> list[ResultFieldSpec]:
    """返回一个分析步声明的结果字段；空声明表示案例全部字段。"""

    if step is None or not step.result_fields:
        return list(case.result_fields)
    by_name = {spec.name: spec for spec in case.result_fields}
    return [by_name[name] for name in step.result_fields if name in by_name]


def _select_fields(
    fields: Mapping[str, Any], specs: Sequence[ResultFieldSpec], *, required: bool = True
) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for spec in specs:
        key = _QUANTITY_ALIASES.get(spec.quantity.strip().upper(), spec.quantity.strip().lower())
        raw = fields.get(key)
        if raw is None:
            if required and spec.required:
                raise SolverError(f"结果字段 {spec.name} 所需的 {spec.quantity} 场不存在。")
            continue
        if not isinstance(raw, Mapping) or not isinstance(raw.get("values"), Mapping):
            if required and spec.required:
                raise SolverError(f"结果字段 {spec.name} 的 {key} 场格式无效。")
            continue
        raw_location = str(raw.get("location", "")).strip()
        if raw_location and raw_location != spec.location:
            if required and spec.required:
                raise SolverError(
                    f"结果字段 {spec.name} 请求位置 {spec.location}，后端只提供 {raw_location}。"
                )
            continue
        values = raw["values"]
        selected[spec.name] = {
            "quantity": spec.quantity,
            "location": raw.get("location", spec.location),
            "unit": spec.unit or raw.get("unit", ""),
            "selector": spec.component or spec.invariant or "vector",
            "values": {
                str(label): _select_value(value, spec, key) for label, value in values.items()
            },
        }
        selected[spec.name]["summary"] = _summarize_values(selected[spec.name]["values"])
    return selected


def _summarize_values(values: Mapping[str, Any]) -> dict[str, float]:
    """生成跨网格比较使用的确定性标量摘要。"""

    numbers = [number for value in values.values() for number in _flatten_numeric(value)]
    if not numbers:
        return {"count": 0.0}
    return {
        "count": float(len(numbers)),
        "min": min(numbers),
        "max": max(numbers),
        "max_abs": max(abs(number) for number in numbers),
        "mean": sum(numbers) / len(numbers),
    }


def _flatten_numeric(value: Any) -> list[float]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [number for item in value for number in _flatten_numeric(item)]
    number = float(value)
    if not math.isfinite(number):
        raise SolverError("结果字段值必须是有限数字。")
    return [number]


def _select_value(value: Any, spec: ResultFieldSpec, quantity: str) -> float | list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        scalar = float(value)
        return scalar if spec.component or spec.invariant else scalar
    vector = [float(item) for item in value]
    if spec.component:
        index = _COMPONENT_INDEX.get(spec.component.strip().lower())
        if index is None or index >= len(vector):
            raise SolverError(f"结果字段 {spec.name} 的分量 {spec.component} 不受支持。")
        return vector[index]
    if spec.invariant == "magnitude":
        return math.sqrt(sum(item * item for item in vector))
    if spec.invariant == "trace":
        return sum(vector[index] for index in (0, 1, 2) if index < len(vector))
    if spec.invariant in {"max_principal", "min_principal", "tresca", "mises"}:
        if quantity == "stress" and len(vector) >= 6:
            sxx, syy, szz, sxy, syz, sxz = vector[:6]
            principal = _principal_stresses(sxx, syy, szz, sxy, syz, sxz)
            mean = sum(principal) / 3.0
            j2 = sum((value - mean) ** 2 for value in principal) / 2.0
            mises = math.sqrt(max(0.0, 3.0 * j2))
            if spec.invariant == "mises":
                return mises
            if spec.invariant == "tresca":
                return principal[0] - principal[2]
            return principal[0] if spec.invariant == "max_principal" else principal[2]
        raise SolverError(f"结果字段 {spec.name} 的 {spec.invariant} 需要六分量应力场。")
    return vector


def _principal_stresses(
    sxx: float, syy: float, szz: float, sxy: float, syz: float, sxz: float
) -> tuple[float, float, float]:
    """返回对称三维应力张量的降序主应力。"""

    mean = (sxx + syy + szz) / 3.0
    a = sxx - mean
    b = syy - mean
    c = szz - mean
    p = math.sqrt(
        max(0.0, (a * a + b * b + c * c + 2.0 * (sxy * sxy + syz * syz + sxz * sxz)) / 6.0)
    )
    if p <= 1.0e-15:
        return (mean, mean, mean)
    det = a * (b * c - syz * syz) - sxy * (sxy * c - syz * sxz) + sxz * (sxy * syz - b * sxz)
    r = max(-1.0, min(1.0, det / (2.0 * p**3)))
    angle = math.acos(r) / 3.0
    root = 2.0 * p
    values = (
        mean + root * math.cos(angle),
        mean + root * math.cos(angle - 2.0 * math.pi / 3.0),
        mean + root * math.cos(angle - 4.0 * math.pi / 3.0),
    )
    ordered = sorted(values, reverse=True)
    return (ordered[0], ordered[1], ordered[2])

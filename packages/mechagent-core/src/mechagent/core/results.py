"""统一结果场字段选择与逐步结果归档。"""

from __future__ import annotations

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
        for index, frame in enumerate(history):
            if named_groups:
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
                    required=False,
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
    extracted["requested_fields"] = requested
    if step_results:
        extracted["step_results"] = step_results
    return extracted


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

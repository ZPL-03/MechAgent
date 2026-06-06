"""仿真结果评价器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mechagent.core.models import GeometryType, LoadType, ModelParams
from mechagent.core.validation import (
    axial_bar_end_displacement,
    cantilever_tip_deflection,
    cantilever_uniform_load_tip_deflection,
    simply_supported_plate_center_deflection,
    solver_result_succeeded,
)


@dataclass(frozen=True)
class ResultEvaluationContext:
    """结果评价上下文。

    Args:
        model_params: 求解使用的结构化参数。
        solver_result: 求解器输出字典。
        solver_name: 求解器名称。
        task_case_id: Planner 生成的任务类别编号。
        task_title: Planner 生成的任务标题。

    Returns:
        ResultEvaluationContext: 结果评价输入。

    Raises:
        TypeError: 当字段类型不匹配时由 dataclass 构造阶段抛出。
    """

    model_params: ModelParams
    solver_result: dict[str, Any]
    solver_name: str
    task_case_id: str
    task_title: str


ResultEvaluator = Callable[[ResultEvaluationContext], dict[str, Any]]


def evaluate_structural_static_result(context: ResultEvaluationContext) -> dict[str, Any]:
    """评价结构静力求解结果。

    Args:
        context: 结果评价上下文。

    Returns:
        dict[str, Any]: 带参考值、误差和验收状态的结果字典。

    Raises:
        ValueError: 当几何类型或载荷工况无法评价时抛出。
        KeyError: 当求解结果缺少必要标量时抛出。
    """

    model_params = context.model_params
    if model_params.geometry.type is GeometryType.BEAM:
        return _evaluate_static_beam_case(context)
    if model_params.geometry.type is GeometryType.PLATE:
        return _evaluate_static_plate_case(context)
    if model_params.geometry.type is GeometryType.SOLID:
        return _evaluate_static_solid_case(context)

    msg = f"结构静力结果评价不支持几何类型: {model_params.geometry.type.value}。"
    raise ValueError(msg)


def _evaluate_static_beam_case(context: ResultEvaluationContext) -> dict[str, Any]:
    model_params = context.model_params
    solver_result = context.solver_result
    dimensions = model_params.geometry.dimensions
    predicted = float(solver_result["tip_deflection_mm"])
    if model_params.load_case == "cantilever_uniform_line_load":
        reference = cantilever_uniform_load_tip_deflection(
            _first_load_magnitude(model_params, LoadType.LINE_LOAD),
            dimensions["length"],
            model_params.material.E,
            dimensions["width"],
            dimensions["height"],
        )
        tolerance = 0.02
    elif model_params.load_case == "cantilever_tip_force":
        reference = cantilever_tip_deflection(
            _first_load_magnitude(model_params, LoadType.FORCE),
            dimensions["length"],
            model_params.material.E,
            dimensions["width"],
            dimensions["height"],
        )
        tolerance = 0.01
    else:
        return _unreferenced_result(
            context,
            predicted=predicted,
            quantity="tip_deflection",
            unit="mm",
        )

    return _referenced_result(
        context,
        predicted=predicted,
        reference=reference,
        tolerance=tolerance,
        quantity="tip_deflection",
        unit="mm",
    )


def _evaluate_static_plate_case(context: ResultEvaluationContext) -> dict[str, Any]:
    model_params = context.model_params
    solver_result = context.solver_result
    dimensions = model_params.geometry.dimensions
    predicted = float(solver_result["center_deflection_mm"])
    if model_params.load_case != "simply_supported_pressure":
        return _unreferenced_result(
            context,
            predicted=predicted,
            quantity="center_deflection",
            unit="mm",
        )

    reference = simply_supported_plate_center_deflection(
        _first_load_magnitude(model_params, LoadType.PRESSURE),
        dimensions["length"],
        dimensions["width"],
        dimensions["thickness"],
        model_params.material.E,
        model_params.material.nu,
        terms=151,
    )
    return _referenced_result(
        context,
        predicted=predicted,
        reference=reference,
        tolerance=0.02,
        quantity="center_deflection",
        unit="mm",
    )


def _evaluate_static_solid_case(context: ResultEvaluationContext) -> dict[str, Any]:
    model_params = context.model_params
    solver_result = context.solver_result
    predicted = float(solver_result.get("axial_displacement_mm", solver_result["max_abs_u1_mm"]))
    if model_params.load_case not in {
        "fixed_solid_axial_pressure",
        "fixed_solid_axial_force",
    }:
        return _unreferenced_result(
            context,
            predicted=predicted,
            quantity="axial_displacement",
            unit="mm",
        )

    dimensions = model_params.geometry.dimensions
    reference = axial_bar_end_displacement(
        _solid_axial_load(model_params),
        dimensions["length"],
        dimensions["width"] * dimensions["height"],
        model_params.material.E,
    )
    return _referenced_result(
        context,
        predicted=predicted,
        reference=reference,
        tolerance=0.08,
        quantity="axial_displacement",
        unit="mm",
    )


def _referenced_result(
    context: ResultEvaluationContext,
    *,
    predicted: float,
    reference: float,
    tolerance: float,
    quantity: str,
    unit: str,
) -> dict[str, Any]:
    relative_error = abs(predicted - reference) / abs(reference)
    solver_success = solver_result_succeeded(context.solver_result)
    passed = solver_success and relative_error <= tolerance
    return {
        **context.solver_result,
        "model_case_id": context.model_params.case_id or context.task_case_id,
        "reference": reference,
        "predicted": predicted,
        "relative_error": relative_error,
        "tolerance": tolerance,
        "passed": passed,
        "verification_status": "passed" if passed else "failed",
        "quantity": quantity,
        "unit": unit,
        "solver": context.solver_name,
        "task_title": context.task_title,
    }


def _unreferenced_result(
    context: ResultEvaluationContext,
    *,
    predicted: float,
    quantity: str,
    unit: str,
) -> dict[str, Any]:
    verification_status = (
        "unverified" if solver_result_succeeded(context.solver_result) else "failed"
    )
    return {
        **context.solver_result,
        "model_case_id": context.model_params.case_id or context.task_case_id,
        "predicted": predicted,
        "passed": False,
        "verification_status": verification_status,
        "quantity": quantity,
        "unit": unit,
        "solver": context.solver_name,
        "task_title": context.task_title,
    }


def _first_load_magnitude(model_params: ModelParams, load_type: LoadType) -> float:
    for load in model_params.loads:
        if load.type is load_type:
            return abs(load.magnitude)
    msg = f"模型缺少 {load_type.value} 载荷。"
    raise ValueError(msg)


def _solid_axial_load(model_params: ModelParams) -> float:
    dimensions = model_params.geometry.dimensions
    area = dimensions["width"] * dimensions["height"]
    for load in model_params.loads:
        if load.type is LoadType.PRESSURE:
            return abs(load.magnitude) * area
        if load.type is LoadType.FORCE:
            return abs(load.magnitude)
    msg = "实体轴向位移参考解需要 pressure 或 force 载荷。"
    raise ValueError(msg)

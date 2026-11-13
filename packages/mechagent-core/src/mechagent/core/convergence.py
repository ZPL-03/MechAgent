"""网格独立性与收敛报告契约。"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConvergencePoint(BaseModel):
    """一个网格尺寸对应的可复核标量结果。"""

    model_config = ConfigDict(extra="forbid")

    seed_size: float = Field(gt=0.0)
    value: float
    node_count: int = Field(ge=1)
    element_count: int = Field(ge=1)
    relative_change: float | None = Field(default=None, ge=0.0)
    reference_error: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _finite_values(self) -> "ConvergencePoint":
        values = (self.seed_size, self.value, self.relative_change, self.reference_error)
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("收敛点必须包含有限数值。")
        return self


class MeshConvergenceReport(BaseModel):
    """单个案例的网格收敛判定。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, frozen=True)
    case_id: str = Field(min_length=1)
    quantity: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    reference: float | None = None
    stabilization_tolerance: float = Field(gt=0.0)
    reference_tolerance: float | None = Field(default=None, ge=0.0)
    points: list[ConvergencePoint] = Field(min_length=2)
    status: Literal["passed", "failed", "unverified"]
    failure_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_report(self) -> "MeshConvergenceReport":
        if self.reference is not None and not math.isfinite(self.reference):
            raise ValueError("收敛报告 reference 必须是有限数值。")
        if self.reference_tolerance is not None and self.reference is None:
            raise ValueError("设置 reference_tolerance 时必须提供 reference。")
        sizes = [point.seed_size for point in self.points]
        if any(
            next_size >= current_size
            for current_size, next_size in zip(sizes, sizes[1:], strict=False)
        ):
            raise ValueError("收敛点必须按 seed_size 严格递减排列。")
        if self.status == "passed" and self.failure_reasons:
            raise ValueError("passed 收敛报告不能包含 failure_reasons。")
        return self


def evaluate_mesh_convergence(
    *,
    case_id: str,
    quantity: str,
    unit: str,
    values: list[tuple[float, float, int, int]],
    stabilization_tolerance: float,
    reference: float | None = None,
    reference_tolerance: float | None = None,
) -> MeshConvergenceReport:
    """按逐级网格结果计算收敛状态。

    ``values`` 必须按从粗到细的顺序提供 ``(seed_size, value, nodes, elements)``。
    终点只有同时满足相邻两级变化阈值和参考误差阈值时才会判定为 ``passed``；
    没有参考值时状态为 ``unverified``；稳定变化和工程参考验收分别记录。
    """

    if not math.isfinite(stabilization_tolerance) or stabilization_tolerance <= 0:
        raise ValueError("stabilization_tolerance 必须是正有限数值。")
    if reference_tolerance is not None and (
        reference is None or not math.isfinite(reference_tolerance) or reference_tolerance < 0
    ):
        raise ValueError("reference_tolerance 必须与有限 reference 一起提供。")
    if len(values) < 2:
        raise ValueError("至少需要两个网格尺寸才能计算收敛。")
    points: list[ConvergencePoint] = []
    failures: list[str] = []
    previous: float | None = None
    for seed_size, value, node_count, element_count in values:
        point = ConvergencePoint(
            seed_size=seed_size,
            value=value,
            node_count=node_count,
            element_count=element_count,
            relative_change=(
                None
                if previous is None
                else abs(value - previous) / max(abs(value), abs(previous), 1.0e-15)
            ),
            reference_error=(
                None if reference is None else abs(value - reference) / max(abs(reference), 1.0e-15)
            ),
        )
        points.append(point)
        previous = value
    final_change = points[-1].relative_change
    if final_change is None or final_change > stabilization_tolerance:
        failures.append(
            f"终点相邻网格相对变化 {final_change!r} 超过 {stabilization_tolerance:.6g}。"
        )
    final_error = points[-1].reference_error
    status: Literal["passed", "failed", "unverified"]
    if reference is None:
        status = "unverified" if not failures else "failed"
    else:
        if reference_tolerance is None:
            raise ValueError("提供 reference 时必须提供 reference_tolerance。")
        if final_error is None or final_error > reference_tolerance:
            failures.append(f"终点参考相对误差 {final_error!r} 超过 {reference_tolerance:.6g}。")
        status = "passed" if not failures else "failed"
    return MeshConvergenceReport(
        case_id=case_id,
        quantity=quantity,
        unit=unit,
        reference=reference,
        stabilization_tolerance=stabilization_tolerance,
        reference_tolerance=reference_tolerance,
        points=points,
        status=status,
        failure_reasons=failures,
    )

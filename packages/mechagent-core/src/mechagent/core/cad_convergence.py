"""CAD 直接网格的独立性证据契约。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CADMeshConvergenceRun(BaseModel):
    """一个 CAD 网格尺寸的可复核运行记录。"""

    model_config = ConfigDict(extra="forbid")

    seed_size: float = Field(gt=0.0)
    value: float
    node_count: int = Field(ge=1)
    element_count: int = Field(ge=1)
    quality_metric: str = Field(min_length=1)
    min_quality: float = Field(ge=0.0)
    quality_threshold: float = Field(ge=0.0)
    mesh_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    topology_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    region_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    region_node_counts: dict[str, int] = Field(min_length=1)
    solver_success: bool
    relative_change: float | None = Field(default=None, ge=0.0)
    reference_error: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _finite_values(self) -> "CADMeshConvergenceRun":
        values = (self.seed_size, self.value, self.min_quality, self.quality_threshold)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("CAD 网格收敛运行必须包含有限数值。")
        if any(count < 1 for count in self.region_node_counts.values()):
            raise ValueError("CAD 区域节点集合必须包含至少一个节点。")
        if self.relative_change is not None and not math.isfinite(self.relative_change):
            raise ValueError("CAD 网格收敛运行的 relative_change 必须是有限数值。")
        if self.reference_error is not None and not math.isfinite(self.reference_error):
            raise ValueError("CAD 网格收敛运行的 reference_error 必须是有限数值。")
        return self


class CADMeshConvergenceReport(BaseModel):
    """同一 CAD 来源和区域契约下的网格独立性判定。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, frozen=True)
    case_id: str = Field(min_length=1)
    quantity: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    solver: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    topology_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    region_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    stabilization_tolerance: float = Field(gt=0.0)
    quality_threshold: float = Field(ge=0.0)
    reference: float | None = None
    reference_tolerance: float | None = Field(default=None, ge=0.0)
    runs: list[CADMeshConvergenceRun] = Field(min_length=2)
    status: Literal["passed", "failed", "unverified"]
    failure_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_report(self) -> "CADMeshConvergenceReport":
        if self.reference is not None and not math.isfinite(self.reference):
            raise ValueError("CAD 收敛报告 reference 必须是有限数值。")
        if self.reference_tolerance is not None and self.reference is None:
            raise ValueError("设置 reference_tolerance 时必须提供 reference。")
        sizes = [run.seed_size for run in self.runs]
        if any(left <= right for left, right in zip(sizes, sizes[1:], strict=False)):
            raise ValueError("CAD 收敛运行必须按 seed_size 严格递减排列。")
        identities = {
            (run.source_sha256, run.topology_digest, run.region_contract_digest)
            for run in self.runs
        }
        if len(identities) != 1:
            raise ValueError("CAD 收敛运行必须使用同一源文件、拓扑摘要和区域契约。")
        if self.status == "passed" and self.failure_reasons:
            raise ValueError("passed CAD 收敛报告不能包含 failure_reasons。")
        return self


def region_contract_digest(regions: Mapping[str, object]) -> str:
    """为案例区域契约生成稳定摘要。"""

    payload = json.dumps(regions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evaluate_cad_mesh_convergence(
    *,
    case_id: str,
    quantity: str,
    unit: str,
    solver: str,
    source_sha256: str,
    topology_digest: str,
    region_contract_digest: str,
    runs: list[CADMeshConvergenceRun],
    stabilization_tolerance: float,
    quality_threshold: float,
    reference: float | None = None,
    reference_tolerance: float | None = None,
) -> CADMeshConvergenceReport:
    """计算 CAD 网格收敛状态并验证跨尺寸身份和质量门禁。"""

    if not _SHA256.fullmatch(source_sha256):
        raise ValueError("source_sha256 必须是小写 SHA-256。")
    if not _SHA256.fullmatch(topology_digest):
        raise ValueError("topology_digest 必须是小写 SHA-256。")
    if not _SHA256.fullmatch(region_contract_digest):
        raise ValueError("region_contract_digest 必须是小写 SHA-256。")
    if not math.isfinite(stabilization_tolerance) or stabilization_tolerance <= 0:
        raise ValueError("stabilization_tolerance 必须是正有限数值。")
    if not math.isfinite(quality_threshold) or quality_threshold < 0:
        raise ValueError("quality_threshold 必须是非负有限数值。")
    if reference_tolerance is not None and (
        reference is None or not math.isfinite(reference_tolerance) or reference_tolerance < 0
    ):
        raise ValueError("reference_tolerance 必须与有限 reference 一起提供。")
    if len(runs) < 2:
        raise ValueError("至少需要两个 CAD 网格尺寸才能计算收敛。")

    previous: float | None = None
    normalized: list[CADMeshConvergenceRun] = []
    failures: list[str] = []
    for index, run in enumerate(runs, start=1):
        if run.source_sha256 != source_sha256:
            failures.append(f"运行 {index} 的源文件摘要不一致。")
        if run.topology_digest != topology_digest:
            failures.append(f"运行 {index} 的拓扑摘要不一致。")
        if run.region_contract_digest != region_contract_digest:
            failures.append(f"运行 {index} 的区域契约摘要不一致。")
        if run.quality_threshold != quality_threshold:
            failures.append(f"运行 {index} 的质量阈值不一致。")
        if not run.solver_success:
            failures.append(f"运行 {index} 的求解状态失败。")
        if run.min_quality < quality_threshold:
            failures.append(
                f"运行 {index} 的 {run.quality_metric} {run.min_quality:.6g} "
                f"低于阈值 {quality_threshold:.6g}。"
            )
        relative_change = (
            None
            if previous is None
            else abs(run.value - previous) / max(abs(run.value), abs(previous), 1.0e-15)
        )
        reference_error = (
            None if reference is None else abs(run.value - reference) / max(abs(reference), 1.0e-15)
        )
        normalized.append(
            run.model_copy(
                update={"relative_change": relative_change, "reference_error": reference_error}
            )
        )
        previous = run.value

    final_change = normalized[-1].relative_change
    if final_change is None or final_change > stabilization_tolerance:
        failures.append(
            f"终点相邻网格相对变化 {final_change!r} 超过 {stabilization_tolerance:.6g}。"
        )
    final_error = normalized[-1].reference_error
    if reference is None:
        status: Literal["passed", "failed", "unverified"] = (
            "unverified" if not failures else "failed"
        )
    else:
        if reference_tolerance is None:
            raise ValueError("提供 reference 时必须提供 reference_tolerance。")
        if final_error is None or final_error > reference_tolerance:
            failures.append(f"终点参考相对误差 {final_error!r} 超过 {reference_tolerance:.6g}。")
        status = "passed" if not failures else "failed"
    return CADMeshConvergenceReport(
        case_id=case_id,
        quantity=quantity,
        unit=unit,
        solver=solver,
        source_sha256=source_sha256,
        topology_digest=topology_digest,
        region_contract_digest=region_contract_digest,
        stabilization_tolerance=stabilization_tolerance,
        quality_threshold=quality_threshold,
        reference=reference,
        reference_tolerance=reference_tolerance,
        runs=normalized,
        status=status,
        failure_reasons=failures,
    )

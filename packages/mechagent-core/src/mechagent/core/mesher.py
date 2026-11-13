"""网格器抽象接口。"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mechagent.core.models import ModelParams
from mechagent.core.regions import canonical_region_name


class MeshConfig(BaseModel):
    """网格器运行配置。

    Args:
        work_dir: 网格输出目录。
        seed_size: 全局网格种子尺寸，单位为 mm。
        min_quality: 最小网格质量阈值。
        healing: CAD 直接网格是否在导入后执行 Gmsh OCC 修复；参数化网格器忽略该字段。

    Returns:
        MeshConfig: 经过校验的网格器配置。

    Raises:
        pydantic.ValidationError: 当字段不满足类型或范围约束时抛出。

    Example:
        >>> MeshConfig(work_dir="mechagent_output", seed_size=5)
        MeshConfig(...)
    """

    model_config = ConfigDict(extra="forbid")

    work_dir: Path = Field(default=Path("mechagent_output"))
    seed_size: float = Field(default=5.0, gt=0)
    min_quality: float = Field(default=0.3, ge=0, le=1)
    healing: bool = True

    @field_validator("seed_size", "min_quality")
    @classmethod
    def _numeric_config_values_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "网格器数值配置必须是有限数值。"
            raise ValueError(msg)
        return value


class MeshQualityGate(BaseModel):
    """网格质量门禁的结构化结果。"""

    model_config = ConfigDict(extra="forbid")

    threshold: float = Field(ge=0.0, le=1.0)
    lower_bound_metrics: list[str] = Field(default_factory=list)
    status: Literal["passed", "failed"]

    @field_validator("threshold")
    @classmethod
    def _threshold_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("网格质量门禁阈值必须是有限数值。")
        return value


class MeshLocalSizeProvenance(BaseModel):
    """已应用的 CAD 局部尺寸场及其拓扑绑定。"""

    model_config = ConfigDict(extra="forbid")

    region: str = Field(min_length=1, max_length=128)
    topology_ids: list[str] = Field(min_length=1, max_length=4096)
    topology_dimensions: list[Literal[1, 2]] = Field(min_length=1, max_length=4096)
    size_mm: float = Field(gt=0.0)
    distance_mm: float = Field(gt=0.0)

    @field_validator("size_mm", "distance_mm")
    @classmethod
    def _local_size_values_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("局部网格尺寸和影响距离必须是有限数值。")
        return value

    @model_validator(mode="after")
    def _distance_must_cover_size(self) -> "MeshLocalSizeProvenance":
        if self.distance_mm < self.size_mm:
            raise ValueError("局部尺寸场影响距离不能小于目标尺寸。")
        return self


class MeshProvenance(BaseModel):
    """成功网格的输入、输出和门禁摘要。

    该对象只记录可由网格器和 MeshAgent 直接核验的事实；网格收敛、
    CAD 修复报告和跨网格器等价性不属于此对象的证明范围。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    case_id: str = Field(default="", max_length=128)
    geometry_type: str = Field(min_length=1, max_length=64)
    mesher: str = Field(min_length=1, max_length=128)
    seed_size_mm: float = Field(gt=0.0)
    element_type: str = Field(min_length=1, max_length=32)
    mesh_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_metrics: dict[str, float] = Field(default_factory=dict)
    quality_gate: MeshQualityGate
    region_names: list[str] = Field(default_factory=list, max_length=4096)
    cad_source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    topology_digest: str | None = Field(default=None, max_length=128)
    local_size_fields: list[MeshLocalSizeProvenance] = Field(
        default_factory=list,
        max_length=128,
    )
    solid_count: int = Field(default=1, ge=1)
    part_ids: list[str] = Field(default_factory=list, max_length=4096)
    connection_semantics: Literal["single_part", "unconnected_parts"] = "single_part"

    @model_validator(mode="after")
    def _local_size_fields_are_consistent(self) -> "MeshProvenance":
        names: set[str] = set()
        for item in self.local_size_fields:
            region = canonical_region_name(item.region)
            if not region:
                raise ValueError("MeshProvenance.local_size_fields.region 不能是空白字符串。")
            if region in names:
                raise ValueError("MeshProvenance.local_size_fields.region 不能重复。")
            names.add(region)
            if item.size_mm > self.seed_size_mm:
                raise ValueError("MeshProvenance.local_size_fields.size_mm 不能大于 seed_size_mm。")
            if len(set(item.topology_ids)) != len(item.topology_ids):
                raise ValueError("MeshProvenance.local_size_fields.topology_ids 不能包含重复值。")
            if any(not topology_id.strip() for topology_id in item.topology_ids):
                raise ValueError("MeshProvenance.local_size_fields.topology_ids 不能包含空白值。")
            if len(set(item.topology_dimensions)) != len(item.topology_dimensions):
                raise ValueError("MeshProvenance.local_size_fields.topology_dimensions 不能重复。")
        return self

    @field_validator("seed_size_mm")
    @classmethod
    def _seed_size_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("MeshProvenance.seed_size_mm 必须是有限数值。")
        return value

    @field_validator("quality_metrics")
    @classmethod
    def _quality_metrics_must_be_finite(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(metric) for metric in value.values()):
            raise ValueError("MeshProvenance.quality_metrics 必须全部是有限数值。")
        return value


class MeshResult(BaseModel):
    """网格生成结果。

    Args:
        success: 网格是否生成成功。
        mesh_file: 主网格文件路径。
        quality: 网格质量指标。
        metadata: 附加网格信息。
        error_message: 失败诊断信息。

    Returns:
        MeshResult: 统一网格结果对象。

    Raises:
        pydantic.ValidationError: 当结果字段不满足 schema 时抛出。

    Example:
        >>> MeshResult(success=True, mesh_file="model.inp", quality={"min_jacobian": 0.8})
        MeshResult(...)
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    mesh_file: Optional[Path] = None
    quality: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: MeshProvenance | None = None
    error_message: Optional[str] = None


class AbstractMesher(ABC):
    """所有网格器适配器必须实现的抽象基类。

    Args:
        config: 网格器配置。

    Returns:
        AbstractMesher: 具体网格器实例。

    Raises:
        OSError: 当工作目录无法创建时抛出。

    Example:
        >>> class MyMesher(AbstractMesher):
        ...     def generate(self, model_params): return MeshResult(success=True)
    """

    def __init__(self, config: MeshConfig) -> None:
        self.config = config
        self.config.work_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def generate(self, model_params: ModelParams) -> MeshResult:
        """生成网格。

        Args:
            model_params: 结构化仿真参数。

        Returns:
            MeshResult: 网格生成结果。

        Raises:
            MeshError: 当网格生成失败时抛出。

        Example:
            >>> mesher.generate(model_params)
            MeshResult(success=True, ...)
        """

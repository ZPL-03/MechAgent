"""CAD 内核抽象接口。

定义把外部 CAD 形体（STEP/IGES/BREP 等）导入、修复、特征识别并归纳为可求解几何摘要的
统一契约。具体内核（如基于 OpenCASCADE 的实现）通过工厂注册名、构造函数和配置接入，
与求解器、网格器保持一致的注册/工厂/配置模式。
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mechagent.core.exceptions import CADError
from mechagent.core.models import GeometryType


class CADConfig(BaseModel):
    """CAD 内核运行配置。

    Args:
        work_dir: 几何处理输出目录。
        linear_deflection: 离散化线性弦高，单位为 mm。
        min_feature_size: 去特征阈值，单位为 mm；为 0 时不去特征。
        healing: 是否在导入后执行几何修复。

    Returns:
        CADConfig: 经过校验的 CAD 内核配置。

    Raises:
        pydantic.ValidationError: 当字段不满足类型或范围约束时抛出。

    Example:
        >>> CADConfig(work_dir="mechagent_output", linear_deflection=0.1)
        CADConfig(...)
    """

    model_config = ConfigDict(extra="forbid")

    work_dir: Path = Field(default=Path("mechagent_output"))
    linear_deflection: float = Field(default=0.1, gt=0)
    min_feature_size: float = Field(default=0.0, ge=0)
    healing: bool = Field(default=True)

    @field_validator("linear_deflection", "min_feature_size")
    @classmethod
    def _numeric_config_values_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "CAD 内核数值配置必须是有限数值。"
            raise ValueError(msg)
        return value


class CADGeometryFeature(BaseModel):
    """CAD 几何特征。

    Args:
        kind: 特征类型，例如 ``hole``、``fillet``、``chamfer``、``boss``、``face``。
        feature_id: 特征在内核中的稳定标识。
        dimensions: 特征关键尺寸，单位为 mm。
        location: 特征参考点坐标，单位为 mm。

    Returns:
        CADGeometryFeature: 单点定义的几何特征。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> CADGeometryFeature(kind="hole", feature_id="H1", dimensions={"diameter": 12.0})
        CADGeometryFeature(...)
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    feature_id: str
    dimensions: dict[str, float] = Field(default_factory=dict)
    location: Optional[tuple[float, float, float]] = None


class CADGeometrySummary(BaseModel):
    """CAD 几何摘要。

    Args:
        source_format: 来源格式，例如 ``step``、``iges``、``brep``。
        units: 几何单位，默认 ``mm``。
        bbox_min: 包围盒最小角点坐标。
        bbox_max: 包围盒最大角点坐标。
        volume: 体积，单位为 mm^3。
        surface_area: 表面积，单位为 mm^2。
        solid_count: 实体数量。
        face_count: 面数量。
        edge_count: 边数量。
        watertight: 形体是否封闭水密。
        features: 识别出的几何特征列表。

    Returns:
        CADGeometrySummary: 统一几何摘要，供边界/载荷区域映射与网格策略消费。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> CADGeometrySummary(
        ...     source_format="step",
        ...     bbox_min=(0.0, 0.0, 0.0),
        ...     bbox_max=(100.0, 20.0, 20.0),
        ...     volume=40000.0,
        ...     surface_area=9600.0,
        ...     solid_count=1,
        ...     face_count=6,
        ...     edge_count=12,
        ... )
        CADGeometrySummary(...)
    """

    model_config = ConfigDict(extra="forbid")

    source_format: str
    units: str = "mm"
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    volume: float = Field(ge=0)
    surface_area: float = Field(ge=0)
    solid_count: int = Field(ge=0)
    face_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    watertight: bool = True
    features: list[CADGeometryFeature] = Field(default_factory=list)

    @field_validator("volume", "surface_area")
    @classmethod
    def _measures_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "CAD 几何度量必须是有限数值。"
            raise ValueError(msg)
        return value


class CADImportResult(BaseModel):
    """CAD 导入结果。

    Args:
        success: 导入与修复是否成功。
        summary: 成功时的几何摘要。
        geometry_file: 修复或标准化后导出的几何文件路径。
        wall_time: 处理耗时，单位为 s。
        metadata: 附加诊断信息，例如修复告警、去特征统计。
        error_message: 失败诊断信息。

    Returns:
        CADImportResult: 统一 CAD 导入结果对象。

    Raises:
        pydantic.ValidationError: 当结果字段不满足 schema 时抛出。

    Example:
        >>> CADImportResult(success=False, wall_time=0.0, error_message="不支持的格式")
        CADImportResult(...)
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    summary: Optional[CADGeometrySummary] = None
    geometry_file: Optional[Path] = None
    wall_time: float = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None

    @field_validator("wall_time")
    @classmethod
    def _wall_time_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "cad.wall_time 必须是有限数值。"
            raise ValueError(msg)
        return value


class AbstractCADKernel(ABC):
    """所有 CAD 内核适配器必须实现的抽象基类。

    ``import_model()`` 是固定模板方法，按 ``load -> repair -> summarize`` 顺序执行；
    子类只实现形体加载、修复和摘要归纳。硬失败通过抛出 ``CADError`` 表达，模板捕获后
    返回 ``success=False`` 的结果对象。

    Args:
        config: CAD 内核配置。

    Returns:
        AbstractCADKernel: 具体 CAD 内核实例。

    Raises:
        TypeError: 当子类定义与模板方法冲突的 import_model 时抛出。

    Example:
        >>> class MyKernel(AbstractCADKernel):
        ...     def load(self, source): return source
        ...     def repair(self, shape): return shape
        ...     def summarize(self, shape):
        ...         return CADGeometrySummary(
        ...             source_format="step",
        ...             bbox_min=(0.0, 0.0, 0.0),
        ...             bbox_max=(1.0, 1.0, 1.0),
        ...             volume=1.0,
        ...             surface_area=6.0,
        ...             solid_count=1,
        ...             face_count=6,
        ...             edge_count=12,
        ...         )
    """

    config: CADConfig

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "import_model" in cls.__dict__:
            msg = "AbstractCADKernel.import_model() 是固定模板方法，子类只实现加载、修复和摘要。"
            raise TypeError(msg)

    def __init__(self, config: CADConfig) -> None:
        self.config = config
        self.config.work_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def load(self, source: Path) -> Any:
        """加载 CAD 形体。

        Args:
            source: CAD 文件路径。

        Returns:
            Any: 内核私有的形体句柄。

        Raises:
            CADError: 当格式不受支持或文件无法解析时抛出。

        Example:
            >>> kernel.load(Path("bracket.step"))
            <shape ...>
        """

    @abstractmethod
    def repair(self, shape: Any) -> Any:
        """修复形体，例如缝合面、修复自由边和移除微小特征。

        Args:
            shape: 内核形体句柄。

        Returns:
            Any: 修复后的形体句柄。

        Raises:
            CADError: 当修复失败时抛出。

        Example:
            >>> kernel.repair(shape)
            <shape ...>
        """

    @abstractmethod
    def summarize(self, shape: Any) -> CADGeometrySummary:
        """归纳形体的几何摘要与特征。

        Args:
            shape: 内核形体句柄。

        Returns:
            CADGeometrySummary: 统一几何摘要。

        Raises:
            CADError: 当几何度量或特征识别失败时抛出。

        Example:
            >>> kernel.summarize(shape)
            CADGeometrySummary(...)
        """

    def import_model(self, source: Path) -> CADImportResult:
        """按固定模板执行 CAD 导入流程。

        Args:
            source: CAD 文件路径。

        Returns:
            CADImportResult: 统一 CAD 导入结果；硬失败返回 ``success=False``。

        Raises:
            无：硬失败以 ``CADError`` 捕获后写入结果，不向上层抛出。

        Example:
            >>> kernel.import_model(Path("bracket.step"))
            CADImportResult(success=True, ...)
        """

        start = time.perf_counter()
        try:
            shape = self.load(source)
            if self.config.healing:
                shape = self.repair(shape)
            summary = self.summarize(shape)
        except CADError as exc:
            return CADImportResult(
                success=False,
                wall_time=time.perf_counter() - start,
                error_message=str(exc),
            )
        return CADImportResult(
            success=True,
            summary=summary,
            wall_time=time.perf_counter() - start,
        )


class RegionCandidate(BaseModel):
    """边界/载荷区域候选。

    由几何包围盒的六个面派生，供边界条件与载荷区域映射使用。

    Args:
        name: 区域名称，例如 ``x_min``、``z_max``。
        axis: 法向轴，``x`` / ``y`` / ``z``。
        side: 端面方位，``min`` / ``max``。
        center: 面中心坐标，单位为 mm。
        area: 面面积，单位为 mm^2。

    Returns:
        RegionCandidate: 单点定义的区域候选。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> RegionCandidate(name="x_min", axis="x", side="min", center=(0.0, 10.0, 10.0), area=400)
        RegionCandidate(...)
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    axis: str
    side: str
    center: tuple[float, float, float]
    area: float = Field(ge=0)


class GeometryCandidate(BaseModel):
    """几何候选。

    由 CAD 几何摘要派生的可求解几何草案，供 Designer/能力解析进一步补全材料、载荷与边界。

    Args:
        geometry_type: 推断的几何类型。
        dimensions: 包围盒派生尺寸（``length`` / ``width`` / ``height``），单位为 mm。
        bbox_min: 包围盒最小角点。
        bbox_max: 包围盒最大角点。
        region_candidates: 边界/载荷区域候选列表。
        missing_fields: 几何无法确定、需补充的字段。

    Returns:
        GeometryCandidate: 几何候选草案。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> from mechagent.core.cad import CADGeometrySummary, geometry_candidate_from_summary
        >>> geometry_candidate_from_summary(
        ...     CADGeometrySummary(
        ...         source_format="step",
        ...         bbox_min=(0.0, 0.0, 0.0),
        ...         bbox_max=(1000.0, 40.0, 40.0),
        ...         volume=1.6e6,
        ...         surface_area=1.0e5,
        ...         solid_count=1,
        ...         face_count=6,
        ...         edge_count=12,
        ...     )
        ... ).geometry_type
        <GeometryType.BEAM: 'beam'>
    """

    model_config = ConfigDict(extra="forbid")

    geometry_type: GeometryType
    dimensions: dict[str, float]
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    region_candidates: list[RegionCandidate] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


def geometry_candidate_from_summary(summary: CADGeometrySummary) -> GeometryCandidate:
    """从 CAD 几何摘要派生几何候选。

    依据包围盒长宽高的薄度与细长比推断几何类型，并由六个包围盒面生成边界/载荷区域候选；
    材料、载荷与边界由几何无法确定，记入缺参诊断。

    Args:
        summary: CAD 几何摘要。

    Returns:
        GeometryCandidate: 几何候选草案。

    Raises:
        无。

    Example:
        >>> candidate = geometry_candidate_from_summary(summary)
        >>> candidate.missing_fields
        ['material', 'loads', 'bcs']
    """

    dx = summary.bbox_max[0] - summary.bbox_min[0]
    dy = summary.bbox_max[1] - summary.bbox_min[1]
    dz = summary.bbox_max[2] - summary.bbox_min[2]
    center = (
        (summary.bbox_min[0] + summary.bbox_max[0]) / 2,
        (summary.bbox_min[1] + summary.bbox_max[1]) / 2,
        (summary.bbox_min[2] + summary.bbox_max[2]) / 2,
    )
    axes = (("x", 0, dx), ("y", 1, dy), ("z", 2, dz))
    regions: list[RegionCandidate] = []
    for axis, index, _extent in axes:
        face_area = 1.0
        for other_axis, _other_index, other_extent in axes:
            if other_axis != axis:
                face_area *= other_extent
        for side in ("min", "max"):
            coord = summary.bbox_min[index] if side == "min" else summary.bbox_max[index]
            face_center = list(center)
            face_center[index] = coord
            regions.append(
                RegionCandidate(
                    name=f"{axis}_{side}",
                    axis=axis,
                    side=side,
                    center=(face_center[0], face_center[1], face_center[2]),
                    area=max(face_area, 0.0),
                )
            )
    return GeometryCandidate(
        geometry_type=_infer_geometry_type(dx, dy, dz),
        dimensions={"length": dx, "width": dy, "height": dz},
        bbox_min=summary.bbox_min,
        bbox_max=summary.bbox_max,
        region_candidates=regions,
        missing_fields=["material", "loads", "bcs"],
    )


def _infer_geometry_type(dx: float, dy: float, dz: float) -> GeometryType:
    smallest, mid, _largest = sorted((dx, dy, dz))
    if mid <= 0:
        return GeometryType.SOLID
    if smallest / mid < 0.2:
        return GeometryType.PLATE
    if _largest / mid > 5.0:
        return GeometryType.BEAM
    return GeometryType.SOLID

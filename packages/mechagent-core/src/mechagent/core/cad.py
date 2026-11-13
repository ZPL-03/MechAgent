"""CAD 内核抽象接口。

定义把外部 CAD 形体（STEP/IGES/BREP 等）导入、按配置尝试处理并归纳为几何摘要的统一
契约。摘要本身不证明特征识别、区域语义或有限元可求解性；这些结论由具体适配器、案例
契约和执行前门禁分别提供。具体内核（如基于 OpenCASCADE 的实现）通过工厂注册名、构造
函数和配置接入，与求解器、网格器保持一致的注册/工厂/配置模式。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mechagent.core.exceptions import CADError
from mechagent.core.models import GeometryType


class CADConfig(BaseModel):
    """CAD 内核运行配置。

    Args:
        work_dir: 几何处理输出目录。
        linear_deflection: 预留的离散化线性弦高，单位为 mm；当前 Gmsh 摘要适配器不使用该字段。
        min_feature_size: 预留的去特征阈值，单位为 mm。当前 Gmsh 适配器不使用该字段，
            因此非零值不会自动删除 CAD 特征。
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
        feature_id: 由具体适配器提供的特征标识；不保证是 CAD 内核的长期 persistent ID。
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


class CADTopologyEntity(BaseModel):
    """可追踪的 CAD 拓扑实体。

    ``stable_id`` 是根据当前导入摘要的几何度量生成的可复现标识，只能在相同的
    拓扑摘要和容差约定下复用；它不是 CAD 文件或内核提供的长期 persistent ID。
    """

    model_config = ConfigDict(extra="forbid")

    stable_id: str = Field(min_length=1, max_length=128)
    dimension: Literal[1, 2, 3]
    native_tag: int = Field(gt=0)
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    center: tuple[float, float, float]
    measure: float = Field(ge=0)
    children: list[str] = Field(default_factory=list)


class CADArtifact(BaseModel):
    """可追踪的 CAD 源文件及其摘要指纹。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    source_path: str = Field(min_length=1, max_length=4096)
    source_format: str = Field(min_length=1, max_length=32)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_size: int = Field(ge=0)
    units: str = Field(default="mm", min_length=1, max_length=32)
    topology_digest: str = Field(default="", max_length=128)
    summary_digest: str = Field(default="", max_length=128)
    geometry_file: str | None = Field(default=None, max_length=4096)


class GeometryValidation(BaseModel):
    """CAD 摘要的确定性校验结果。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    status: Literal["passed", "failed", "unverified"]
    execution_ready: bool = False
    checks: dict[str, Literal["passed", "failed", "unverified"]] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RegionBinding(BaseModel):
    """CAD 拓扑区域与案例语义之间的绑定记录。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=128)
    dimension: Literal[1, 2, 3] | None = None
    topology_ids: list[str] = Field(default_factory=list, max_length=4096)
    part_ids: list[str] = Field(default_factory=list, max_length=4096)
    status: Literal["mapped", "ambiguous", "unresolved"]
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["cad_summary", "case"] = "cad_summary"
    reason: str = Field(default="", max_length=512)


class CADPartSummary(BaseModel):
    """一个三维实体及其边界拓扑成员的摘要。"""

    model_config = ConfigDict(extra="forbid")

    part_id: str = Field(min_length=1, max_length=128)
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    volume: float = Field(ge=0)
    surface_area: float = Field(ge=0)
    face_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)


class CADGeometrySummary(BaseModel):
    """CAD 几何摘要。

    Args:
        source_format: 来源格式，例如 ``step``、``iges``、``brep``。
        units: 几何单位，默认 ``mm``。
        bbox_min: 包围盒最小角点坐标。
        bbox_max: 包围盒最大角点坐标。
        source_sha256: CAD 源文件 SHA-256；为空表示未提供完整性指纹。
        topology_digest: 当前拓扑实体及父子关系的摘要指纹。
        volume: 体积，单位为 mm^3。
        surface_area: 表面积，单位为 mm^2。
        solid_count: 实体数量。
        face_count: 面数量。
        edge_count: 边数量。
        watertight: 形体是否封闭水密。
        healing_applied: 是否对导入结果执行了内核级修复。
        features: 由具体适配器确认的几何特征列表；为空表示没有提供特征识别结果。
        parts: 按三维实体划分的零件摘要。

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
    source_sha256: str = ""
    topology_digest: str = ""
    units: str = "mm"
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    volume: float = Field(ge=0)
    surface_area: float = Field(ge=0)
    solid_count: int = Field(ge=0)
    face_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    watertight: bool = True
    healing_applied: bool = False
    features: list[CADGeometryFeature] = Field(default_factory=list)
    topology_entities: list[CADTopologyEntity] = Field(default_factory=list)
    parts: list[CADPartSummary] = Field(default_factory=list)
    region_candidates: list["RegionCandidate"] = Field(default_factory=list)

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
        success: 导入以及配置中启用的处理步骤是否成功。
        summary: 成功时的几何摘要。
        artifact: 可追踪的源文件及摘要指纹；源文件不可读时为空。
        validation: 几何、拓扑和区域契约的确定性校验结果。
        region_bindings: 摘要中的区域候选及其拓扑绑定记录。
        geometry_file: 可选的修复或标准化后导出文件路径；当前 Gmsh 适配器不导出标准化文件，
            默认保持为空。
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
    artifact: CADArtifact | None = None
    validation: GeometryValidation | None = None
    region_bindings: list[RegionBinding] = Field(default_factory=list)
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
    子类只实现形体加载、处理和摘要归纳。硬失败通过抛出 ``CADError`` 表达，模板捕获后
    返回 ``success=False`` 的结果对象。返回的摘要不自动获得特征识别或有限元可求解语义。

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
        """按具体内核契约尝试修复形体。

        具体实现可以缝合面或修复自由边，但抽象接口不保证执行去特征、特征识别或导出。

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
        """归纳形体的几何摘要和由适配器确认的特征。

        Args:
            shape: 内核形体句柄。

        Returns:
            CADGeometrySummary: 统一几何摘要。

        Raises:
            CADError: 当几何度量或适配器声明的摘要步骤失败时抛出。

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
            validation = validate_cad_summary(summary)
            artifact = _cad_artifact(source, summary)
            bindings = region_bindings_from_summary(summary)
            if validation.status == "failed":
                return CADImportResult(
                    success=False,
                    summary=summary,
                    artifact=artifact,
                    validation=validation,
                    region_bindings=bindings,
                    wall_time=time.perf_counter() - start,
                    error_message="CAD 几何校验失败: " + "；".join(validation.blockers),
                )
        except CADError as exc:
            return CADImportResult(
                success=False,
                wall_time=time.perf_counter() - start,
                error_message=str(exc),
            )
        return CADImportResult(
            success=True,
            summary=summary,
            artifact=artifact,
            validation=validation,
            region_bindings=bindings,
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
        part_ids: 候选拓扑面所属的三维实体 ID；空列表表示适配器没有提供零件归属。

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
    topology_ids: list[str] = Field(default_factory=list)
    part_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: Literal["mapped", "ambiguous", "unresolved"] = "unresolved"


def validate_cad_summary(summary: CADGeometrySummary) -> GeometryValidation:
    """校验 CAD 摘要的几何、拓扑和区域契约。"""

    checks: dict[str, Literal["passed", "failed", "unverified"]] = {}
    blockers: list[str] = []
    warnings: list[str] = []

    extents = tuple(summary.bbox_max[index] - summary.bbox_min[index] for index in range(3))
    if all(math.isfinite(value) for value in (*summary.bbox_min, *summary.bbox_max)) and all(
        value > 0.0 for value in extents
    ):
        checks["bbox"] = "passed"
    else:
        checks["bbox"] = "failed"
        blockers.append("包围盒必须包含三个有限的正长度方向。")

    if summary.solid_count > 0 and summary.volume > 0.0 and summary.watertight:
        checks["solid_geometry"] = "passed"
    else:
        checks["solid_geometry"] = "failed"
        blockers.append("CAD 必须包含正体积且水密的三维实体。")

    topology_by_id = {entity.stable_id: entity for entity in summary.topology_entities}
    if not summary.topology_entities:
        checks["topology"] = "unverified"
        warnings.append("摘要未提供拓扑实体，无法验证面、边和体的父子关系。")
    elif len(topology_by_id) != len(summary.topology_entities):
        checks["topology"] = "failed"
        blockers.append("拓扑实体 stable_id 必须唯一。")
    else:
        topology_errors: list[str] = []
        for entity in summary.topology_entities:
            if any(
                not math.isfinite(value)
                for value in (*entity.bbox_min, *entity.bbox_max, *entity.center, entity.measure)
            ):
                topology_errors.append(f"拓扑实体 {entity.stable_id} 含非有限几何值")
            if any(entity.bbox_max[index] < entity.bbox_min[index] for index in range(3)):
                topology_errors.append(f"拓扑实体 {entity.stable_id} 的包围盒范围无效")
            if len(entity.children) != len(set(entity.children)):
                topology_errors.append(f"拓扑实体 {entity.stable_id} 的子实体引用重复")
            if entity.stable_id in entity.children:
                topology_errors.append(f"拓扑实体 {entity.stable_id} 不能引用自身")
            for child_id in entity.children:
                child = topology_by_id.get(child_id)
                if child is None or child.dimension != entity.dimension - 1:
                    topology_errors.append(f"拓扑实体 {entity.stable_id} 的子实体关系无效")
        if topology_errors:
            checks["topology"] = "failed"
            blockers.extend(sorted(set(topology_errors)))
        else:
            checks["topology"] = "passed"

    if summary.solid_count != len(summary.parts):
        checks["parts"] = "unverified"
        warnings.append("零件摘要数量与实体数量不一致，无法确认所有实体的零件归属。")
    elif any(
        part.part_id not in topology_by_id or topology_by_id[part.part_id].dimension != 3
        for part in summary.parts
    ):
        checks["parts"] = "failed"
        blockers.append("零件摘要必须引用三维拓扑实体。")
    else:
        invalid_faces = [
            face_id
            for part in summary.parts
            for face_id in part.face_ids
            if face_id not in topology_by_id or topology_by_id[face_id].dimension != 2
        ]
        invalid_edges = [
            edge_id
            for part in summary.parts
            for edge_id in part.edge_ids
            if edge_id not in topology_by_id or topology_by_id[edge_id].dimension != 1
        ]
        if invalid_faces or invalid_edges:
            checks["parts"] = "failed"
            blockers.append("零件摘要引用了未知或维度不匹配的面/边拓扑实体。")
        else:
            checks["parts"] = "passed"

    if not summary.source_sha256 or not re.fullmatch(r"[0-9a-f]{64}", summary.source_sha256):
        checks["source_integrity"] = "unverified"
        warnings.append("摘要没有可验证的源文件 SHA-256。")
    else:
        checks["source_integrity"] = "passed"
    if not summary.topology_digest:
        checks["topology_digest"] = "unverified"
        warnings.append("摘要没有拓扑摘要指纹。")
    else:
        checks["topology_digest"] = "passed"

    region_errors: list[str] = []
    part_ids = {part.part_id for part in summary.parts}
    for candidate in summary.region_candidates:
        unknown = [item for item in candidate.topology_ids if item not in topology_by_id]
        if unknown:
            region_errors.append(f"区域 {candidate.name} 引用了未知拓扑实体")
        if any(
            item in topology_by_id and topology_by_id[item].dimension != 2
            for item in candidate.topology_ids
        ):
            region_errors.append(f"区域 {candidate.name} 必须引用二维拓扑实体")
        if any(item not in part_ids for item in candidate.part_ids):
            region_errors.append(f"区域 {candidate.name} 引用了未知零件")
        if candidate.status == "mapped" and not candidate.topology_ids:
            region_errors.append(f"区域 {candidate.name} 标记为 mapped 但没有拓扑实体")
    if region_errors:
        checks["regions"] = "failed"
        blockers.extend(sorted(set(region_errors)))
    elif summary.region_candidates:
        checks["regions"] = "passed"
    else:
        checks["regions"] = "unverified"
        warnings.append("摘要没有区域候选，载荷和边界无法绑定到 CAD 拓扑。")

    if blockers:
        status: Literal["passed", "failed", "unverified"] = "failed"
    elif any(value == "unverified" for value in checks.values()):
        status = "unverified"
    else:
        status = "passed"
    execution_ready = status == "passed" and not warnings
    return GeometryValidation(
        status=status,
        execution_ready=execution_ready,
        checks=checks,
        blockers=sorted(set(blockers)),
        warnings=sorted(set(warnings)),
    )


def region_bindings_from_summary(summary: CADGeometrySummary) -> list[RegionBinding]:
    """将摘要中的区域候选转换为可序列化的绑定记录。"""

    topology_by_id = {entity.stable_id: entity for entity in summary.topology_entities}
    bindings: list[RegionBinding] = []
    for candidate in summary.region_candidates:
        dimensions = {
            topology_by_id[item].dimension
            for item in candidate.topology_ids
            if item in topology_by_id
        }
        dimension = next(iter(dimensions)) if len(dimensions) == 1 else None
        reason = ""
        if candidate.status == "ambiguous":
            reason = "候选面存在等距拓扑实体。"
        elif candidate.status == "unresolved":
            reason = "没有可确认的拓扑面。"
        bindings.append(
            RegionBinding(
                name=candidate.name,
                dimension=dimension,
                topology_ids=list(candidate.topology_ids),
                part_ids=list(candidate.part_ids),
                status=candidate.status,
                confidence=candidate.confidence,
                reason=reason,
            )
        )
    return bindings


def _cad_artifact(source: Path, summary: CADGeometrySummary) -> CADArtifact | None:
    """从现有源文件和摘要生成 CADArtifact；源文件不可读时不伪造指纹。"""

    try:
        source_path = source.resolve()
        if not source_path.is_file():
            return None
        source_hash = _sha256_file(source_path)
        source_size = source_path.stat().st_size
    except OSError:
        return None
    summary_payload = summary.model_dump(mode="json")
    summary_json = json.dumps(
        summary_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    summary_digest = hashlib.sha256(summary_json).hexdigest()
    return CADArtifact(
        source_path=str(source_path),
        source_format=summary.source_format,
        source_sha256=source_hash,
        source_size=source_size,
        units=summary.units,
        topology_digest=summary.topology_digest,
        summary_digest=summary_digest,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


CADGeometrySummary.model_rebuild()


class GeometryCandidate(BaseModel):
    """几何候选。

    由 CAD 几何摘要派生的结构化几何草案，供 Designer/能力解析进一步补全材料、载荷与边界。
    候选通过执行前门禁后才进入网格和求解；候选对象本身仍只描述当前摘要派生的几何草案。

    Args:
        geometry_type: 推断的几何类型。
        dimensions: 包围盒派生尺寸（``length`` / ``width`` / ``height``），单位为 mm。
        bbox_min: 包围盒最小角点。
        bbox_max: 包围盒最大角点。
        region_candidates: 边界/载荷区域候选列表。
        parts: 按三维实体划分的零件摘要。
        artifact: 源文件和摘要指纹。
        geometry_validation: 几何、拓扑和区域契约校验结果。
        region_bindings: 区域语义到拓扑实体的绑定记录。
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
    source_format: str = ""
    source_path: str = ""
    source_sha256: str = ""
    topology_digest: str = ""
    watertight: bool | None = None
    healing_applied: bool = False
    topology_entities: list[CADTopologyEntity] = Field(default_factory=list)
    parts: list[CADPartSummary] = Field(default_factory=list)
    artifact: CADArtifact | None = None
    geometry_validation: GeometryValidation | None = None
    region_bindings: list[RegionBinding] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


def is_multi_solid_cad_metadata(metadata: Mapping[str, Any]) -> bool:
    """判断模型元数据是否描述包含多个三维实体的 CAD 来源。"""

    if metadata.get("geometry_source") != "cad":
        return False
    cad_geometry = metadata.get("cad_geometry")
    if not isinstance(cad_geometry, Mapping):
        return False
    solid_count = cad_geometry.get("solid_count")
    if isinstance(solid_count, int) and solid_count > 1:
        return True
    parts = cad_geometry.get("parts")
    return isinstance(parts, list) and len(parts) > 1


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
    regions: list[RegionCandidate] = list(summary.region_candidates)
    geometry_validation = validate_cad_summary(summary)
    bindings = region_bindings_from_summary(summary)
    if regions:
        return GeometryCandidate(
            geometry_type=_infer_geometry_type(dx, dy, dz),
            dimensions={"length": dx, "width": dy, "height": dz},
            bbox_min=summary.bbox_min,
            bbox_max=summary.bbox_max,
            region_candidates=regions,
            source_format=summary.source_format,
            source_sha256=summary.source_sha256,
            topology_digest=summary.topology_digest,
            watertight=summary.watertight,
            healing_applied=summary.healing_applied,
            topology_entities=summary.topology_entities,
            parts=summary.parts,
            geometry_validation=geometry_validation,
            region_bindings=bindings,
            missing_fields=["material", "loads", "bcs"],
        )
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
        source_format=summary.source_format,
        source_sha256=summary.source_sha256,
        topology_digest=summary.topology_digest,
        watertight=summary.watertight,
        healing_applied=summary.healing_applied,
        topology_entities=summary.topology_entities,
        parts=summary.parts,
        geometry_validation=geometry_validation,
        region_bindings=bindings,
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

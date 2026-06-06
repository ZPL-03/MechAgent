"""仿真任务结构化参数模型。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mechagent.core.models.geometry import (
    AnalysisType,
    BCType,
    ElementType,
    GeometryType,
    LoadType,
    MaterialType,
)


class CompositeSpec(BaseModel):
    """复合材料铺层参数。

    Args:
        layup: 铺层角度列表，单位为度。
        ply_thickness: 单层厚度，单位为 mm。

    Returns:
        CompositeSpec: 经过 Pydantic 校验的复合材料参数。

    Raises:
        pydantic.ValidationError: 当铺层或厚度不满足约束时抛出。

    Example:
        >>> CompositeSpec(layup=[0, 45, -45, 90], ply_thickness=0.125)
        CompositeSpec(layup=[0.0, 45.0, -45.0, 90.0], ply_thickness=0.125)
    """

    model_config = ConfigDict(extra="forbid")

    layup: list[float] = Field(default_factory=list, description="铺层角度，单位为度。")
    ply_thickness: Optional[float] = Field(default=None, gt=0, description="单层厚度，单位为 mm。")

    @model_validator(mode="after")
    def _composite_numbers_must_be_finite(self) -> "CompositeSpec":
        invalid_angles = [
            str(index) for index, angle in enumerate(self.layup) if not math.isfinite(angle)
        ]
        if invalid_angles:
            msg = f"composite.layup 包含非有限角度: {', '.join(invalid_angles)}。"
            raise ValueError(msg)
        if self.ply_thickness is not None and not math.isfinite(self.ply_thickness):
            msg = "composite.ply_thickness 必须是有限数值。"
            raise ValueError(msg)
        return self


class GeometrySpec(BaseModel):
    """几何参数。

    Args:
        type: 结构几何类型。
        dimensions: 几何尺寸字典，长度单位统一为 mm。

    Returns:
        GeometrySpec: 经过校验的几何参数。

    Raises:
        pydantic.ValidationError: 当尺寸字段为空或存在非正值时抛出。

    Example:
        >>> GeometrySpec(type="beam", dimensions={"length": 1000, "width": 20, "height": 40})
        GeometrySpec(type=<GeometryType.BEAM: 'beam'>, dimensions={'length': 1000.0, ...})
    """

    model_config = ConfigDict(extra="forbid")

    type: GeometryType
    dimensions: dict[str, float] = Field(description="几何尺寸，单位为 mm。")

    @field_validator("dimensions")
    @classmethod
    def _dimensions_must_be_positive(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            msg = "geometry.dimensions 不能为空。"
            raise ValueError(msg)
        non_finite = [name for name, number in value.items() if not math.isfinite(number)]
        if non_finite:
            msg = f"geometry.dimensions 存在非有限尺寸: {', '.join(non_finite)}。"
            raise ValueError(msg)
        invalid = [name for name, number in value.items() if number <= 0]
        if invalid:
            msg = f"geometry.dimensions 存在非正尺寸: {', '.join(invalid)}。"
            raise ValueError(msg)
        return value


class MaterialSpec(BaseModel):
    """材料参数。

    Args:
        type: 材料类型。
        E: 弹性模量，单位为 MPa。
        nu: 泊松比。
        rho: 密度，单位为 tonne/mm^3。
        composite: 复合材料铺层信息。

    Returns:
        MaterialSpec: 经过校验的材料参数。

    Raises:
        pydantic.ValidationError: 当弹性模量、泊松比或密度不满足约束时抛出。

    Example:
        >>> MaterialSpec(E=210000, nu=0.3, rho=7.85e-9)
        MaterialSpec(type=<MaterialType.ISOTROPIC: 'isotropic'>, E=210000.0, ...)
    """

    model_config = ConfigDict(extra="forbid")

    type: MaterialType = MaterialType.ISOTROPIC
    E: float = Field(gt=0, description="弹性模量，单位为 MPa。")
    nu: float = Field(gt=-1.0, lt=0.5, description="泊松比。")
    rho: float = Field(gt=0, description="密度，单位为 tonne/mm^3。")
    composite: Optional[CompositeSpec] = None

    @model_validator(mode="after")
    def _material_numbers_must_be_finite(self) -> "MaterialSpec":
        invalid = [
            name
            for name, number in (("E", self.E), ("nu", self.nu), ("rho", self.rho))
            if not math.isfinite(number)
        ]
        if invalid:
            msg = f"material 包含非有限数值: {', '.join(invalid)}。"
            raise ValueError(msg)
        return self


class LoadSpec(BaseModel):
    """载荷参数。

    Args:
        type: 载荷类型。
        magnitude: 载荷幅值，单位按载荷类型解释。
        region: 载荷作用区域。
        direction: 三维方向向量。

    Returns:
        LoadSpec: 经过校验的载荷参数。

    Raises:
        pydantic.ValidationError: 当方向向量长度不是 3 时抛出。

    Example:
        >>> LoadSpec(type="force", magnitude=1000, region="tip", direction=[0, -1, 0])
        LoadSpec(type=<LoadType.FORCE: 'force'>, magnitude=1000.0, ...)
    """

    model_config = ConfigDict(extra="forbid")

    type: LoadType
    magnitude: float
    region: str = Field(min_length=1)
    direction: tuple[float, float, float]

    @model_validator(mode="after")
    def _load_must_be_effective(self) -> "LoadSpec":
        if not math.isfinite(self.magnitude):
            msg = "loads.magnitude 必须是有限数值。"
            raise ValueError(msg)
        non_finite_direction = [
            str(index)
            for index, component in enumerate(self.direction)
            if not math.isfinite(component)
        ]
        if non_finite_direction:
            msg = f"loads.direction 包含非有限分量: {', '.join(non_finite_direction)}。"
            raise ValueError(msg)
        if abs(self.magnitude) <= 1.0e-12:
            msg = "loads.magnitude 不能为 0。"
            raise ValueError(msg)
        if all(abs(component) <= 1.0e-12 for component in self.direction):
            msg = "loads.direction 不能是零向量。"
            raise ValueError(msg)
        return self


class BCSpec(BaseModel):
    """边界条件参数。

    Args:
        type: 边界条件类型。
        region: 约束区域。
        dofs: 约束自由度名称。
        values: 对应自由度取值。

    Returns:
        BCSpec: 经过校验的边界条件参数。

    Raises:
        pydantic.ValidationError: 当自由度数量与取值数量不一致时抛出。

    Example:
        >>> BCSpec(type="fixed", region="root", dofs=["ux", "uy"], values=[0, 0])
        BCSpec(type=<BCType.FIXED: 'fixed'>, region='root', ...)
    """

    model_config = ConfigDict(extra="forbid")

    type: BCType
    region: str = Field(min_length=1)
    dofs: list[str] = Field(min_length=1)
    values: list[float] = Field(min_length=1)

    @model_validator(mode="after")
    def _dofs_and_values_must_match(self) -> "BCSpec":
        blank_dofs = [dof for dof in self.dofs if not dof.strip()]
        if blank_dofs:
            msg = "bcs.dofs 不能包含空白自由度。"
            raise ValueError(msg)
        non_finite_values = [
            str(index) for index, value in enumerate(self.values) if not math.isfinite(value)
        ]
        if non_finite_values:
            msg = f"bcs.values 包含非有限数值: {', '.join(non_finite_values)}。"
            raise ValueError(msg)
        if len(self.dofs) != len(self.values):
            msg = "bcs.dofs 与 bcs.values 数量必须一致。"
            raise ValueError(msg)
        return self


class MeshSpec(BaseModel):
    """网格参数。

    Args:
        element_type: 单元类型。
        seed_size: 全局网格种子尺寸，单位为 mm。

    Returns:
        MeshSpec: 经过校验的网格参数。

    Raises:
        pydantic.ValidationError: 当网格尺寸非正时抛出。

    Example:
        >>> MeshSpec(element_type="B31", seed_size=10)
        MeshSpec(element_type=<ElementType.B31: 'B31'>, seed_size=10.0)
    """

    model_config = ConfigDict(extra="forbid")

    element_type: ElementType
    seed_size: float = Field(gt=0, description="全局网格种子尺寸，单位为 mm。")

    @field_validator("seed_size")
    @classmethod
    def _seed_size_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "mesh.seed_size 必须是有限数值。"
            raise ValueError(msg)
        return value


class AnalysisSpec(BaseModel):
    """分析设置。

    Args:
        type: 分析类型。
        nlgeom: 是否启用几何非线性。

    Returns:
        AnalysisSpec: 经过校验的分析设置。

    Raises:
        pydantic.ValidationError: 当分析类型不在枚举范围内时抛出。

    Example:
        >>> AnalysisSpec(type="static", nlgeom=False)
        AnalysisSpec(type=<AnalysisType.STATIC: 'static'>, nlgeom=False)
    """

    model_config = ConfigDict(extra="forbid")

    type: AnalysisType
    nlgeom: bool = False


class ModelParams(BaseModel):
    """Agent 与工具层共享的仿真任务参数。

    Args:
        geometry: 几何参数。
        material: 材料参数。
        loads: 载荷列表。
        bcs: 边界条件列表。
        mesh: 网格参数。
        analysis: 分析设置。
        case_id: 模型能力或验证案例编号。
        load_case: 载荷工况编号。
        mesh_file: 求解使用的网格文件。
        metadata: 输入来源和扩展诊断元数据。

    Returns:
        ModelParams: 完整仿真任务参数。

    Raises:
        pydantic.ValidationError: 当任一字段违反 schema 时抛出。

    Example:
        >>> ModelParams(
        ...     geometry={
        ...         "type": "beam",
        ...         "dimensions": {"length": 1000, "width": 20, "height": 40},
        ...     },
        ...     material={"E": 210000, "nu": 0.3, "rho": 7.85e-9},
        ...     loads=[
        ...         {"type": "force", "magnitude": 1000, "region": "tip", "direction": [0, -1, 0]}
        ...     ],
        ...     bcs=[{"type": "fixed", "region": "root", "dofs": ["ux"], "values": [0]}],
        ...     mesh={"element_type": "B31", "seed_size": 10},
        ...     analysis={"type": "static"},
        ... )
        ModelParams(...)
    """

    model_config = ConfigDict(extra="forbid")

    geometry: GeometrySpec
    material: MaterialSpec
    loads: list[LoadSpec] = Field(min_length=1)
    bcs: list[BCSpec] = Field(min_length=1)
    mesh: MeshSpec
    analysis: AnalysisSpec
    case_id: str = ""
    load_case: str = ""
    mesh_file: Optional[Path] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

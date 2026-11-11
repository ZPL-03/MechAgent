"""版本化仿真案例契约。

`ModelParams` 是现有求解器和网格器使用的兼容模型；`SimulationCase` 为跨 API、
编排、适配器和证据边界使用的版本化封装。两者通过显式转换连接，避免在每个层级
复制一套几何、材料和载荷字段。
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mechagent.core.models.params import ModelParams

CASE_SCHEMA_VERSION = 1


class UnitSystem(BaseModel):
    """案例中的物理单位约定。

    当前结构静力基线使用 N-mm-MPa-tonne/mm³。单位字段必须显式存在；
    单位转换由后续适配器集中实现，案例契约不会根据自然语言猜测单位。
    """

    model_config = ConfigDict(extra="forbid")

    length: Literal["mm"] = "mm"
    force: Literal["N"] = "N"
    stress: Literal["MPa"] = "MPa"
    density: Literal["tonne/mm^3"] = "tonne/mm^3"
    temperature: Literal["C"] = "C"


class CoordinateSystem(BaseModel):
    """案例几何与载荷使用的右手坐标系。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="global", min_length=1, max_length=64)
    handedness: Literal["right"] = "right"
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    axes: tuple[str, str, str] = ("x", "y", "z")

    @field_validator("origin")
    @classmethod
    def _origin_must_be_finite(
        cls, value: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        if any(not math.isfinite(component) for component in value):
            raise ValueError("coordinate_system.origin 必须是有限数值。")
        return value

    @model_validator(mode="after")
    def _axes_must_be_distinct(self) -> "CoordinateSystem":
        if len(set(self.axes)) != 3 or any(not axis.strip() for axis in self.axes):
            raise ValueError("coordinate_system.axes 必须包含三个不同的非空轴名称。")
        return self


class Provenance(BaseModel):
    """输入值的来源和可信度。"""

    model_config = ConfigDict(extra="forbid")

    source: Literal["user", "parser", "llm", "default", "file", "import", "legacy"]
    reference: str = Field(default="", max_length=512)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RegionSpec(BaseModel):
    """载荷或边界区域的可追踪描述。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    kind: Literal["named", "topology", "mesh_set", "coordinate", "unknown"] = "named"
    stable_id: str = Field(default="", max_length=256)
    provenance: Provenance


class SolverControl(BaseModel):
    """求解控制参数的稳定占位契约。

    这些字段不会替代现有 `AnalysisSpec`；未提供的值由具体求解器适配器决定。
    """

    model_config = ConfigDict(extra="forbid")

    max_iterations: int | None = Field(default=None, gt=0, le=1_000_000)
    relative_tolerance: float | None = Field(default=None, gt=0.0, lt=1.0)
    absolute_tolerance: float | None = Field(default=None, gt=0.0)
    time_step: float | None = Field(default=None, gt=0.0)


class RequestProvenance(BaseModel):
    """用户请求及其解析链路的可审计摘要。"""

    model_config = ConfigDict(extra="forbid")

    raw_request: str = Field(min_length=1, max_length=20_000)
    source: Literal["user", "import", "retry"] = "user"
    parser: str = Field(default="deterministic", min_length=1, max_length=128)
    parser_version: str = Field(default="", max_length=64)


class SimulationCase(BaseModel):
    """跨层共享的版本化仿真案例。

    `model` 保留现有求解器输入模型，其他字段明确描述版本、单位、坐标、区域
    和来源。未知的未来 schema 版本必须在校验阶段拒绝。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=CASE_SCHEMA_VERSION, ge=1, le=CASE_SCHEMA_VERSION)
    case_id: str = Field(default="", max_length=128)
    model: ModelParams
    units: UnitSystem = Field(default_factory=UnitSystem)
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    regions: dict[str, RegionSpec] = Field(default_factory=dict)
    request: RequestProvenance | None = None
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    solver_control: SolverControl = Field(default_factory=SolverControl)

    @model_validator(mode="after")
    def _case_id_matches_model(self) -> "SimulationCase":
        if self.schema_version != CASE_SCHEMA_VERSION:
            raise ValueError(f"不支持的仿真案例版本：{self.schema_version}")
        if self.case_id and self.model.case_id and self.case_id != self.model.case_id:
            raise ValueError("case_id 必须与 model.case_id 一致。")
        invalid_region_keys = [key for key, value in self.regions.items() if key != value.name]
        if invalid_region_keys:
            raise ValueError(
                "regions 的字典键必须与 RegionSpec.name 一致："
                + ", ".join(sorted(invalid_region_keys))
            )
        referenced = {item.region for item in self.model.loads}
        referenced.update(item.region for item in self.model.bcs)
        missing_regions = sorted(referenced - self.regions.keys())
        if missing_regions:
            raise ValueError("案例缺少区域来源：" + ", ".join(missing_regions))
        required_provenance = {"geometry", "material", "loads", "bcs", "mesh", "analysis"}
        missing_provenance = sorted(required_provenance - self.provenance.keys())
        if missing_provenance:
            raise ValueError("案例缺少字段来源：" + ", ".join(missing_provenance))
        return self

    @classmethod
    def from_model_params(
        cls,
        model: ModelParams,
        *,
        raw_request: str | None = None,
        parser: str = "legacy",
        parser_version: str = "",
        request_source: Literal["user", "import", "retry"] = "user",
    ) -> "SimulationCase":
        """把兼容 `ModelParams` 显式提升为案例契约。"""

        source_name = str(model.metadata.get("source", "legacy"))
        provenance_source: Literal[
            "user", "parser", "llm", "default", "file", "import", "legacy"
        ] = "legacy"
        if source_name == "natural_language":
            provenance_source = "parser"
        elif source_name == "llm_structured":
            provenance_source = "llm"
        regions: dict[str, RegionSpec] = {}
        region_names = [item.region for item in model.loads]
        region_names.extend(item.region for item in model.bcs)
        for region in region_names:
            if region not in regions:
                regions[region] = RegionSpec(
                    name=region,
                    provenance=Provenance(source=provenance_source, reference="ModelParams.region"),
                )
        request = (
            RequestProvenance(
                raw_request=raw_request,
                source=request_source,
                parser=parser,
                parser_version=parser_version,
            )
            if raw_request
            else None
        )
        return cls(
            case_id=model.case_id,
            model=model,
            regions=regions,
            request=request,
            provenance={
                "geometry": Provenance(source=provenance_source, reference="ModelParams.geometry"),
                "material": Provenance(source=provenance_source, reference="ModelParams.material"),
                "loads": Provenance(source=provenance_source, reference="ModelParams.loads"),
                "bcs": Provenance(source=provenance_source, reference="ModelParams.bcs"),
                "mesh": Provenance(source=provenance_source, reference="ModelParams.mesh"),
                "analysis": Provenance(source=provenance_source, reference="ModelParams.analysis"),
            },
        )

    def to_model_params(self) -> ModelParams:
        """返回求解器兼容模型，不丢失案例元数据。"""

        metadata = dict(self.model.metadata)
        metadata.setdefault("case_schema_version", self.schema_version)
        metadata.setdefault("unit_system", self.units.model_dump(mode="json"))
        metadata.setdefault("coordinate_system", self.coordinate_system.model_dump(mode="json"))
        if self.request is not None:
            metadata.setdefault("request_provenance", self.request.model_dump(mode="json"))
        return self.model.model_copy(update={"metadata": metadata})

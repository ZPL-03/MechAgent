"""版本化仿真案例契约。

`ModelParams` 是现有求解器和网格器使用的兼容模型；`SimulationCase` 为跨 API、
编排、适配器和证据边界使用的版本化封装。两者通过显式转换连接，避免在每个层级
复制一套几何、材料和载荷字段。
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mechagent.core.models.geometry import AnalysisType, LoadType
from mechagent.core.models.params import CompositeSpec, ModelParams

CASE_SCHEMA_VERSION = 1
MIN_EXECUTION_CONFIDENCE = 0.8
REQUIRED_PROVENANCE_FIELDS = frozenset({"geometry", "material", "loads", "bcs", "mesh", "analysis"})


class UnitSystem(BaseModel):
    """案例中的物理单位约定。

    求解器兼容基线为 N-mm-MPa-tonne/mm³。案例可声明受支持的输入单位，
    `to_canonical_model()` 将几何、材料、载荷、边界位移、网格和坐标转换到该基线。
    温度字段目前只支持摄氏度；案例契约不会根据自然语言猜测单位。
    """

    model_config = ConfigDict(extra="forbid")

    length: Literal["mm", "cm", "m", "in"] = "mm"
    force: Literal["N", "kN", "lbf"] = "N"
    stress: Literal["MPa", "kPa", "Pa", "GPa", "psi"] = "MPa"
    density: Literal["tonne/mm^3", "kg/m^3", "g/cm^3"] = "tonne/mm^3"
    temperature: Literal["C"] = "C"

    def to_canonical_model(self, model: ModelParams) -> ModelParams:
        """把模型数值转换为求解器使用的 N-mm-MPa-tonne/mm³ 基线。"""

        length_factor = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}[self.length]
        force_factor = {"N": 1.0, "kN": 1000.0, "lbf": 4.4482216152605}[self.force]
        stress_factor = {
            "MPa": 1.0,
            "kPa": 1.0e-3,
            "Pa": 1.0e-6,
            "GPa": 1000.0,
            "psi": 0.006894757293168,
        }[self.stress]
        density_factor = {
            "tonne/mm^3": 1.0,
            "kg/m^3": 1.0e-12,
            "g/cm^3": 1.0e-9,
        }[self.density]
        dimensions = {
            name: value if name in {"hole_count", "slot_count"} else _scaled(value, length_factor)
            for name, value in model.geometry.dimensions.items()
        }
        material = model.material.model_copy(
            update={
                "E": _scaled(model.material.E, stress_factor),
                "rho": _scaled(model.material.rho, density_factor),
                "composite": _converted_composite(model.material.composite, length_factor),
            }
        )
        loads = [
            load.model_copy(
                update={
                    "magnitude": _scaled(
                        load.magnitude,
                        _load_factor(load.type, length_factor, force_factor),
                    )
                }
            )
            for load in model.loads
        ]
        bcs = [
            bc.model_copy(
                update={
                    "values": [
                        _scaled(value, length_factor) if dof in {"ux", "uy", "uz"} else value
                        for dof, value in zip(bc.dofs, bc.values, strict=True)
                    ]
                }
            )
            for bc in model.bcs
        ]
        return model.model_copy(
            update={
                "geometry": model.geometry.model_copy(update={"dimensions": dimensions}),
                "material": material,
                "loads": loads,
                "bcs": bcs,
                "mesh": model.mesh.model_copy(
                    update={"seed_size": _scaled(model.mesh.seed_size, length_factor)}
                ),
            }
        )


def _scaled(value: float, factor: float) -> float:
    scaled = value * factor
    if not math.isfinite(scaled):
        raise ValueError("单位换算结果必须是有限数值。")
    return scaled


def _converted_composite(
    composite: CompositeSpec | None, length_factor: float
) -> CompositeSpec | None:
    if composite is None:
        return None
    ply_thickness = composite.ply_thickness
    if ply_thickness is None:
        return composite
    return composite.model_copy(update={"ply_thickness": _scaled(ply_thickness, length_factor)})


def _load_factor(load_type: LoadType, length_factor: float, force_factor: float) -> float:
    if load_type in {LoadType.FORCE, LoadType.MOMENT}:
        return force_factor * (length_factor if load_type is LoadType.MOMENT else 1.0)
    if load_type is LoadType.LINE_LOAD:
        return force_factor / length_factor
    if load_type is LoadType.PRESSURE:
        return force_factor / length_factor**2
    if load_type is LoadType.DISPLACEMENT:
        return length_factor
    return 1.0


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


class ExecutionReadiness(BaseModel):
    """案例进入网格和求解前的可执行性检查结果。"""

    model_config = ConfigDict(extra="forbid")

    ready: bool
    minimum_confidence: float = Field(
        default=MIN_EXECUTION_CONFIDENCE,
        ge=0.0,
        le=1.0,
    )
    lowest_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    blockers: list[str] = Field(default_factory=list)


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


class ResultFieldSpec(BaseModel):
    """案例请求的一个结果字段。

    `quantity` 和 `location` 描述后处理器应查找的物理量和位置；具体求解器
    是否能够提供该字段由能力注册项和适配器契约判断。字段请求不会把尚未
    注册的后处理能力伪装成已支持能力。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    quantity: str = Field(min_length=1, max_length=64)
    location: Literal["node", "element", "integration_point", "global"]
    component: str | None = Field(default=None, max_length=32)
    invariant: Literal[
        "mises",
        "max_principal",
        "min_principal",
        "tresca",
        "magnitude",
        "trace",
    ] | None = None
    unit: str = Field(default="", max_length=32)
    required: bool = True

    @model_validator(mode="after")
    def _result_selector_must_be_unambiguous(self) -> "ResultFieldSpec":
        if self.component is not None and not self.component.strip():
            raise ValueError("result_fields.component 不能是空白字符串。")
        if self.invariant is not None and self.component is not None:
            raise ValueError("result_fields.component 与 invariant 不能同时指定。")
        if not self.quantity.strip():
            raise ValueError("result_fields.quantity 不能是空白字符串。")
        if self.unit and not self.unit.strip():
            raise ValueError("result_fields.unit 不能是空白字符串。")
        return self


class LoadStepSpec(BaseModel):
    """一个有序分析步的执行控制和输出选择。

    `load_case` 为空时继承案例级 `ModelParams.load_case`；`load_scale` 是该步
    对案例载荷的统一比例。`duration` 使用分析类型定义的时间或伪时间单位，
    静力步中只用于增量和输出调度。当前兼容转换器只接受单个未缩放分析步，
    多步和非单位比例会在进入旧求解器接口前明确拒绝。
    """

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(
        default="step-1",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    )
    sequence: int = Field(default=1, ge=1, le=1_000_000)
    analysis: AnalysisType = AnalysisType.STATIC
    nlgeom: bool = False
    load_case: str = Field(default="", max_length=128)
    load_scale: float = Field(default=1.0, ge=0.0)
    duration: float = Field(default=1.0, gt=0.0)
    increments: int = Field(default=1, ge=1, le=1_000_000)
    output_interval: int = Field(default=1, ge=1, le=1_000_000)
    result_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _step_numbers_and_outputs_must_be_valid(self) -> "LoadStepSpec":
        if not math.isfinite(self.load_scale):
            raise ValueError("load_steps.load_scale 必须是有限数值。")
        if not math.isfinite(self.duration):
            raise ValueError("load_steps.duration 必须是有限数值。")
        if self.load_case and not self.load_case.strip():
            raise ValueError("load_steps.load_case 不能是空白字符串。")
        if self.output_interval > self.increments:
            raise ValueError("load_steps.output_interval 不能大于 increments。")
        if any(not field.strip() for field in self.result_fields):
            raise ValueError("load_steps.result_fields 不能包含空白名称。")
        if len(set(self.result_fields)) != len(self.result_fields):
            raise ValueError("load_steps.result_fields 不能包含重复名称。")
        return self


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
    load_steps: list[LoadStepSpec] = Field(default_factory=list)
    result_fields: list[ResultFieldSpec] = Field(default_factory=list)
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
        missing_provenance = sorted(REQUIRED_PROVENANCE_FIELDS - self.provenance.keys())
        if missing_provenance:
            raise ValueError("案例缺少字段来源：" + ", ".join(missing_provenance))
        if not self.result_fields:
            if "result_fields" in self.model_fields_set:
                raise ValueError("案例至少需要一个结果字段请求。")
            self.result_fields = [_default_result_field()]
        if not self.load_steps:
            if "load_steps" in self.model_fields_set:
                raise ValueError("案例至少需要一个分析步。")
            self.load_steps = [_default_load_step(self.model, self.result_fields)]
        self._validate_load_steps_and_results()
        return self

    def _validate_load_steps_and_results(self) -> None:
        step_ids = [step.step_id for step in self.load_steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("案例分析步 step_id 必须唯一。")
        sequences = [step.sequence for step in self.load_steps]
        if sorted(sequences) != list(range(1, len(sequences) + 1)):
            raise ValueError("案例分析步 sequence 必须从 1 开始连续编号。")
        result_names = [field.name for field in self.result_fields]
        if len(set(result_names)) != len(result_names):
            raise ValueError("案例结果字段 name 必须唯一。")
        result_name_set = set(result_names)
        unknown = sorted(
            {
                result_name
                for step in self.load_steps
                for result_name in step.result_fields
                if result_name not in result_name_set
            }
        )
        if unknown:
            raise ValueError("分析步引用了未知结果字段：" + ", ".join(unknown))

    def execution_readiness(
        self,
        *,
        minimum_confidence: float = MIN_EXECUTION_CONFIDENCE,
    ) -> ExecutionReadiness:
        """检查案例是否具备进入网格和求解阶段的来源证据。

        缺失来源或置信度只能在读取兼容案例时保留；执行前必须显式补齐，
        且所有字段和区域的置信度不得低于门槛。
        """

        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence 必须位于 0 到 1 之间。")

        blockers: list[str] = []
        confidences: list[float] = []
        for field_name in sorted(REQUIRED_PROVENANCE_FIELDS):
            provenance = self.provenance.get(field_name)
            if provenance is None:
                blockers.append(f"provenance.{field_name} 缺少来源")
                continue
            _collect_confidence_blocker(
                blockers,
                confidences,
                f"provenance.{field_name}",
                provenance.confidence,
                minimum_confidence,
            )
        for region_name in sorted(self.regions):
            _collect_confidence_blocker(
                blockers,
                confidences,
                f"regions.{region_name}.provenance",
                self.regions[region_name].provenance.confidence,
                minimum_confidence,
            )
        return ExecutionReadiness(
            ready=not blockers,
            minimum_confidence=minimum_confidence,
            lowest_confidence=min(confidences) if confidences else None,
            blockers=blockers,
        )

    @property
    def execution_ready(self) -> bool:
        """返回默认执行置信度门槛下的结果。"""

        return self.execution_readiness().ready

    def ensure_execution_ready(
        self,
        *,
        minimum_confidence: float = MIN_EXECUTION_CONFIDENCE,
    ) -> "SimulationCase":
        """在执行前强制检查来源完整性和置信度。"""

        readiness = self.execution_readiness(minimum_confidence=minimum_confidence)
        if not readiness.ready:
            details = "；".join(readiness.blockers)
            raise ValueError(
                "执行前检查失败：案例来源置信度不足或缺失。"
                f"最低要求 {minimum_confidence:.2f}。{details}"
            )
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
        provenance_confidence: float | None = None,
    ) -> "SimulationCase":
        """把兼容 `ModelParams` 显式提升为案例契约。"""

        if provenance_confidence is not None and not 0.0 <= provenance_confidence <= 1.0:
            raise ValueError("provenance_confidence 必须位于 0 到 1 之间。")

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
                    provenance=Provenance(
                        source=provenance_source,
                        reference="ModelParams.region",
                        confidence=provenance_confidence,
                    ),
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
            load_steps=[_default_load_step(model, [_default_result_field()])],
            result_fields=[_default_result_field()],
            provenance={
                "geometry": Provenance(
                    source=provenance_source,
                    reference="ModelParams.geometry",
                    confidence=provenance_confidence,
                ),
                "material": Provenance(
                    source=provenance_source,
                    reference="ModelParams.material",
                    confidence=provenance_confidence,
                ),
                "loads": Provenance(
                    source=provenance_source,
                    reference="ModelParams.loads",
                    confidence=provenance_confidence,
                ),
                "bcs": Provenance(
                    source=provenance_source,
                    reference="ModelParams.bcs",
                    confidence=provenance_confidence,
                ),
                "mesh": Provenance(
                    source=provenance_source,
                    reference="ModelParams.mesh",
                    confidence=provenance_confidence,
                ),
                "analysis": Provenance(
                    source=provenance_source,
                    reference="ModelParams.analysis",
                    confidence=provenance_confidence,
                ),
            },
        )

    def to_model_params(self) -> ModelParams:
        """返回转换为求解器基线单位的兼容模型，不丢失案例元数据。"""

        projection_blockers = self._legacy_projection_blockers()
        if projection_blockers:
            raise ValueError(
                "当前 ModelParams 兼容转换器无法表达案例分析步："
                + "；".join(projection_blockers)
            )

        model = self.units.to_canonical_model(self.model)
        metadata = dict(model.metadata)
        metadata.setdefault("case_schema_version", self.schema_version)
        metadata.setdefault("unit_system", self.units.model_dump(mode="json"))
        canonical_coordinate = self.coordinate_system.model_copy(
            update={
                "origin": tuple(
                    _scaled(
                        value, {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}[self.units.length]
                    )
                    for value in self.coordinate_system.origin
                )
            }
        )
        metadata.setdefault("coordinate_system", self.coordinate_system.model_dump(mode="json"))
        metadata.setdefault(
            "canonical_coordinate_system", canonical_coordinate.model_dump(mode="json")
        )
        metadata.setdefault("canonical_unit_system", UnitSystem().model_dump(mode="json"))
        if self.request is not None:
            metadata.setdefault("request_provenance", self.request.model_dump(mode="json"))
        metadata["load_steps"] = [step.model_dump(mode="json") for step in self.load_steps]
        metadata["result_fields"] = [field.model_dump(mode="json") for field in self.result_fields]
        return model.model_copy(update={"metadata": metadata})

    def _legacy_projection_blockers(self) -> list[str]:
        if len(self.load_steps) != 1:
            return [f"需要 {len(self.load_steps)} 个分析步，兼容接口只支持 1 个"]
        step = self.load_steps[0]
        blockers: list[str] = []
        if step.analysis != self.model.analysis.type:
            blockers.append("分析类型与 ModelParams.analysis.type 不一致")
        if step.nlgeom != self.model.analysis.nlgeom:
            blockers.append("几何非线性设置与 ModelParams.analysis.nlgeom 不一致")
        if step.load_case and step.load_case != self.model.load_case:
            blockers.append("load_case 与 ModelParams.load_case 不一致")
        if step.load_scale != 1.0:
            blockers.append("load_scale 不是 1.0")
        if step.duration != 1.0:
            blockers.append("duration 不是兼容默认值")
        if step.increments != 1 or step.output_interval != 1:
            blockers.append("增量或输出间隔不是兼容默认值")
        return blockers


def _collect_confidence_blocker(
    blockers: list[str],
    confidences: list[float],
    field_name: str,
    confidence: float | None,
    minimum_confidence: float,
) -> None:
    if confidence is None:
        blockers.append(f"{field_name}.confidence 缺失")
        return
    confidences.append(confidence)
    if confidence < minimum_confidence:
        blockers.append(f"{field_name}.confidence={confidence:.3f} 低于 {minimum_confidence:.3f}")


def _default_result_field() -> ResultFieldSpec:
    """为旧 `ModelParams` 案例提供可审计的主位移请求。"""

    return ResultFieldSpec(
        name="displacement",
        quantity="U",
        location="node",
        invariant="magnitude",
        unit="mm",
    )


def _default_load_step(
    model: ModelParams,
    result_fields: list[ResultFieldSpec],
) -> LoadStepSpec:
    return LoadStepSpec(
        step_id="step-1",
        sequence=1,
        analysis=model.analysis.type,
        nlgeom=model.analysis.nlgeom,
        load_case=model.load_case,
        result_fields=[field.name for field in result_fields],
    )

"""MechAgent 核心 Pydantic 数据模型。"""

from mechagent.core.models.case import (
    CASE_SCHEMA_VERSION,
    CoordinateSystem,
    Provenance,
    RegionSpec,
    RequestProvenance,
    SimulationCase,
    SolverControl,
    UnitSystem,
)
from mechagent.core.models.geometry import (
    AnalysisType,
    BCType,
    ElementType,
    GeometryType,
    LoadType,
    MaterialType,
    StiffenerType,
)
from mechagent.core.models.params import (
    AnalysisSpec,
    BCSpec,
    CompositeSpec,
    GeometrySpec,
    LoadSpec,
    MaterialSpec,
    MeshSpec,
    ModelParams,
)

__all__ = [
    "AnalysisSpec",
    "AnalysisType",
    "BCSpec",
    "BCType",
    "CompositeSpec",
    "ElementType",
    "GeometrySpec",
    "GeometryType",
    "LoadSpec",
    "LoadType",
    "MaterialSpec",
    "MaterialType",
    "MeshSpec",
    "ModelParams",
    "CASE_SCHEMA_VERSION",
    "CoordinateSystem",
    "Provenance",
    "RegionSpec",
    "RequestProvenance",
    "SimulationCase",
    "SolverControl",
    "StiffenerType",
    "UnitSystem",
]

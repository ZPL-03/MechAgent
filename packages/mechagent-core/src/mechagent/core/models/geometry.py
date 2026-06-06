"""几何、材料、载荷、边界条件和分析类型枚举。"""

from enum import Enum


class GeometryType(str, Enum):
    """结构几何类型枚举。"""

    PLATE = "plate"
    BEAM = "beam"
    SHELL = "shell"
    SOLID = "solid"
    RVE = "rve"
    STIFFENED_PANEL = "stiffened_panel"


class StiffenerType(str, Enum):
    """加筋结构类型枚举。"""

    NONE = "none"
    T = "t"
    L = "l"
    HAT = "hat"
    Z = "z"


class MaterialType(str, Enum):
    """材料类型枚举。"""

    ISOTROPIC = "isotropic"
    ORTHOTROPIC = "orthotropic"
    COMPOSITE_LAMINATE = "composite_laminate"


class LoadType(str, Enum):
    """载荷类型枚举。"""

    FORCE = "force"
    LINE_LOAD = "line_load"
    PRESSURE = "pressure"
    DISPLACEMENT = "displacement"
    MOMENT = "moment"
    TEMPERATURE = "temperature"


class BCType(str, Enum):
    """边界条件类型枚举。"""

    FIXED = "fixed"
    PINNED = "pinned"
    SIMPLE_SUPPORT = "simple_support"
    SYMMETRY = "symmetry"
    ENCASTRE = "encastre"


class ElementType(str, Enum):
    """有限元单元类型枚举。"""

    B31 = "B31"
    S4 = "S4"
    S4R = "S4R"
    C3D8R = "C3D8R"
    CPS4 = "CPS4"


class AnalysisType(str, Enum):
    """分析类型枚举。"""

    STATIC = "static"
    BUCKLE = "buckle"
    FREQUENCY = "frequency"
    DYNAMIC = "dynamic"
    THERMAL = "thermal"

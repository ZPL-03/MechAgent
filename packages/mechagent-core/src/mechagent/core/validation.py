"""标准验证算例与解析解。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from mechagent.core.adapters.calculix import CalculiXAdapter
from mechagent.core.defaults import DEFAULT_CALCULIX_PATH
from mechagent.core.models import (
    AnalysisSpec,
    AnalysisType,
    BCSpec,
    BCType,
    ElementType,
    GeometrySpec,
    GeometryType,
    LoadSpec,
    LoadType,
    MaterialSpec,
    MeshSpec,
    ModelParams,
)
from mechagent.core.solver import SolverConfig

_SOLVER_SUCCESS_TRUE_VALUES = {"true", "1", "yes", "y", "pass", "passed", "ok", "success"}
_SOLVER_SUCCESS_FALSE_VALUES = {"false", "0", "no", "n", "fail", "failed", "error", "failure"}


@dataclass(frozen=True)
class BenchmarkResult:
    """标准验证算例结果。

    Args:
        case_id: 算例编号。
        description: 算例描述。
        predicted: 框架计算值。
        reference: 解析参考值。
        relative_error: 相对误差。
        tolerance: 验收阈值。
        quantity: 对比物理量名称。
        unit: 物理量单位。
        solver: 求解后端名称。

    Returns:
        BenchmarkResult: 标准验证算例结果。

    Raises:
        TypeError: 当字段类型不匹配时由 dataclass 构造阶段抛出。

    Example:
        >>> BenchmarkResult("TC-01", "悬臂梁", 1.0, 1.0, 0.0, 0.01, "tip", "mm")
        BenchmarkResult(...)
    """

    case_id: str
    description: str
    predicted: float
    reference: float
    relative_error: float
    tolerance: float
    quantity: str
    unit: str
    solver: str

    @property
    def passed(self) -> bool:
        """判断算例是否通过验收。

        Args:
            无。

        Returns:
            bool: 相对误差小于等于阈值时返回 True。

        Raises:
            无。

        Example:
            >>> BenchmarkResult("TC", "", 1, 1, 0, 0.01, "x", "mm").passed
            True
        """

        return self.relative_error <= self.tolerance


def cantilever_tip_deflection(
    load_n: float,
    length_mm: float,
    elastic_modulus_mpa: float,
    width_mm: float,
    height_mm: float,
) -> float:
    """计算矩形截面悬臂梁端点挠度。

    Args:
        load_n: 端部集中力，单位为 N。
        length_mm: 梁长，单位为 mm。
        elastic_modulus_mpa: 弹性模量，单位为 MPa。
        width_mm: 截面宽度，单位为 mm。
        height_mm: 截面高度，单位为 mm。

    Returns:
        float: 端点挠度，单位为 mm。

    Raises:
        ValueError: 当任一几何或材料参数非正时抛出。

    Example:
        >>> round(cantilever_tip_deflection(1000, 1000, 210000, 20, 40), 6)
        14.880952
    """

    _ensure_positive(
        load_n=abs(load_n),
        length_mm=length_mm,
        elastic_modulus_mpa=elastic_modulus_mpa,
        width_mm=width_mm,
        height_mm=height_mm,
    )
    second_moment = width_mm * height_mm**3 / 12.0
    return abs(load_n) * length_mm**3 / (3.0 * elastic_modulus_mpa * second_moment)


def cantilever_uniform_load_tip_deflection(
    line_load_n_per_mm: float,
    length_mm: float,
    elastic_modulus_mpa: float,
    width_mm: float,
    height_mm: float,
) -> float:
    """计算矩形截面悬臂梁全跨均布线载荷端点挠度。

    Args:
        line_load_n_per_mm: 均布线载荷，单位为 N/mm。
        length_mm: 梁长，单位为 mm。
        elastic_modulus_mpa: 弹性模量，单位为 MPa。
        width_mm: 截面宽度，单位为 mm。
        height_mm: 截面高度，单位为 mm。

    Returns:
        float: 端点挠度，单位为 mm。

    Raises:
        ValueError: 当任一几何、材料或载荷参数非正时抛出。

    Example:
        >>> round(cantilever_uniform_load_tip_deflection(1, 1000, 210000, 20, 40), 6)
        5.580357
    """

    _ensure_positive(
        line_load_n_per_mm=abs(line_load_n_per_mm),
        length_mm=length_mm,
        elastic_modulus_mpa=elastic_modulus_mpa,
        width_mm=width_mm,
        height_mm=height_mm,
    )
    second_moment = width_mm * height_mm**3 / 12.0
    return abs(line_load_n_per_mm) * length_mm**4 / (8.0 * elastic_modulus_mpa * second_moment)


def cantilever_root_bending_stress(
    load_n: float,
    length_mm: float,
    width_mm: float,
    height_mm: float,
) -> float:
    """计算矩形截面悬臂梁根部最大弯曲应力。

    Args:
        load_n: 端部集中力，单位为 N。
        length_mm: 梁长，单位为 mm。
        width_mm: 截面宽度，单位为 mm。
        height_mm: 截面高度，单位为 mm。

    Returns:
        float: 最大弯曲应力，单位为 MPa。

    Raises:
        ValueError: 当任一几何参数非正时抛出。

    Example:
        >>> round(cantilever_root_bending_stress(1000, 1000, 20, 40), 3)
        187.5
    """

    _ensure_positive(
        load_n=abs(load_n), length_mm=length_mm, width_mm=width_mm, height_mm=height_mm
    )
    second_moment = width_mm * height_mm**3 / 12.0
    return abs(load_n) * length_mm * (height_mm / 2.0) / second_moment


def axial_bar_end_displacement(
    axial_load_n: float,
    length_mm: float,
    area_mm2: float,
    elastic_modulus_mpa: float,
) -> float:
    """计算等截面杆件轴向端部位移。

    Args:
        axial_load_n: 轴向合力，单位为 N。
        length_mm: 轴向长度，单位为 mm。
        area_mm2: 截面积，单位为 mm^2。
        elastic_modulus_mpa: 弹性模量，单位为 MPa。

    Returns:
        float: 轴向端部位移，单位为 mm。

    Raises:
        ValueError: 当任一参数非正时抛出。

    Example:
        >>> round(axial_bar_end_displacement(4000, 200, 400, 210000), 8)
        0.00952381
    """

    _ensure_positive(
        axial_load_n=abs(axial_load_n),
        length_mm=length_mm,
        area_mm2=area_mm2,
        elastic_modulus_mpa=elastic_modulus_mpa,
    )
    return abs(axial_load_n) * length_mm / (area_mm2 * elastic_modulus_mpa)


def simply_supported_plate_center_deflection(
    pressure_mpa: float,
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    terms: int = 31,
) -> float:
    """计算四边简支矩形薄板均布载荷中心挠度。

    Args:
        pressure_mpa: 均布压力，单位为 MPa，也等价于 N/mm^2。
        length_mm: 板长，单位为 mm。
        width_mm: 板宽，单位为 mm。
        thickness_mm: 板厚，单位为 mm。
        elastic_modulus_mpa: 弹性模量，单位为 MPa。
        poisson_ratio: 泊松比。
        terms: Navier 双重级数截断阶数。

    Returns:
        float: 板中心挠度，单位为 mm。

    Raises:
        ValueError: 当参数非正、泊松比越界或截断阶数小于 1 时抛出。

    Example:
        >>> value = simply_supported_plate_center_deflection(0.01, 300, 200, 5, 70000, 0.3)
        >>> 0.15 < value < 0.16
        True
    """

    _ensure_positive(
        pressure_mpa=abs(pressure_mpa),
        length_mm=length_mm,
        width_mm=width_mm,
        thickness_mm=thickness_mm,
        elastic_modulus_mpa=elastic_modulus_mpa,
    )
    if not -1.0 < poisson_ratio < 0.5:
        msg = "poisson_ratio 必须位于 (-1, 0.5) 区间。"
        raise ValueError(msg)
    if terms < 1:
        msg = "terms 必须大于等于 1。"
        raise ValueError(msg)

    bending_stiffness = elastic_modulus_mpa * thickness_mm**3 / (12.0 * (1.0 - poisson_ratio**2))
    center_deflection = 0.0
    odd_limit = terms + 1 if terms % 2 == 1 else terms
    for m in range(1, odd_limit, 2):
        for n in range(1, odd_limit, 2):
            sign = math.sin(m * math.pi / 2.0) * math.sin(n * math.pi / 2.0)
            load_term = 16.0 * abs(pressure_mpa) / (math.pi**2 * m * n)
            stiffness_term = (
                bending_stiffness * math.pi**4 * ((m / length_mm) ** 2 + (n / width_mm) ** 2) ** 2
            )
            center_deflection += load_term * sign / stiffness_term
    return abs(center_deflection)


def tc01_model_params() -> ModelParams:
    """生成 TC-01 悬臂梁标准算例参数。

    Args:
        无。

    Returns:
        ModelParams: TC-01 标准算例参数。

    Raises:
        pydantic.ValidationError: 当内部默认参数违反 schema 时抛出。

    Example:
        >>> tc01_model_params().geometry.type.value
        'beam'
    """

    return ModelParams(
        geometry=GeometrySpec(
            type=GeometryType.BEAM,
            dimensions={"length": 1000.0, "width": 20.0, "height": 40.0},
        ),
        material=MaterialSpec(E=210000.0, nu=0.3, rho=7.85e-9),
        loads=[
            LoadSpec(
                type=LoadType.FORCE,
                magnitude=1000.0,
                region="tip",
                direction=(0.0, -1.0, 0.0),
            )
        ],
        bcs=[
            BCSpec(
                type=BCType.FIXED,
                region="root",
                dofs=["ux", "uy", "uz", "rx", "ry", "rz"],
                values=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
        ],
        mesh=MeshSpec(element_type=ElementType.B31, seed_size=10.0),
        analysis=AnalysisSpec(type=AnalysisType.STATIC, nlgeom=False),
        case_id="TC-01",
        load_case="cantilever_tip_force",
    )


def tc02_model_params() -> ModelParams:
    """生成 TC-02 四边简支薄板标准算例参数。

    Args:
        无。

    Returns:
        ModelParams: TC-02 标准算例参数。

    Raises:
        pydantic.ValidationError: 当内部默认参数违反 schema 时抛出。

    Example:
        >>> tc02_model_params().geometry.type.value
        'plate'
    """

    return ModelParams(
        geometry=GeometrySpec(
            type=GeometryType.PLATE,
            dimensions={"length": 300.0, "width": 200.0, "thickness": 5.0},
        ),
        material=MaterialSpec(E=70000.0, nu=0.3, rho=2.7e-9),
        loads=[
            LoadSpec(
                type=LoadType.PRESSURE,
                magnitude=0.01,
                region="top_surface",
                direction=(0.0, 0.0, -1.0),
            )
        ],
        bcs=[
            BCSpec(
                type=BCType.SIMPLE_SUPPORT,
                region="all_edges",
                dofs=["uz"],
                values=[0.0],
            ),
        ],
        mesh=MeshSpec(element_type=ElementType.S4, seed_size=5.0),
        analysis=AnalysisSpec(type=AnalysisType.STATIC, nlgeom=False),
        case_id="TC-02",
        load_case="simply_supported_pressure",
    )


def tc03_model_params() -> ModelParams:
    """生成 TC-03 固支长方体端面轴向拉伸标准算例参数。

    Args:
        无。

    Returns:
        ModelParams: TC-03 标准算例参数。

    Raises:
        pydantic.ValidationError: 当内部默认参数违反 schema 时抛出。

    Example:
        >>> tc03_model_params().geometry.type.value
        'solid'
    """

    return ModelParams(
        geometry=GeometrySpec(
            type=GeometryType.SOLID,
            dimensions={"length": 200.0, "width": 20.0, "height": 20.0},
        ),
        material=MaterialSpec(E=210000.0, nu=0.3, rho=7.85e-9),
        loads=[
            LoadSpec(
                type=LoadType.PRESSURE,
                magnitude=10.0,
                region="end_face",
                direction=(1.0, 0.0, 0.0),
            )
        ],
        bcs=[
            BCSpec(
                type=BCType.FIXED,
                region="root",
                dofs=["ux", "uy", "uz"],
                values=[0.0, 0.0, 0.0],
            ),
        ],
        mesh=MeshSpec(element_type=ElementType.C3D8R, seed_size=10.0),
        analysis=AnalysisSpec(type=AnalysisType.STATIC, nlgeom=False),
        case_id="TC-03",
        load_case="fixed_solid_axial_pressure",
    )


def tc04_model_params() -> ModelParams:
    """生成 TC-04 悬臂梁均布线载荷标准算例参数。"""

    return ModelParams(
        geometry=GeometrySpec(
            type=GeometryType.BEAM,
            dimensions={"length": 1000.0, "width": 20.0, "height": 40.0},
        ),
        material=MaterialSpec(E=210000.0, nu=0.3, rho=7.85e-9),
        loads=[
            LoadSpec(
                type=LoadType.LINE_LOAD,
                magnitude=1.0,
                region="span",
                direction=(0.0, -1.0, 0.0),
            )
        ],
        bcs=[
            BCSpec(
                type=BCType.FIXED,
                region="root",
                dofs=["ux", "uy", "uz", "rx", "ry", "rz"],
                values=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            )
        ],
        mesh=MeshSpec(element_type=ElementType.B31, seed_size=10.0),
        analysis=AnalysisSpec(type=AnalysisType.STATIC, nlgeom=False),
        case_id="TC-04",
        load_case="cantilever_uniform_line_load",
    )


def tc05_model_params() -> ModelParams:
    """生成 TC-05 固支长方体端面合力轴向拉伸标准算例参数。"""

    return ModelParams(
        geometry=GeometrySpec(
            type=GeometryType.SOLID,
            dimensions={"length": 200.0, "width": 20.0, "height": 20.0},
        ),
        material=MaterialSpec(E=210000.0, nu=0.3, rho=7.85e-9),
        loads=[
            LoadSpec(
                type=LoadType.FORCE,
                magnitude=4000.0,
                region="end_face",
                direction=(1.0, 0.0, 0.0),
            )
        ],
        bcs=[
            BCSpec(
                type=BCType.FIXED,
                region="root",
                dofs=["ux", "uy", "uz"],
                values=[0.0, 0.0, 0.0],
            ),
        ],
        mesh=MeshSpec(element_type=ElementType.C3D8R, seed_size=10.0),
        analysis=AnalysisSpec(type=AnalysisType.STATIC, nlgeom=False),
        case_id="TC-05",
        load_case="fixed_solid_axial_force",
    )


def evaluate_validation_case(
    case_id: str,
    model_params: ModelParams,
    solver_result: dict[str, Any],
    solver_name: str,
) -> dict[str, Any]:
    """按标准算例验收求解结果。

    Args:
        case_id: 标准算例编号。
        model_params: 结构化仿真参数。
        solver_result: 求解器输出字典。
        solver_name: 求解器名称。

    Returns:
        dict[str, Any]: 带参考值、误差和通过状态的求解结果。

    Raises:
        KeyError: 当求解结果缺少验收物理量时抛出。
        ValueError: 当算例编号未注册时抛出。

    Example:
        >>> params = tc01_model_params()
        >>> data = {"tip_deflection_mm": cantilever_tip_deflection(1000, 1000, 210000, 20, 40)}
        >>> evaluate_validation_case("TC-01", params, data, "calculix")["passed"]
        True
    """

    if case_id == "TC-01":
        reference = _tc01_reference(model_params)
        predicted = float(solver_result["tip_deflection_mm"])
        tolerance = 0.01
        quantity = "tip_deflection"
    elif case_id == "TC-02":
        reference = _tc02_reference(model_params)
        predicted = float(solver_result["center_deflection_mm"])
        tolerance = 0.02
        quantity = "center_deflection"
    elif case_id == "TC-03":
        reference = _tc03_reference(model_params)
        predicted = _axial_displacement_value(solver_result)
        tolerance = 0.08
        quantity = "axial_displacement"
    elif case_id == "TC-04":
        reference = _tc04_reference(model_params)
        predicted = float(solver_result["tip_deflection_mm"])
        tolerance = 0.02
        quantity = "tip_deflection"
    elif case_id == "TC-05":
        reference = _tc03_reference(model_params)
        predicted = _axial_displacement_value(solver_result)
        tolerance = 0.08
        quantity = "axial_displacement"
    else:
        msg = f"未注册标准验证算例: {case_id}"
        raise ValueError(msg)

    relative_error = abs(predicted - reference) / abs(reference)
    solver_success = solver_result_succeeded(solver_result)
    passed = solver_success and relative_error <= tolerance
    return {
        **solver_result,
        "reference": reference,
        "predicted": predicted,
        "relative_error": relative_error,
        "tolerance": tolerance,
        "passed": passed,
        "verification_status": "passed" if passed else "failed",
        "quantity": quantity,
        "unit": "mm",
        "solver": solver_name,
    }


def solver_result_succeeded(solver_result: Mapping[str, Any]) -> bool:
    """解析求解器输出中的执行成功状态。

    Args:
        solver_result: 求解器或插件输出字典。

    Returns:
        bool: `success` 缺省时按成功处理；显式失败值按失败处理。

    Raises:
        无。

    Example:
        >>> solver_result_succeeded({"success": "failed"})
        False
    """

    value = solver_result.get("success", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return False
        return number == 1.0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _SOLVER_SUCCESS_TRUE_VALUES:
            return True
        if text in _SOLVER_SUCCESS_FALSE_VALUES:
            return False
        return False
    return bool(value)


def _tc01_reference(model_params: ModelParams) -> float:
    dimensions = model_params.geometry.dimensions
    load = abs(model_params.loads[0].magnitude)
    return cantilever_tip_deflection(
        load,
        dimensions["length"],
        model_params.material.E,
        dimensions["width"],
        dimensions["height"],
    )


def _tc02_reference(model_params: ModelParams) -> float:
    dimensions = model_params.geometry.dimensions
    pressure = abs(model_params.loads[0].magnitude)
    return simply_supported_plate_center_deflection(
        pressure,
        dimensions["length"],
        dimensions["width"],
        dimensions["thickness"],
        model_params.material.E,
        model_params.material.nu,
        terms=151,
    )


def _tc03_reference(model_params: ModelParams) -> float:
    dimensions = model_params.geometry.dimensions
    load = _solid_axial_load(model_params)
    return axial_bar_end_displacement(
        load,
        dimensions["length"],
        dimensions["width"] * dimensions["height"],
        model_params.material.E,
    )


def _tc04_reference(model_params: ModelParams) -> float:
    dimensions = model_params.geometry.dimensions
    line_load = abs(model_params.loads[0].magnitude)
    return cantilever_uniform_load_tip_deflection(
        line_load,
        dimensions["length"],
        model_params.material.E,
        dimensions["width"],
        dimensions["height"],
    )


def run_tc01(
    solver_path: str = DEFAULT_CALCULIX_PATH,
    work_dir: Path | None = None,
    num_cpus: int = 1,
    timeout: int = 3600,
) -> BenchmarkResult:
    """运行 TC-01 标准基准。

    Args:
        无。

    Returns:
        BenchmarkResult: TC-01 验证结果。

    Raises:
        ValueError: 当内部参数非法时抛出。

    Example:
        >>> run_tc01().passed
        True
    """

    params = tc01_model_params()
    dimensions = params.geometry.dimensions
    load = abs(params.loads[0].magnitude)
    predicted = _run_calculix_static(params, solver_path, work_dir, num_cpus, timeout)[
        "tip_deflection_mm"
    ]
    reference = cantilever_tip_deflection(
        load,
        dimensions["length"],
        params.material.E,
        dimensions["width"],
        dimensions["height"],
    )
    return _benchmark_result(
        case_id="TC-01",
        description="悬臂梁端点静力，线弹性",
        predicted=predicted,
        reference=reference,
        tolerance=0.01,
        quantity="tip_deflection",
        unit="mm",
        solver="calculix",
    )


def run_tc02(
    solver_path: str = DEFAULT_CALCULIX_PATH,
    work_dir: Path | None = None,
    num_cpus: int = 1,
    timeout: int = 3600,
) -> BenchmarkResult:
    """运行 TC-02 四边简支矩形薄板弯曲验证。

    Args:
        无。

    Returns:
        BenchmarkResult: TC-02 验证结果。

    Raises:
        ValueError: 当内部参数非法时抛出。

    Example:
        >>> run_tc02().passed
        True
    """

    params = tc02_model_params()
    dimensions = params.geometry.dimensions
    pressure = abs(params.loads[0].magnitude)
    predicted = _run_calculix_static(params, solver_path, work_dir, num_cpus, timeout)[
        "center_deflection_mm"
    ]
    reference = simply_supported_plate_center_deflection(
        pressure,
        dimensions["length"],
        dimensions["width"],
        dimensions["thickness"],
        params.material.E,
        params.material.nu,
        terms=151,
    )
    return _benchmark_result(
        case_id="TC-02",
        description="四边简支矩形薄板均布载荷弯曲",
        predicted=predicted,
        reference=reference,
        tolerance=0.02,
        quantity="center_deflection",
        unit="mm",
        solver="calculix",
    )


def run_tc03(
    solver_path: str = DEFAULT_CALCULIX_PATH,
    work_dir: Path | None = None,
    num_cpus: int = 1,
    timeout: int = 3600,
) -> BenchmarkResult:
    """运行 TC-03 固支长方体端面轴向拉伸验证。

    Args:
        solver_path: CalculiX 可执行文件路径。
        work_dir: 运行目录。

    Returns:
        BenchmarkResult: TC-03 验证结果。

    Raises:
        ValueError: 当内部参数非法时抛出。

    Example:
        >>> run_tc03().passed
        True
    """

    params = tc03_model_params()
    predicted = _axial_displacement_value(
        _run_calculix_static(params, solver_path, work_dir, num_cpus, timeout)
    )
    reference = _tc03_reference(params)
    return _benchmark_result(
        case_id="TC-03",
        description="固支长方体端面轴向拉伸",
        predicted=predicted,
        reference=reference,
        tolerance=0.08,
        quantity="axial_displacement",
        unit="mm",
        solver="calculix",
    )


def run_tc04(
    solver_path: str = DEFAULT_CALCULIX_PATH,
    work_dir: Path | None = None,
    num_cpus: int = 1,
    timeout: int = 3600,
) -> BenchmarkResult:
    """运行 TC-04 悬臂梁均布线载荷验证。"""

    params = tc04_model_params()
    predicted = _run_calculix_static(params, solver_path, work_dir, num_cpus, timeout)[
        "tip_deflection_mm"
    ]
    reference = _tc04_reference(params)
    return _benchmark_result(
        case_id="TC-04",
        description="悬臂梁全跨均布线载荷静力弯曲",
        predicted=predicted,
        reference=reference,
        tolerance=0.02,
        quantity="tip_deflection",
        unit="mm",
        solver="calculix",
    )


def run_tc05(
    solver_path: str = DEFAULT_CALCULIX_PATH,
    work_dir: Path | None = None,
    num_cpus: int = 1,
    timeout: int = 3600,
) -> BenchmarkResult:
    """运行 TC-05 固支长方体端面合力轴向拉伸验证。"""

    params = tc05_model_params()
    predicted = _axial_displacement_value(
        _run_calculix_static(params, solver_path, work_dir, num_cpus, timeout)
    )
    reference = _tc03_reference(params)
    return _benchmark_result(
        case_id="TC-05",
        description="固支长方体端面合力轴向拉伸",
        predicted=predicted,
        reference=reference,
        tolerance=0.08,
        quantity="axial_displacement",
        unit="mm",
        solver="calculix",
    )


def run_core_benchmarks(
    solver_path: str = DEFAULT_CALCULIX_PATH,
    work_dir: Path | None = None,
    num_cpus: int = 1,
    timeout: int = 3600,
) -> list[BenchmarkResult]:
    """运行核心验证算例。

    Args:
        无。

    Returns:
        list[BenchmarkResult]: 核心标准验证结果。

    Raises:
        ValueError: 当标准算例参数非法时抛出。

    Example:
        >>> all(result.passed for result in run_core_benchmarks())
        True
    """

    root = work_dir or _new_benchmark_root()
    return [
        run_tc01(
            solver_path=solver_path,
            work_dir=root / "TC-01",
            num_cpus=num_cpus,
            timeout=timeout,
        ),
        run_tc02(
            solver_path=solver_path,
            work_dir=root / "TC-02",
            num_cpus=num_cpus,
            timeout=timeout,
        ),
        run_tc03(
            solver_path=solver_path,
            work_dir=root / "TC-03",
            num_cpus=num_cpus,
            timeout=timeout,
        ),
        run_tc04(
            solver_path=solver_path,
            work_dir=root / "TC-04",
            num_cpus=num_cpus,
            timeout=timeout,
        ),
        run_tc05(
            solver_path=solver_path,
            work_dir=root / "TC-05",
            num_cpus=num_cpus,
            timeout=timeout,
        ),
    ]


def _benchmark_result(
    case_id: str,
    description: str,
    predicted: float,
    reference: float,
    tolerance: float,
    quantity: str,
    unit: str,
    solver: str,
) -> BenchmarkResult:
    relative_error = 0.0 if reference == 0 else abs(predicted - reference) / abs(reference)
    return BenchmarkResult(
        case_id=case_id,
        description=description,
        predicted=predicted,
        reference=reference,
        relative_error=relative_error,
        tolerance=tolerance,
        quantity=quantity,
        unit=unit,
        solver=solver,
    )


def _run_calculix_static(
    params: ModelParams,
    solver_path: str,
    work_dir: Path | None,
    num_cpus: int,
    timeout: int,
) -> dict[str, float]:
    active_work_dir = work_dir or _new_benchmark_root() / (params.case_id or "RUN")
    active_work_dir.mkdir(parents=True, exist_ok=True)
    solver = CalculiXAdapter(
        SolverConfig(
            solver_path=solver_path,
            work_dir=active_work_dir,
            num_cpus=num_cpus,
            timeout=timeout,
        )
    )
    result = solver.run(params)
    return {key: float(value) for key, value in result.items() if isinstance(value, (int, float))}


def _ensure_positive(**values: float) -> None:
    invalid = [name for name, value in values.items() if value <= 0]
    if invalid:
        msg = f"参数必须为正数: {', '.join(invalid)}。"
        raise ValueError(msg)


def _solid_axial_load(model_params: ModelParams) -> float:
    dimensions = model_params.geometry.dimensions
    area = dimensions["width"] * dimensions["height"]
    for load in model_params.loads:
        if load.type is LoadType.PRESSURE:
            return abs(load.magnitude) * area
        if load.type is LoadType.FORCE:
            return abs(load.magnitude)
    msg = "实体轴向位移参考解需要 pressure 或 force 载荷。"
    raise ValueError(msg)


def _axial_displacement_value(solver_result: dict[str, Any]) -> float:
    if "axial_displacement_mm" in solver_result:
        return float(solver_result["axial_displacement_mm"])
    return float(solver_result["max_abs_u1_mm"])


def _new_benchmark_root() -> Path:
    timestamp = datetime.now(tz=ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S_%f")
    return Path("mechagent_output/benchmarks") / f"RUN_{timestamp}_{uuid4().hex[:8]}"

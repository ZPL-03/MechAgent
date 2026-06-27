"""CalculiX 求解器适配器。"""

from __future__ import annotations

import re
import shutil
from collections.abc import Sequence
from math import sqrt
from pathlib import Path
from typing import Any, Optional

from mechagent.core.exceptions import SolverError
from mechagent.core.executor import (
    AbstractJobExecutor,
    ExecutorConfig,
    JobSpec,
    JobStatus,
    LocalCommandExecutor,
)
from mechagent.core.models import (
    AnalysisType,
    BCType,
    ElementType,
    GeometryType,
    LoadSpec,
    LoadType,
    MaterialType,
    ModelParams,
)
from mechagent.core.paths import safe_file_stem
from mechagent.core.solver import AbstractSolver, SolverConfig, SolverResult

_FRD_FLOAT_PATTERN = re.compile(r"[+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[Ee][+-]\d{2,3})?")


class CalculiXAdapter(AbstractSolver):
    """CalculiX `ccx` 求解器适配器。

    Args:
        config: 求解器配置。

    Returns:
        CalculiXAdapter: CalculiX 适配器实例。

    Raises:
        SolverError: 当输入模型不在适配器支持范围内时抛出。

    Example:
        >>> from mechagent.core.solver import SolverConfig
        >>> CalculiXAdapter(SolverConfig(solver_path="ccx"))
        <mechagent.core.adapters.calculix.CalculiXAdapter object at ...>
    """

    def __init__(
        self, config: SolverConfig, executor: Optional[AbstractJobExecutor] = None
    ) -> None:
        """构造 CalculiX 适配器。

        Args:
            config: 求解器配置。
            executor: 作业执行器；为空时使用同步本地命令执行器。注入远程/HPC/容器执行器
                可在不改求解逻辑的前提下切换执行后端。

        Returns:
            无。

        Raises:
            OSError: 当工作目录无法创建时抛出。
        """

        super().__init__(config)
        self.executor: AbstractJobExecutor = executor or LocalCommandExecutor(
            ExecutorConfig(work_dir=config.work_dir, default_timeout=config.timeout)
        )

    def generate_input(self, model_params: ModelParams) -> Path:
        """生成 CalculiX `.inp` 输入文件。

        Args:
            model_params: 结构化仿真参数。

        Returns:
            Path: `.inp` 文件路径。

        Raises:
            SolverError: 当分析类型或几何类型不受支持时抛出。

        Example:
            >>> adapter.generate_input(tc01_model_params()).suffix
            '.inp'
        """

        if model_params.analysis.type is not AnalysisType.STATIC:
            msg = f"CalculiXAdapter 不支持分析类型 {model_params.analysis.type.value}。"
            raise SolverError(msg)
        if model_params.analysis.nlgeom:
            msg = "CalculiXAdapter 支持线性静力分析，要求 nlgeom=False。"
            raise SolverError(msg)
        _ensure_supported_material(model_params)
        mesh_file = _mesh_file_from_model(model_params)
        if model_params.geometry.type is GeometryType.BEAM:
            content = _beam_static_inp(model_params, mesh_file)
        elif model_params.geometry.type is GeometryType.PLATE:
            content = _plate_static_inp(model_params, mesh_file)
        elif model_params.geometry.type is GeometryType.SOLID:
            content = _solid_static_inp(model_params, mesh_file)
        else:
            msg = f"CalculiXAdapter 不支持 {model_params.geometry.type.value} 几何输入生成。"
            raise SolverError(msg)

        case_id = safe_file_stem(model_params.case_id, "RUN_calculix")
        inp_path = self.config.work_dir / f"{case_id}.inp"
        inp_path.write_text(content, encoding="utf-8")
        return inp_path

    def solve(self, input_file: Path) -> SolverResult:
        """调用 `ccx` 执行求解。

        Args:
            input_file: CalculiX `.inp` 输入文件。

        Returns:
            SolverResult: 求解器执行结果。

        Raises:
            SolverError: 当输入文件不存在时抛出。

        Example:
            >>> adapter.solve(Path("model.inp"))
            SolverResult(...)
        """

        if not input_file.exists():
            msg = f"CalculiX 输入文件不存在: {input_file}"
            raise SolverError(msg)

        executable = _resolve_executable(str(self.config.solver_path))
        if executable is None:
            return SolverResult(
                success=False,
                wall_time=0.0,
                error_message=f"未找到 CalculiX 可执行文件: {self.config.solver_path}",
            )

        job_name = input_file.stem
        spec = JobSpec(
            command=[executable, job_name],
            work_dir=input_file.parent,
            env={"OMP_NUM_THREADS": str(self.config.num_cpus)},
            timeout=self.config.timeout,
        )
        job_result = self.executor.run(spec)
        output_files = sorted(input_file.parent.glob(f"{job_name}.*"))
        if job_result.status is JobStatus.SUCCEEDED:
            return SolverResult(
                success=True,
                wall_time=job_result.wall_time,
                output_files=output_files,
                summary={"job_name": job_name, "returncode": job_result.return_code},
            )
        if job_result.return_code is not None and job_result.return_code != 0:
            error_message = job_result.stderr.strip() or job_result.stdout.strip()
        else:
            error_message = job_result.error_message or "CalculiX 求解失败。"
        return SolverResult(
            success=False,
            wall_time=job_result.wall_time,
            output_files=output_files,
            error_message=error_message,
        )

    def extract_results(self, result: SolverResult) -> dict[str, Any]:
        """提取 CalculiX 求解结果元数据。

        Args:
            result: 求解器执行结果。

        Returns:
            dict[str, Any]: 输出文件列表、执行摘要和解析标量。

        Raises:
            SolverError: 当求解失败时抛出。

        Example:
            >>> adapter.extract_results(SolverResult(success=True, wall_time=0, summary={}))
            {'success': True, 'output_files': []}
        """

        if not result.success:
            raise SolverError(result.error_message or "CalculiX 求解失败。")
        frd_file = _first_file_with_suffix(result.output_files, ".frd")
        node_coordinates = _result_node_coordinates(result.output_files)
        parsed = _parse_frd(frd_file, node_coordinates) if frd_file else {}
        return {
            "success": True,
            "output_files": [str(path) for path in result.output_files],
            **parsed,
            **result.summary,
        }


def _beam_static_inp(model_params: ModelParams, mesh_file: Path | None = None) -> str:
    _ensure_supported_beam_case(model_params)
    dimensions = model_params.geometry.dimensions
    length = dimensions["length"]
    width = dimensions["width"]
    height = dimensions["height"]
    elastic_modulus = model_params.material.E
    poisson_ratio = model_params.material.nu
    if mesh_file:
        mesh_lines, nodes, _ = _read_mesh_sections(mesh_file)
        x_values = [point[0] for point in nodes.values()]
        root_nodes = _node_ids_on_axis(nodes, axis=0, target=min(x_values))
        tip_nodes = _node_ids_on_axis(nodes, axis=0, target=max(x_values))
    else:
        element_count = max(4, int(round(length / model_params.mesh.seed_size)))
        nodes = {}
        mesh_lines = ["*NODE"]
        for index in range(element_count + 1):
            node_id = index + 1
            x = length * index / element_count
            nodes[node_id] = (x, 0.0, 0.0)
            mesh_lines.append(f"{node_id}, {x:.12g}, 0., 0.")
        mesh_lines.append("*ELEMENT, TYPE=B31, ELSET=EALL")
        for index in range(element_count):
            element_id = index + 1
            mesh_lines.append(f"{element_id}, {element_id}, {element_id + 1}")
        root_nodes = [1]
        tip_nodes = [element_count + 1]

    force = _first_load_spec(model_params, LoadType.FORCE)
    line_load = _first_load_spec(model_params, LoadType.LINE_LOAD)
    if force is not None:
        load_lines = _beam_point_load_lines(force, tip_nodes)
    elif line_load is not None:
        load_lines = _beam_line_load_lines(line_load, nodes)
    else:
        msg = "梁静力分析缺少 force 或 line_load 载荷。"
        raise SolverError(msg)

    lines = [
        "*HEADING",
        "MechAgent static beam",
        *mesh_lines,
        "*MATERIAL, NAME=MAT",
        "*ELASTIC",
        f"{elastic_modulus:.12g}, {poisson_ratio:.12g}",
        "*BEAM SECTION, ELSET=EALL, MATERIAL=MAT, SECTION=RECT",
        f"{width:.12g}, {height:.12g}",
        "0., 0., 1.",
        "*NSET, NSET=ROOT",
        *_format_id_rows(root_nodes),
        "*NSET, NSET=TIP",
        *_format_id_rows(tip_nodes),
        "*BOUNDARY",
        "ROOT, 1, 6, 0.",
        "*STEP",
        "*STATIC",
        "*CLOAD",
        *load_lines,
        "*NODE FILE",
        "U",
        "*EL FILE",
        "S",
        "*END STEP",
        "",
    ]
    return "\n".join(lines)


def _plate_static_inp(model_params: ModelParams, mesh_file: Path | None = None) -> str:
    pressure_load = _ensure_supported_plate_case(model_params)
    dimensions = model_params.geometry.dimensions
    length = dimensions["length"]
    width = dimensions["width"]
    thickness = dimensions["thickness"]
    elastic_modulus = model_params.material.E
    poisson_ratio = model_params.material.nu
    if mesh_file:
        mesh_lines, nodes, elements = _read_mesh_sections(mesh_file)
    else:
        mesh_lines, nodes, elements = _regular_plate_mesh(
            length,
            width,
            model_params.mesh.seed_size,
        )

    min_x = min(point[0] for point in nodes.values())
    max_x = max(point[0] for point in nodes.values())
    min_y = min(point[1] for point in nodes.values())
    max_y = max(point[1] for point in nodes.values())
    edge_nodes = [
        node_id
        for node_id, point in nodes.items()
        if _is_close(point[0], min_x, max_x - min_x)
        or _is_close(point[0], max_x, max_x - min_x)
        or _is_close(point[1], min_y, max_y - min_y)
        or _is_close(point[1], max_y, max_y - min_y)
    ]
    lines = [
        "*HEADING",
        "MechAgent static plate",
        *mesh_lines,
        "*NSET, NSET=EDGE",
        *_format_id_rows(edge_nodes),
        "*NSET, NSET=PINXY",
        str(_nearest_node(nodes, target_x=min_x, target_y=min_y)),
        "*NSET, NSET=PINY",
        str(_nearest_node(nodes, target_x=max_x, target_y=min_y)),
    ]
    lines.extend(
        [
            "*MATERIAL, NAME=MAT",
            "*ELASTIC",
            f"{elastic_modulus:.12g}, {poisson_ratio:.12g}",
            "*SHELL SECTION, ELSET=EALL, MATERIAL=MAT",
            f"{thickness:.12g}",
            "*BOUNDARY",
            "EDGE, 3, 3, 0.",
            "PINXY, 1, 2, 0.",
            "PINY, 2, 2, 0.",
            "*STEP",
            "*STATIC",
            "*CLOAD",
        ]
    )

    lines.extend(_plate_nodal_load_lines(nodes, elements, pressure_load))

    lines.extend(["*NODE FILE", "U", "*EL FILE", "S", "*END STEP", ""])
    return "\n".join(lines)


def _solid_static_inp(model_params: ModelParams, mesh_file: Path | None = None) -> str:
    _ensure_supported_solid_case(model_params)
    dimensions = model_params.geometry.dimensions
    length = dimensions["length"]
    width = dimensions["width"]
    height = dimensions["height"]
    elastic_modulus = model_params.material.E
    poisson_ratio = model_params.material.nu
    if mesh_file:
        mesh_lines, nodes, _ = _read_mesh_sections(mesh_file)
        solid_elements = _parse_hex_elements(mesh_lines)
        if not solid_elements:
            msg = f"实体网格文件缺少 C3D8 单元: {mesh_file}"
            raise SolverError(msg)
    else:
        mesh_lines, nodes, solid_elements = _regular_solid_mesh(
            length,
            width,
            height,
            model_params.mesh.seed_size,
        )

    x_values = [point[0] for point in nodes.values()]
    min_x = min(x_values)
    max_x = max(x_values)
    root_nodes = _node_ids_on_axis(nodes, axis=0, target=min_x)
    load = _first_load_spec(model_params, LoadType.PRESSURE)
    if load is None:
        load = _first_load_spec(model_params, LoadType.FORCE)
    if load is None:
        msg = "实体静力分析缺少 pressure 或 force 端面载荷。"
        raise SolverError(msg)
    load_lines = _solid_end_face_load_lines(nodes, solid_elements, load, target_x=max_x)

    lines = [
        "*HEADING",
        "MechAgent static solid",
        *mesh_lines,
        "*NSET, NSET=ROOT",
        *_format_id_rows(root_nodes),
        "*MATERIAL, NAME=MAT",
        "*ELASTIC",
        f"{elastic_modulus:.12g}, {poisson_ratio:.12g}",
        "*SOLID SECTION, ELSET=EALL, MATERIAL=MAT",
        "*BOUNDARY",
        "ROOT, 1, 3, 0.",
        "*STEP",
        "*STATIC",
        "*CLOAD",
        *load_lines,
        "*NODE FILE",
        "U",
        "*EL FILE",
        "S",
        "*END STEP",
        "",
    ]
    return "\n".join(lines)


def _regular_plate_mesh(
    length: float,
    width: float,
    seed_size: float,
) -> tuple[list[str], dict[int, tuple[float, float, float]], list[tuple[int, ...]]]:
    nx = max(4, int(round(length / seed_size)))
    ny = max(4, int(round(width / seed_size)))

    def node_id(i: int, j: int) -> int:
        return j * (nx + 1) + i + 1

    nodes: dict[int, tuple[float, float, float]] = {}
    elements: list[tuple[int, ...]] = []
    lines = ["*NODE"]
    for j in range(ny + 1):
        y = width * j / ny
        for i in range(nx + 1):
            node = node_id(i, j)
            x = length * i / nx
            nodes[node] = (x, y, 0.0)
            lines.append(f"{node}, {x:.12g}, {y:.12g}, 0.")
    lines.append("*ELEMENT, TYPE=S4, ELSET=EALL")
    element_id = 1
    for j in range(ny):
        for i in range(nx):
            element_nodes = (
                node_id(i, j),
                node_id(i + 1, j),
                node_id(i + 1, j + 1),
                node_id(i, j + 1),
            )
            elements.append(element_nodes)
            lines.append(
                f"{element_id}, {element_nodes[0]}, {element_nodes[1]}, "
                f"{element_nodes[2]}, {element_nodes[3]}"
            )
            element_id += 1
    return lines, nodes, elements


def _regular_solid_mesh(
    length: float,
    width: float,
    height: float,
    seed_size: float,
) -> tuple[
    list[str],
    dict[int, tuple[float, float, float]],
    list[tuple[int, int, int, int, int, int, int, int]],
]:
    nx = max(1, int(round(length / seed_size)))
    ny = max(1, int(round(width / seed_size)))
    nz = max(1, int(round(height / seed_size)))

    def node_id(i: int, j: int, k: int) -> int:
        return k * (ny + 1) * (nx + 1) + j * (nx + 1) + i + 1

    nodes: dict[int, tuple[float, float, float]] = {}
    elements: list[tuple[int, int, int, int, int, int, int, int]] = []
    lines = ["*NODE"]
    for k in range(nz + 1):
        z = height * k / nz
        for j in range(ny + 1):
            y = width * j / ny
            for i in range(nx + 1):
                node = node_id(i, j, k)
                point = (length * i / nx, y, z)
                nodes[node] = point
                lines.append(f"{node}, {point[0]:.12g}, {point[1]:.12g}, {point[2]:.12g}")

    lines.append("*ELEMENT, TYPE=C3D8R, ELSET=EALL")
    element_id = 1
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                element_nodes = (
                    node_id(i, j, k),
                    node_id(i + 1, j, k),
                    node_id(i + 1, j + 1, k),
                    node_id(i, j + 1, k),
                    node_id(i, j, k + 1),
                    node_id(i + 1, j, k + 1),
                    node_id(i + 1, j + 1, k + 1),
                    node_id(i, j + 1, k + 1),
                )
                elements.append(element_nodes)
                lines.append(f"{element_id}, {', '.join(str(node) for node in element_nodes)}")
                element_id += 1
    return lines, nodes, elements


def _mesh_file_from_model(model_params: ModelParams) -> Path | None:
    if model_params.mesh_file is None:
        return None
    path = Path(model_params.mesh_file)
    if not path.exists():
        msg = f"model_params.mesh_file 指向的网格文件不存在: {path}"
        raise SolverError(msg)
    return path


def _ensure_supported_material(model_params: ModelParams) -> None:
    if (
        model_params.material.type is not MaterialType.ISOTROPIC
        or model_params.material.composite is not None
    ):
        msg = "CalculiXAdapter 支持各向同性线弹性材料。"
        raise SolverError(msg)


def _ensure_supported_beam_case(model_params: ModelParams) -> None:
    _ensure_required_dimensions(model_params, ("length", "width", "height"), "CalculiX 梁静力路径")
    if model_params.mesh.element_type is not ElementType.B31:
        msg = "CalculiX 梁静力路径支持 B31 单元。"
        raise SolverError(msg)
    if not _has_bc(
        model_params,
        types={BCType.FIXED, BCType.ENCASTRE},
        regions={"root", "fixed_end", "left_end"},
        dofs={"ux", "uy", "uz", "rx", "ry", "rz"},
    ):
        msg = "CalculiX 梁静力路径需要 root 固支边界并约束 ux/uy/uz/rx/ry/rz。"
        raise SolverError(msg)
    load = _single_supported_load(
        model_params,
        {
            LoadType.FORCE: {"tip", "free_end", "right_end"},
            LoadType.LINE_LOAD: {"span", "full_span"},
        },
        "梁静力路径支持 tip 集中力或 span 全跨均布线载荷。",
    )
    if not _is_axis_aligned(load.direction, 1):
        msg = "CalculiX 梁静力路径支持纯全局 Y 向横向载荷。"
        raise SolverError(msg)


def _ensure_supported_plate_case(model_params: ModelParams) -> LoadSpec:
    _ensure_required_dimensions(
        model_params,
        ("length", "width", "thickness"),
        "CalculiX 板静力路径",
    )
    if model_params.mesh.element_type is not ElementType.S4:
        msg = "CalculiX 板静力路径支持 S4 壳单元。"
        raise SolverError(msg)
    if not _has_bc(
        model_params,
        types={BCType.SIMPLE_SUPPORT},
        regions={"all_edges", "edges"},
        dofs={"uz"},
    ):
        msg = "CalculiX 板静力路径需要 all_edges 简支边界并约束 uz。"
        raise SolverError(msg)
    load = _single_supported_load(
        model_params,
        {LoadType.PRESSURE: {"top_surface", "surface", "plate", "all"}},
        "板静力路径支持 top_surface 均布压力。",
    )
    if not _is_axis_aligned(load.direction, 2):
        msg = "CalculiX 板静力路径支持纯全局 Z 向面载荷。"
        raise SolverError(msg)
    return load


def _ensure_supported_solid_case(model_params: ModelParams) -> None:
    _ensure_required_dimensions(
        model_params,
        ("length", "width", "height"),
        "CalculiX 实体静力路径",
    )
    if model_params.mesh.element_type is not ElementType.C3D8R:
        msg = "CalculiX 实体静力路径支持 C3D8R 单元。"
        raise SolverError(msg)
    if not _has_bc(
        model_params,
        types={BCType.FIXED, BCType.ENCASTRE},
        regions={"root", "fixed_end", "left_end"},
        dofs={"ux", "uy", "uz"},
    ):
        msg = "CalculiX 实体静力路径需要 root 固定边界并约束 ux/uy/uz。"
        raise SolverError(msg)
    load = _single_supported_load(
        model_params,
        {
            LoadType.PRESSURE: {"end_face", "right_end", "free_end"},
            LoadType.FORCE: {"end_face", "right_end", "free_end"},
        },
        "实体静力路径支持 end_face 轴向压力或端面合力。",
    )
    if not _is_axis_aligned(load.direction, 0):
        msg = "CalculiX 实体静力路径支持纯全局 X 向端面轴向载荷。"
        raise SolverError(msg)


def _has_bc(
    model_params: ModelParams,
    *,
    types: set[BCType],
    regions: set[str],
    dofs: set[str],
) -> bool:
    for bc in model_params.bcs:
        if bc.type not in types:
            continue
        if _region_key(bc.region) not in regions:
            continue
        if dofs.issubset({_dof_key(dof) for dof in bc.dofs}):
            return True
    return False


def _single_supported_load(
    model_params: ModelParams,
    allowed: dict[LoadType, set[str]],
    error_message: str,
) -> LoadSpec:
    if len(model_params.loads) != 1:
        raise SolverError(error_message)
    supported = [
        load
        for load in model_params.loads
        if load.type in allowed and _region_key(load.region) in allowed[load.type]
    ]
    if len(supported) != 1:
        raise SolverError(error_message)
    return supported[0]


def _ensure_required_dimensions(
    model_params: ModelParams,
    required: tuple[str, ...],
    context: str,
) -> None:
    missing = [name for name in required if name not in model_params.geometry.dimensions]
    if missing:
        msg = f"{context}缺少几何尺寸字段: {', '.join(missing)}。"
        raise SolverError(msg)


def _is_axis_aligned(direction: tuple[float, float, float], axis: int) -> bool:
    axis_value = abs(direction[axis])
    if axis_value <= 1.0e-12:
        return False
    tolerance = max(1.0e-12, axis_value * 1.0e-9)
    return all(abs(value) <= tolerance for index, value in enumerate(direction) if index != axis)


def _region_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _dof_key(value: str) -> str:
    return value.strip().lower()


def _read_mesh_sections(
    path: Path,
) -> tuple[list[str], dict[int, tuple[float, float, float]], list[tuple[int, ...]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    nodes = _parse_nodes(lines)
    if not nodes:
        msg = f"网格文件缺少 *NODE 数据: {path}"
        raise SolverError(msg)
    elements = _parse_shell_elements(lines)
    has_element_section = any(line.strip().upper().startswith("*ELEMENT") for line in lines)
    if not has_element_section:
        msg = f"网格文件缺少 *ELEMENT 数据: {path}"
        raise SolverError(msg)
    return [line for line in lines if line.strip()], nodes, elements


def _parse_nodes(lines: list[str]) -> dict[int, tuple[float, float, float]]:
    nodes: dict[int, tuple[float, float, float]] = {}
    active = False
    for raw in lines:
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("*NODE"):
            active = True
            continue
        if active and line.startswith("*"):
            active = False
            continue
        if not active or not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            continue
        nodes[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
    return nodes


def _parse_shell_elements(lines: list[str]) -> list[tuple[int, ...]]:
    elements: list[tuple[int, ...]] = []
    active = False
    expected_nodes = 0
    for raw in lines:
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("*ELEMENT"):
            active = "S3" in upper or "S4" in upper
            expected_nodes = 3 if "S3" in upper else 4 if "S4" in upper else 0
            continue
        if active and line.startswith("*"):
            active = False
            expected_nodes = 0
            continue
        if not active or not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if expected_nodes and len(parts) >= expected_nodes + 1:
            elements.append(tuple(int(part) for part in parts[1 : expected_nodes + 1]))
    return elements


def _parse_hex_elements(lines: list[str]) -> list[tuple[int, int, int, int, int, int, int, int]]:
    elements: list[tuple[int, int, int, int, int, int, int, int]] = []
    active = False
    for raw in lines:
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("*ELEMENT"):
            active = "C3D8" in upper
            continue
        if active and line.startswith("*"):
            active = False
            continue
        if not active or not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 9:
            elements.append(
                (
                    int(parts[1]),
                    int(parts[2]),
                    int(parts[3]),
                    int(parts[4]),
                    int(parts[5]),
                    int(parts[6]),
                    int(parts[7]),
                    int(parts[8]),
                )
            )
    return elements


def _node_ids_on_axis(
    nodes: dict[int, tuple[float, float, float]],
    axis: int,
    target: float,
) -> list[int]:
    values = [point[axis] for point in nodes.values()]
    span = max(values) - min(values)
    return [node_id for node_id, point in nodes.items() if _is_close(point[axis], target, span)]


def _nearest_node(
    nodes: dict[int, tuple[float, float, float]],
    target_x: float,
    target_y: float,
) -> int:
    return min(
        nodes,
        key=lambda node_id: (
            (nodes[node_id][0] - target_x) ** 2 + (nodes[node_id][1] - target_y) ** 2
        ),
    )


def _plate_nodal_load_lines(
    nodes: dict[int, tuple[float, float, float]],
    elements: list[tuple[int, ...]],
    load: LoadSpec,
) -> list[str]:
    dof, sign = _load_dof_and_sign(load)
    if dof != 3:
        msg = "板面载荷必须沿全局 Z 向。"
        raise SolverError(msg)
    if not elements:
        msg = "板面载荷需要至少一个 S3 或 S4 壳单元。"
        raise SolverError(msg)
    loads = dict.fromkeys(nodes, 0.0)
    for element in elements:
        area = _polygon_area([nodes[node_id] for node_id in element])
        nodal_force = sign * abs(load.magnitude) * area / len(element)
        for node_id in element:
            loads[node_id] += nodal_force
    return [f"{node_id}, 3, {force:.12g}" for node_id, force in sorted(loads.items())]


def _solid_end_face_load_lines(
    nodes: dict[int, tuple[float, float, float]],
    elements: Sequence[Sequence[int]],
    load: LoadSpec,
    target_x: float,
) -> list[str]:
    dof, sign = _load_dof_and_sign(load)
    face_loads = dict.fromkeys(nodes, 0.0)
    face_areas: dict[int, float] = dict.fromkeys(nodes, 0.0)
    for element in elements:
        if len(element) < 8:
            continue
        end_face = (element[1], element[2], element[6], element[5])
        if all(_is_close(nodes[node_id][0], target_x, target_x) for node_id in end_face):
            area = _quad_area([nodes[node_id] for node_id in end_face])
            for node_id in end_face:
                face_areas[node_id] += area / 4.0

    total_area = sum(face_areas.values())
    if total_area <= 0:
        msg = "实体端面载荷未找到可施加载荷的端面节点。"
        raise SolverError(msg)

    if load.type is LoadType.PRESSURE:
        for node_id, area in face_areas.items():
            face_loads[node_id] = sign * abs(load.magnitude) * area
    else:
        for node_id, area in face_areas.items():
            face_loads[node_id] = sign * abs(load.magnitude) * area / total_area
    return [
        f"{node_id}, {dof}, {force:.12g}"
        for node_id, force in sorted(face_loads.items())
        if abs(force) > 0.0
    ]


def _beam_point_load_lines(load: LoadSpec, tip_nodes: list[int]) -> list[str]:
    dof, sign = _load_dof_and_sign(load)
    load_per_tip_node = sign * abs(load.magnitude) / len(tip_nodes)
    return [f"{node_id}, {dof}, {load_per_tip_node:.12g}" for node_id in tip_nodes]


def _beam_line_load_lines(
    load: LoadSpec,
    nodes: dict[int, tuple[float, float, float]],
) -> list[str]:
    dof, sign = _load_dof_and_sign(load)
    ordered = sorted(nodes, key=lambda node_id: nodes[node_id][0])
    if len(ordered) < 2:
        msg = "梁线载荷需要至少两个节点。"
        raise SolverError(msg)

    lines: list[str] = []
    for index, node_id in enumerate(ordered):
        if index == 0:
            tributary_length = (nodes[ordered[1]][0] - nodes[node_id][0]) / 2.0
        elif index == len(ordered) - 1:
            tributary_length = (nodes[node_id][0] - nodes[ordered[index - 1]][0]) / 2.0
        else:
            tributary_length = (nodes[ordered[index + 1]][0] - nodes[ordered[index - 1]][0]) / 2.0
        force = sign * abs(load.magnitude) * abs(tributary_length)
        lines.append(f"{node_id}, {dof}, {force:.12g}")
    return lines


def _load_dof_and_sign(load: LoadSpec) -> tuple[int, float]:
    direction = load.direction
    x_component = direction[0]
    y_component = direction[1]
    z_component = direction[2]
    if abs(x_component) > max(abs(y_component), abs(z_component)):
        return (1, 1.0 if x_component >= 0 else -1.0)
    if abs(z_component) > abs(y_component):
        return (3, 1.0 if z_component >= 0 else -1.0)
    return (2, 1.0 if y_component >= 0 else -1.0)


def _quad_area(points: list[tuple[float, float, float]]) -> float:
    if len(points) != 4:
        msg = "四边形面积计算需要 4 个节点。"
        raise SolverError(msg)
    return _triangle_area(points[0], points[1], points[2]) + _triangle_area(
        points[0],
        points[2],
        points[3],
    )


def _polygon_area(points: list[tuple[float, float, float]]) -> float:
    if len(points) == 3:
        return _triangle_area(points[0], points[1], points[2])
    if len(points) == 4:
        return _quad_area(points)
    if len(points) > 4:
        return sum(
            _triangle_area(points[0], points[index], points[index + 1])
            for index in range(1, len(points) - 1)
        )
    msg = "壳单元面积计算需要至少 3 个节点。"
    raise SolverError(msg)


def _triangle_area(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return 0.5 * sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2)


def _is_close(value: float, target: float, span: float) -> bool:
    return abs(value - target) <= max(1e-8, abs(span) * 1e-8)


def _format_id_rows(ids: list[int], row_size: int = 16) -> list[str]:
    return [
        ", ".join(str(item) for item in ids[index : index + row_size])
        for index in range(0, len(ids), row_size)
    ]


def _first_load_spec(params: ModelParams, load_type: LoadType) -> LoadSpec | None:
    for load in params.loads:
        if load.type is load_type:
            return load
    return None


def _resolve_executable(executable: str) -> str | None:
    path = Path(executable)
    if path.exists():
        return str(path)
    return shutil.which(executable)


def _first_file_with_suffix(paths: list[Path], suffix: str) -> Path | None:
    for path in paths:
        if path.suffix.lower() == suffix:
            return path
    return None


def _result_node_coordinates(paths: list[Path]) -> dict[int, tuple[float, float, float]]:
    input_file = _first_file_with_suffix(paths, ".inp")
    if input_file is None:
        return {}
    try:
        return _parse_nodes(input_file.read_text(encoding="utf-8").splitlines())
    except (OSError, ValueError):
        return {}


def _parse_frd(
    path: Path,
    node_coordinates: dict[int, tuple[float, float, float]] | None = None,
) -> dict[str, Any]:
    displacements: dict[int, tuple[float, float, float]] = {}
    stresses: dict[int, tuple[float, float, float, float, float, float]] = {}
    mode: str | None = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(" -4  DISP"):
            mode = "disp"
            continue
        if line.startswith(" -4  STRESS"):
            mode = "stress"
            continue
        if line.startswith(" -3"):
            mode = None
            continue
        if not line.startswith(" -1") or mode is None:
            continue
        parsed = _parse_frd_data_line(line[3:])
        if parsed is None:
            continue
        node, values = parsed
        if mode == "disp" and len(values) >= 4:
            displacements[node] = (values[1], values[2], values[3])
        if mode == "stress" and len(values) >= 7:
            stresses[node] = (
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
            )
    result: dict[str, Any] = {}
    if displacements:
        max_u1 = max((abs(value[0]) for value in displacements.values()), default=0.0)
        max_u2 = max((abs(value[1]) for value in displacements.values()), default=0.0)
        max_u3 = max((abs(value[2]) for value in displacements.values()), default=0.0)
        result["max_abs_u1_mm"] = max_u1
        result["max_abs_u2_mm"] = max_u2
        result["max_abs_u3_mm"] = max_u3
        result["max_displacement_mm"] = max(max_u1, max_u2, max_u3)
        result["displacement_node_count"] = len(displacements)
        if node_coordinates:
            tip_deflection = _max_abs_component_on_axis(
                displacements,
                node_coordinates,
                component=1,
                axis=0,
                target=max(point[0] for point in node_coordinates.values()),
            )
            center_deflection = _abs_component_near_bbox_center(
                displacements,
                node_coordinates,
                component=2,
            )
            axial_displacement = _max_abs_component_on_axis(
                displacements,
                node_coordinates,
                component=0,
                axis=0,
                target=max(point[0] for point in node_coordinates.values()),
            )
            result["tip_deflection_mm"] = tip_deflection if tip_deflection is not None else max_u2
            result["center_deflection_mm"] = (
                center_deflection if center_deflection is not None else max_u3
            )
            result["axial_displacement_mm"] = (
                axial_displacement if axial_displacement is not None else max_u1
            )
        else:
            result["tip_deflection_mm"] = max_u2
            result["center_deflection_mm"] = max_u3
            result["axial_displacement_mm"] = max_u1
    if stresses:
        max_sxx = max((abs(value[0]) for value in stresses.values()), default=0.0)
        result["max_stress_mpa"] = max_sxx
        result["stress_node_count"] = len(stresses)
    return result


def _max_abs_component_on_axis(
    displacements: dict[int, tuple[float, float, float]],
    nodes: dict[int, tuple[float, float, float]],
    *,
    component: int,
    axis: int,
    target: float,
) -> float | None:
    coordinates = [point[axis] for point in nodes.values()]
    span = max(coordinates) - min(coordinates)
    values = [
        abs(displacements[node_id][component])
        for node_id, point in nodes.items()
        if node_id in displacements and _is_close(point[axis], target, span)
    ]
    if not values:
        return None
    return max(values)


def _abs_component_near_bbox_center(
    displacements: dict[int, tuple[float, float, float]],
    nodes: dict[int, tuple[float, float, float]],
    *,
    component: int,
) -> float | None:
    common_nodes = [node_id for node_id in nodes if node_id in displacements]
    if not common_nodes:
        return None
    x_values = [nodes[node_id][0] for node_id in common_nodes]
    y_values = [nodes[node_id][1] for node_id in common_nodes]
    target_x = 0.5 * (min(x_values) + max(x_values))
    target_y = 0.5 * (min(y_values) + max(y_values))
    node_id = min(
        common_nodes,
        key=lambda item: (nodes[item][0] - target_x) ** 2 + (nodes[item][1] - target_y) ** 2,
    )
    return abs(displacements[node_id][component])


def _parse_frd_data_line(text: str) -> tuple[int, list[float]] | None:
    node_text = text[:10].strip()
    data_text = text[10:]
    if node_text.isdigit():
        node = int(node_text)
    else:
        match = re.match(r"\s*(\d+)(?=[+-])", text)
        if not match:
            return None
        node = int(match.group(1))
        data_text = text[match.end() :]
    values = [float(token) for token in _FRD_FLOAT_PATTERN.findall(data_text)]
    return node, [float(node), *values]

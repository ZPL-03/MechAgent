"""标准几何网格适配器。"""

from __future__ import annotations

from pathlib import Path

import gmsh

from mechagent.core.mesher import AbstractMesher, MeshResult
from mechagent.core.models import GeometryType, ModelParams
from mechagent.core.paths import safe_file_stem


class CalculiXInpMesher(AbstractMesher):
    """CalculiX 输入网格生成器。

    矩形板路径调用 Gmsh Python API；梁和矩形实体块路径使用确定性结构化网格。

    Args:
        config: 网格器配置。

    Returns:
        CalculiXInpMesher: CalculiX `.inp` 网格器实例。

    Raises:
        OSError: 当工作目录无法创建时抛出。

    Example:
        >>> from mechagent.core.mesher import MeshConfig
        >>> CalculiXInpMesher(MeshConfig())
        <mechagent.core.adapters.calculix_mesh.CalculiXInpMesher object at ...>
    """

    def generate(self, model_params: ModelParams) -> MeshResult:
        """生成标准几何网格。

        Args:
            model_params: 结构化仿真参数。

        Returns:
            MeshResult: 网格生成结果。

        Raises:
            OSError: 当网格文件无法写入时抛出。

        Example:
            >>> mesher.generate(tc02_model_params())
            MeshResult(success=True, ...)
        """

        if model_params.geometry.type is GeometryType.BEAM:
            missing = _missing_dimensions(model_params, ("length",))
            if missing:
                return _missing_dimension_result("CalculiXInpMesher 梁网格路径", missing)
            return self._generate_beam_mesh(model_params)
        if model_params.geometry.type is GeometryType.PLATE:
            missing = _missing_dimensions(model_params, ("length", "width"))
            if missing:
                return _missing_dimension_result("CalculiXInpMesher 板网格路径", missing)
            return self._generate_plate_mesh(model_params)
        if model_params.geometry.type is GeometryType.SOLID:
            missing = _missing_dimensions(model_params, ("length", "width", "height"))
            if missing:
                return _missing_dimension_result("CalculiXInpMesher 实体网格路径", missing)
            return self._generate_solid_mesh(model_params)
        return MeshResult(
            success=False,
            error_message=(
                f"CalculiXInpMesher 不支持几何类型 {model_params.geometry.type.value}。"
            ),
        )

    def _generate_beam_mesh(self, model_params: ModelParams) -> MeshResult:
        case_id = safe_file_stem(model_params.case_id, "beam_mesh")
        dimensions = model_params.geometry.dimensions
        length = dimensions["length"]
        mesh_file = self.config.work_dir / f"{case_id}_mesh.inp"
        element_count = max(1, int(length / self.config.seed_size))
        node_lines = ["*NODE"]
        element_lines = ["*ELEMENT, TYPE=B31, ELSET=EALL"]
        for idx in range(element_count + 1):
            x = length * idx / element_count
            node_lines.append(f"{idx + 1}, {x:.12g}, 0., 0.")
        for idx in range(element_count):
            element_lines.append(f"{idx + 1}, {idx + 1}, {idx + 2}")
        mesh_file.write_text("\n".join([*node_lines, *element_lines, ""]), encoding="utf-8")
        return MeshResult(
            success=True,
            mesh_file=mesh_file,
            quality={"min_jacobian": 1.0, "max_aspect_ratio": 1.0},
            metadata={
                "format": "calculix_mesh_inp",
                "element_count": element_count,
                "node_count": element_count + 1,
                "element_type": "B31",
                "seed_size_mm": self.config.seed_size,
                "source": "structured_line",
            },
        )

    def _generate_solid_mesh(self, model_params: ModelParams) -> MeshResult:
        case_id = safe_file_stem(model_params.case_id, "solid_mesh")
        mesh_file = self.config.work_dir / f"{case_id}_mesh.inp"
        dimensions = model_params.geometry.dimensions
        length = dimensions["length"]
        width = dimensions["width"]
        height = dimensions["height"]
        nodes, hexes = _regular_solid_mesh(length, width, height, self.config.seed_size)
        _write_calculix_c3d8_mesh(mesh_file, nodes, hexes)
        return MeshResult(
            success=True,
            mesh_file=mesh_file,
            quality={"min_jacobian": 1.0},
            metadata={
                "format": "calculix_mesh_inp",
                "element_type": "C3D8R",
                "source": "structured_hex",
                "seed_size_mm": self.config.seed_size,
                "node_count": len(nodes),
                "element_count": len(hexes),
            },
        )

    def _generate_plate_mesh(self, model_params: ModelParams) -> MeshResult:
        case_id = safe_file_stem(model_params.case_id, "plate_mesh")
        mesh_file = self.config.work_dir / f"{case_id}_mesh.inp"
        dimensions = model_params.geometry.dimensions
        length = dimensions["length"]
        width = dimensions["width"]
        nx = max(4, int(round(length / self.config.seed_size)))
        ny = max(4, int(round(width / self.config.seed_size)))
        nodes: dict[int, tuple[float, float, float]] = {}
        quads: list[tuple[int, int, int, int]] = []
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add(case_id)
            p1 = gmsh.model.geo.addPoint(0.0, 0.0, 0.0, self.config.seed_size)
            p2 = gmsh.model.geo.addPoint(length, 0.0, 0.0, self.config.seed_size)
            p3 = gmsh.model.geo.addPoint(length, width, 0.0, self.config.seed_size)
            p4 = gmsh.model.geo.addPoint(0.0, width, 0.0, self.config.seed_size)
            l1 = gmsh.model.geo.addLine(p1, p2)
            l2 = gmsh.model.geo.addLine(p2, p3)
            l3 = gmsh.model.geo.addLine(p3, p4)
            l4 = gmsh.model.geo.addLine(p4, p1)
            loop = gmsh.model.geo.addCurveLoop([l1, l2, l3, l4])
            surface = gmsh.model.geo.addPlaneSurface([loop])
            gmsh.model.geo.mesh.setTransfiniteCurve(l1, nx + 1)
            gmsh.model.geo.mesh.setTransfiniteCurve(l2, ny + 1)
            gmsh.model.geo.mesh.setTransfiniteCurve(l3, nx + 1)
            gmsh.model.geo.mesh.setTransfiniteCurve(l4, ny + 1)
            gmsh.model.geo.mesh.setTransfiniteSurface(surface)
            gmsh.model.geo.mesh.setRecombine(2, surface)
            gmsh.model.geo.synchronize()
            gmsh.model.mesh.generate(2)
            nodes = _gmsh_nodes()
            quads = _gmsh_quad_elements()
            if not nodes or not quads:
                return MeshResult(
                    success=False,
                    error_message="Gmsh 未生成可用于 CalculiX S4 单元的四边形网格。",
                )
            _write_calculix_s4_mesh(mesh_file, nodes, quads)
        finally:
            gmsh.finalize()
        return MeshResult(
            success=True,
            mesh_file=mesh_file,
            quality={"min_jacobian": 1.0},
            metadata={
                "format": "calculix_mesh_inp",
                "element_type": "S4",
                "source": "gmsh",
                "seed_size_mm": self.config.seed_size,
                "node_count": len(nodes),
                "element_count": len(quads),
            },
        )


def _missing_dimensions(model_params: ModelParams, required: tuple[str, ...]) -> list[str]:
    return [name for name in required if name not in model_params.geometry.dimensions]


def _missing_dimension_result(context: str, missing: list[str]) -> MeshResult:
    return MeshResult(
        success=False,
        error_message=f"{context}缺少几何尺寸字段: {', '.join(missing)}。",
    )


def _gmsh_nodes() -> dict[int, tuple[float, float, float]]:
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    nodes: dict[int, tuple[float, float, float]] = {}
    for index, tag in enumerate(node_tags):
        nodes[int(tag)] = (
            float(coords[index * 3]),
            float(coords[index * 3 + 1]),
            float(coords[index * 3 + 2]),
        )
    return nodes


def _gmsh_quad_elements() -> list[tuple[int, int, int, int]]:
    element_types, _, element_node_tags = gmsh.model.mesh.getElements(2)
    quads: list[tuple[int, int, int, int]] = []
    for element_type, node_tags in zip(element_types, element_node_tags):
        if int(element_type) != 3:
            continue
        for index in range(0, len(node_tags), 4):
            quads.append(
                (
                    int(node_tags[index]),
                    int(node_tags[index + 1]),
                    int(node_tags[index + 2]),
                    int(node_tags[index + 3]),
                )
            )
    return quads


def _write_calculix_s4_mesh(
    path: Path,
    nodes: dict[int, tuple[float, float, float]],
    quads: list[tuple[int, int, int, int]],
) -> None:
    sorted_node_tags = sorted(nodes)
    node_id_by_tag = {tag: index + 1 for index, tag in enumerate(sorted_node_tags)}
    lines = ["*NODE"]
    for tag in sorted_node_tags:
        node_id = node_id_by_tag[tag]
        x, y, z = nodes[tag]
        lines.append(f"{node_id}, {x:.12g}, {y:.12g}, {z:.12g}")
    lines.append("*ELEMENT, TYPE=S4, ELSET=EALL")
    for element_id, quad in enumerate(quads, start=1):
        mapped = [str(node_id_by_tag[tag]) for tag in quad]
        lines.append(f"{element_id}, {', '.join(mapped)}")
    path.write_text("\n".join([*lines, ""]), encoding="utf-8")


def _regular_solid_mesh(
    length: float,
    width: float,
    height: float,
    seed_size: float,
) -> tuple[
    dict[int, tuple[float, float, float]], list[tuple[int, int, int, int, int, int, int, int]]
]:
    nx = max(1, int(round(length / seed_size)))
    ny = max(1, int(round(width / seed_size)))
    nz = max(1, int(round(height / seed_size)))

    def node_id(i: int, j: int, k: int) -> int:
        return k * (ny + 1) * (nx + 1) + j * (nx + 1) + i + 1

    nodes: dict[int, tuple[float, float, float]] = {}
    hexes: list[tuple[int, int, int, int, int, int, int, int]] = []
    for k in range(nz + 1):
        z = height * k / nz
        for j in range(ny + 1):
            y = width * j / ny
            for i in range(nx + 1):
                nodes[node_id(i, j, k)] = (length * i / nx, y, z)

    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                hexes.append(
                    (
                        node_id(i, j, k),
                        node_id(i + 1, j, k),
                        node_id(i + 1, j + 1, k),
                        node_id(i, j + 1, k),
                        node_id(i, j, k + 1),
                        node_id(i + 1, j, k + 1),
                        node_id(i + 1, j + 1, k + 1),
                        node_id(i, j + 1, k + 1),
                    )
                )
    return nodes, hexes


def _write_calculix_c3d8_mesh(
    path: Path,
    nodes: dict[int, tuple[float, float, float]],
    hexes: list[tuple[int, int, int, int, int, int, int, int]],
) -> None:
    lines = ["*NODE"]
    for node_id, point in sorted(nodes.items()):
        x, y, z = point
        lines.append(f"{node_id}, {x:.12g}, {y:.12g}, {z:.12g}")
    lines.append("*ELEMENT, TYPE=C3D8R, ELSET=EALL")
    for element_id, element_nodes in enumerate(hexes, start=1):
        lines.append(f"{element_id}, {', '.join(str(node) for node in element_nodes)}")
    path.write_text("\n".join([*lines, ""]), encoding="utf-8")

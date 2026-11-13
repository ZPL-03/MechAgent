"""基于 Gmsh OpenCASCADE 的 CAD 实体直接网格适配器。

该适配器只处理带有可核验 CAD 来源的三维实体。网格由导入的 CAD 形体直接生成，
并将稳定拓扑面/边转换为 CalculiX/Abaqus 可读取的节点集合。无法恢复来源、拓扑
或有效区域集合时显式失败，不回退到包围盒网格。
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

import gmsh

from mechagent.core.mesher import AbstractMesher, MeshResult
from mechagent.core.models import GeometryType, ModelParams

from .gmsh_cad import _topology_digest, _topology_entities


class GmshCADInpMesher(AbstractMesher):
    """将带有 CAD 拓扑摘要的实体直接网格为 CalculiX INP。"""

    def generate(self, model_params: ModelParams) -> MeshResult:
        """生成一阶四面体实体网格和拓扑区域节点集合。"""

        if model_params.geometry.type is not GeometryType.SOLID:
            return MeshResult(
                success=False,
                error_message=(
                    "CAD 直接网格当前只支持三维实体；梁和薄板必须使用对应参数化网格路径。"
                ),
            )
        cad_geometry = model_params.metadata.get("cad_geometry")
        if not isinstance(cad_geometry, dict):
            return MeshResult(success=False, error_message="CAD 直接网格缺少 cad_geometry 元数据。")
        source_value = cad_geometry.get("source_path")
        if not isinstance(source_value, str) or not source_value.strip():
            return MeshResult(success=False, error_message="CAD 直接网格缺少受控 source_path。")
        source = Path(source_value).resolve()
        if not source.is_file():
            return MeshResult(success=False, error_message=f"CAD 源文件不存在: {source}")
        expected_hash = cad_geometry.get("source_sha256")
        if isinstance(expected_hash, str) and expected_hash:
            actual_hash = _sha256_file(source)
            if actual_hash != expected_hash:
                return MeshResult(
                    success=False,
                    error_message="CAD 源文件 SHA-256 与候选摘要不一致，拒绝直接网格。",
                )

        case_id = _safe_stem(model_params.case_id or "cad_solid")
        mesh_file = self.config.work_dir / f"{case_id}_cad_mesh.inp"
        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.MeshSizeMax", self.config.seed_size)
            gmsh.option.setNumber("Mesh.MeshSizeMin", max(self.config.seed_size / 5.0, 1.0e-6))
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.model.add(case_id)
            gmsh.model.occ.importShapes(str(source))
            gmsh.model.occ.healShapes()
            gmsh.model.occ.synchronize()
            volumes = gmsh.model.getEntities(3)
            faces = gmsh.model.getEntities(2)
            if not volumes:
                return MeshResult(success=False, error_message="CAD 直接网格需要至少一个封闭实体。")
            gmsh.model.mesh.generate(3)
            nodes = _gmsh_nodes()
            tetrahedra = _gmsh_tetrahedra()
            if not nodes or not tetrahedra:
                return MeshResult(
                    success=False,
                    error_message="Gmsh 未生成可用的 C3D4 四面体网格。",
                )
            topology = _topology_entities(volumes, faces, gmsh.model.getEntities(1))
            expected_topology_digest = cad_geometry.get("topology_digest")
            actual_topology_digest = _topology_digest(topology)
            if (
                isinstance(expected_topology_digest, str)
                and expected_topology_digest
                and expected_topology_digest != actual_topology_digest
            ):
                return MeshResult(
                    success=False,
                    error_message=(
                        "CAD 拓扑摘要与网格导入结果不一致，拒绝使用可能错位的区域映射。"
                    ),
                    metadata={
                        "expected_topology_digest": expected_topology_digest,
                        "actual_topology_digest": actual_topology_digest,
                    },
                )
            topology_by_id = {item.stable_id: item for item in topology}
            region_sets = _region_node_sets(cad_geometry, topology_by_id)
            required = _required_region_names(model_params)
            missing = sorted(name for name in required if not region_sets.get(name))
            if missing:
                return MeshResult(
                    success=False,
                    error_message="CAD 区域没有映射到网格节点集合: " + ", ".join(missing),
                )
            quality = _quality_metrics(3)
            if quality.get("min_sicn", 0.0) < self.config.min_quality:
                return MeshResult(
                    success=False,
                    quality=quality,
                    error_message=(
                        f"CAD 直接网格最小质量 {quality.get('min_sicn', 0.0):.6g} "
                        f"低于阈值 {self.config.min_quality:.6g}。"
                    ),
                )
            _write_inp(mesh_file, nodes, tetrahedra, region_sets)
            return MeshResult(
                success=True,
                mesh_file=mesh_file,
                quality=quality,
                metadata={
                    "format": "calculix_mesh_inp",
                    "source": "gmsh_occ_cad",
                    "element_type": "C3D4",
                    "direct_cad": True,
                    "source_path": str(source),
                    "source_sha256": expected_hash or _sha256_file(source),
                    "topology_digest": actual_topology_digest,
                    "region_candidates": [
                        item
                        for item in cad_geometry.get("region_candidates", [])
                        if isinstance(item, dict)
                    ],
                    "region_node_sets": {
                        name: sorted(set(values)) for name, values in region_sets.items()
                    },
                    "node_count": len(nodes),
                    "element_count": len(tetrahedra),
                },
            )
        except Exception as exc:
            return MeshResult(success=False, error_message=f"CAD 直接网格失败: {exc}")
        finally:
            gmsh.finalize()


def _gmsh_nodes() -> dict[int, tuple[float, float, float]]:
    tags, coordinates, _ = gmsh.model.mesh.getNodes()
    return {
        int(tag): (
            float(coordinates[index * 3]),
            float(coordinates[index * 3 + 1]),
            float(coordinates[index * 3 + 2]),
        )
        for index, tag in enumerate(tags)
    }


def _gmsh_tetrahedra() -> list[tuple[int, int, int, int]]:
    element_types, _, groups = gmsh.model.mesh.getElements(3)
    result: list[tuple[int, int, int, int]] = []
    for element_type, tags in zip(element_types, groups, strict=False):
        if int(element_type) != 4:
            continue
        for index in range(0, len(tags), 4):
            result.append(tuple(int(tag) for tag in tags[index : index + 4]))  # type: ignore[arg-type]
    return result


def _region_node_sets(
    cad_geometry: dict[str, Any], topology_by_id: dict[str, Any]
) -> dict[str, list[int]]:
    candidates = cad_geometry.get("region_candidates")
    if not isinstance(candidates, list):
        return {}
    result: dict[str, list[int]] = {}
    aliases = {
        "x_min": ("root", "fixed_end", "left_end"),
        "x_max": ("tip", "right_end", "loaded_end", "end_face", "free_end"),
        "z_max": ("top_surface", "top"),
        "z_min": ("bottom_surface", "bottom"),
    }
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("status") != "mapped":
            continue
        topology_ids = candidate.get("topology_ids")
        if not isinstance(topology_ids, list) or not topology_ids:
            continue
        node_ids: set[int] = set()
        for stable_id in topology_ids:
            entity = topology_by_id.get(stable_id)
            if entity is None:
                continue
            node_tags, _, _ = gmsh.model.mesh.getNodes(
                int(entity.dimension), int(entity.native_tag), True
            )
            node_ids.update(int(tag) for tag in node_tags)
        if not node_ids:
            continue
        name = str(candidate.get("name", ""))
        if not name:
            continue
        result[name] = sorted(node_ids)
        for alias in aliases.get(name, ()):
            result[alias] = sorted(node_ids)
    return result


def _required_region_names(model_params: ModelParams) -> set[str]:
    names = {_region_alias(item.region) for item in model_params.loads}
    names.update(_region_alias(item.region) for item in model_params.bcs)
    return names


def _region_alias(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _quality_metrics(dimension: int) -> dict[str, float]:
    _, groups, _ = gmsh.model.mesh.getElements(dimension)
    element_tags = [int(tag) for group in groups for tag in group]
    if not element_tags:
        return {}
    values = [
        float(value)
        for value in gmsh.model.mesh.getElementQualities(element_tags, "minSICN")
        if math.isfinite(float(value))
    ]
    return {"min_sicn": min(values), "mean_sicn": sum(values) / len(values)} if values else {}


def _write_inp(
    path: Path,
    nodes: dict[int, tuple[float, float, float]],
    tetrahedra: list[tuple[int, int, int, int]],
    region_sets: dict[str, list[int]],
) -> None:
    lines = ["*NODE"]
    for node_id, point in sorted(nodes.items()):
        lines.append(f"{node_id}, {point[0]:.12g}, {point[1]:.12g}, {point[2]:.12g}")
    lines.append("*ELEMENT, TYPE=C3D4, ELSET=EALL")
    for element_id, element_nodes in enumerate(tetrahedra, start=1):
        lines.append(f"{element_id}, {', '.join(str(node) for node in element_nodes)}")
    for name, node_ids in sorted(region_sets.items()):
        safe_name = _safe_set_name(name)
        lines.append(f"*NSET, NSET={safe_name}")
        for index in range(0, len(node_ids), 16):
            lines.append(", ".join(str(node) for node in node_ids[index : index + 16]))
    path.write_text("\n".join([*lines, ""]), encoding="utf-8")


def _safe_set_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value).upper() or "REGION"


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", value).strip("._")
    return stem or "cad_solid"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

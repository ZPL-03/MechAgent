"""基于 gmsh OpenCASCADE 后端的 CAD 内核适配器。

使用 gmsh 内置 OpenCASCADE 导入 STEP/IGES/BREP 形体，可选执行几何修复，并归纳包围盒、
体积、表面积与实体/面/边数量等几何摘要。gmsh 为 core 既有依赖，无需额外安装。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal, cast

import gmsh

from mechagent.core.cad import (
    AbstractCADKernel,
    CADGeometrySummary,
    CADTopologyEntity,
    RegionCandidate,
)
from mechagent.core.exceptions import CADError

_FORMAT_BY_SUFFIX = {
    ".step": "step",
    ".stp": "step",
    ".iges": "iges",
    ".igs": "iges",
    ".brep": "brep",
}


class GmshCADKernel(AbstractCADKernel):
    """gmsh OCC CAD 内核。

    Args:
        config: CAD 内核配置。

    Returns:
        GmshCADKernel: gmsh CAD 内核实例。

    Raises:
        OSError: 当工作目录无法创建时抛出。

    Example:
        >>> from mechagent.core.cad import CADConfig
        >>> GmshCADKernel(CADConfig()).import_model(Path("bracket.step")).success
        True
    """

    def load(self, source: Path) -> Any:
        """校验 CAD 文件路径与格式。

        Args:
            source: CAD 文件路径。

        Returns:
            Any: 校验通过的文件路径。

        Raises:
            CADError: 当文件不存在或格式不受支持时抛出。
        """

        if not source.exists():
            msg = f"CAD 文件不存在: {source}"
            raise CADError(msg)
        if source.suffix.lower() not in _FORMAT_BY_SUFFIX:
            msg = f"不支持的 CAD 格式: {source.suffix}；支持 STEP、IGES、BREP。"
            raise CADError(msg)
        return source

    def repair(self, shape: Any) -> Any:
        """传递形体路径；几何修复由 ``summarize`` 按配置在 gmsh 会话内执行。

        Args:
            shape: 形体路径。

        Returns:
            Any: 形体路径。

        Raises:
            CADError: 不抛出。
        """

        return shape

    def summarize(self, shape: Any) -> CADGeometrySummary:
        """在 gmsh OCC 会话内导入形体并归纳几何摘要。

        Args:
            shape: 形体路径。

        Returns:
            CADGeometrySummary: 统一几何摘要。

        Raises:
            CADError: 当 gmsh 导入或几何度量失败时抛出。
        """

        source: Path = shape
        source_format = _FORMAT_BY_SUFFIX.get(source.suffix.lower(), source.suffix.lstrip("."))
        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("mechagent_cad")
            gmsh.model.occ.importShapes(str(source))
            if self.config.healing:
                gmsh.model.occ.healShapes()
            gmsh.model.occ.synchronize()
            bbox = gmsh.model.getBoundingBox(-1, -1)
            solids = gmsh.model.getEntities(3)
            faces = gmsh.model.getEntities(2)
            edges = gmsh.model.getEntities(1)
            volume = sum(gmsh.model.occ.getMass(3, tag) for _dim, tag in solids)
            area = sum(gmsh.model.occ.getMass(2, tag) for _dim, tag in faces)
            topology = _topology_entities(solids, faces, edges)
            region_candidates = _face_region_candidates(topology, bbox)
            topology_digest = hashlib.sha256(
                json.dumps(
                    [entity.model_dump(mode="json") for entity in topology],
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            return CADGeometrySummary(
                source_format=source_format,
                source_sha256=_sha256_file(source),
                topology_digest=topology_digest,
                bbox_min=(bbox[0], bbox[1], bbox[2]),
                bbox_max=(bbox[3], bbox[4], bbox[5]),
                volume=max(float(volume), 0.0),
                surface_area=max(float(area), 0.0),
                solid_count=len(solids),
                face_count=len(faces),
                edge_count=len(edges),
                watertight=_is_watertight(faces),
                topology_entities=topology,
                region_candidates=region_candidates,
            )
        except CADError:
            raise
        except Exception as exc:  # gmsh/OCC 异常归一化为 CADError
            msg = f"gmsh CAD 处理失败: {exc}"
            raise CADError(msg) from exc
        finally:
            gmsh.finalize()


def _topology_entities(
    solids: list[tuple[int, int]],
    faces: list[tuple[int, int]],
    edges: list[tuple[int, int]],
) -> list[CADTopologyEntity]:
    entities: list[CADTopologyEntity] = []
    stable_ids: dict[tuple[int, int], str] = {}
    for dimension, native_entities in ((3, solids), (2, faces), (1, edges)):
        dimension_value = cast(Literal[1, 2, 3], dimension)
        rows: list[tuple[tuple[float, ...], int, float]] = []
        for _dim, tag in native_entities:
            box = gmsh.model.getBoundingBox(dimension_value, tag)
            measure = float(gmsh.model.occ.getMass(dimension_value, tag))
            rows.append((tuple(round(value, 9) for value in box), tag, measure))
        normalized_rows: list[tuple[tuple[float, ...], int, float, str]] = []
        for index, (box, tag, measure) in enumerate(sorted(rows), start=1):
            stable_id = _stable_topology_id(dimension, box, measure, index)
            stable_ids[(dimension, tag)] = stable_id
            normalized_rows.append((box, tag, measure, stable_id))
        for box, tag, measure, stable_id in normalized_rows:
            bbox_min = (box[0], box[1], box[2])
            bbox_max = (box[3], box[4], box[5])
            center = (
                (bbox_min[0] + bbox_max[0]) / 2,
                (bbox_min[1] + bbox_max[1]) / 2,
                (bbox_min[2] + bbox_max[2]) / 2,
            )
            entities.append(
                CADTopologyEntity(
                    stable_id=stable_id,
                    dimension=dimension_value,
                    native_tag=tag,
                    bbox_min=bbox_min,
                    bbox_max=bbox_max,
                    center=center,
                    measure=max(measure, 0.0),
                )
            )
    children_by_id: dict[str, list[str]] = {entity.stable_id: [] for entity in entities}
    for entity in entities:
        if entity.dimension <= 1:
            continue
        boundary = gmsh.model.getBoundary(
            [(entity.dimension, entity.native_tag)], oriented=False, recursive=False
        )
        children_by_id[entity.stable_id] = sorted(
            {
                stable_ids[(int(dimension), abs(int(tag)))]
                for dimension, tag in boundary
                if (int(dimension), abs(int(tag))) in stable_ids
            }
        )
    return [
        entity.model_copy(update={"children": children_by_id[entity.stable_id]})
        for entity in entities
    ]


def _is_watertight(faces: list[tuple[int, int]]) -> bool:
    """判断面边界是否闭合；实体数量本身不能证明形体水密。"""

    if not faces:
        return False
    edge_use: Counter[int] = Counter()
    for _dimension, tag in faces:
        for boundary_dimension, boundary_tag in gmsh.model.getBoundary(
            [(2, tag)], oriented=False, recursive=False
        ):
            if boundary_dimension == 1:
                edge_use[abs(int(boundary_tag))] += 1
    return bool(edge_use) and all(count == 2 for count in edge_use.values())


def _stable_topology_id(dimension: int, box: tuple[float, ...], measure: float, index: int) -> str:
    payload = json.dumps(
        {"dimension": dimension, "bbox": box, "measure": round(measure, 9)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"topology-{dimension}d-{hashlib.sha256(payload).hexdigest()[:16]}-{index:04d}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _face_region_candidates(
    topology: list[CADTopologyEntity], bbox: tuple[float, float, float, float, float, float]
) -> list[RegionCandidate]:
    faces = [entity for entity in topology if entity.dimension == 2]
    if not faces:
        return []
    bounds = ((bbox[0], bbox[3]), (bbox[1], bbox[4]), (bbox[2], bbox[5]))
    candidates: list[RegionCandidate] = []
    for axis, (low, high) in zip(("x", "y", "z"), bounds, strict=True):
        extent = max(high - low, 1.0e-12)
        for side, target in (("min", low), ("max", high)):
            distances = sorted(
                ((abs(entity.center["xyz".index(axis)] - target), entity) for entity in faces),
                key=lambda item: item[0],
            )
            distance, entity = distances[0]
            tied = [
                item
                for item_distance, item in distances
                if abs(item_distance - distance) <= extent * 1.0e-8
            ]
            status: Literal["mapped", "ambiguous", "unresolved"] = (
                "mapped" if len(tied) == 1 and distance <= extent * 1.0e-6 else "ambiguous"
            )
            confidence = max(0.0, 1.0 - distance / extent) if status == "mapped" else 0.0
            center = list(entity.center)
            center["xyz".index(axis)] = target
            center_tuple = (float(center[0]), float(center[1]), float(center[2]))
            candidates.append(
                RegionCandidate(
                    name=f"{axis}_{side}",
                    axis=axis,
                    side=side,
                    center=center_tuple,
                    area=entity.measure,
                    topology_ids=[item.stable_id for item in tied],
                    confidence=confidence,
                    status=status,
                )
            )
    return candidates

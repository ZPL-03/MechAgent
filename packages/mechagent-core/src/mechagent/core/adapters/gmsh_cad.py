"""基于 gmsh OpenCASCADE 后端的 CAD 内核适配器。

使用 gmsh 内置 OpenCASCADE 导入 STEP/IGES/BREP 形体，可选执行几何修复，并归纳包围盒、
体积、表面积与实体/面/边数量等几何摘要。gmsh 为 core 既有依赖，无需额外安装。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gmsh

from mechagent.core.cad import AbstractCADKernel, CADGeometrySummary
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
            return CADGeometrySummary(
                source_format=source_format,
                bbox_min=(bbox[0], bbox[1], bbox[2]),
                bbox_max=(bbox[3], bbox[4], bbox[5]),
                volume=max(float(volume), 0.0),
                surface_area=max(float(area), 0.0),
                solid_count=len(solids),
                face_count=len(faces),
                edge_count=len(edges),
                watertight=len(solids) > 0,
            )
        except CADError:
            raise
        except Exception as exc:  # gmsh/OCC 异常归一化为 CADError
            msg = f"gmsh CAD 处理失败: {exc}"
            raise CADError(msg) from exc
        finally:
            gmsh.finalize()

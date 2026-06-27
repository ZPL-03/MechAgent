"""gmsh OCC CAD 内核测试（使用真实 gmsh 导入 STEP）。"""

from __future__ import annotations

from pathlib import Path

import gmsh
import pytest

from mechagent.core import CADConfig, create_cad_kernel, registered_cad_kernels
from mechagent.core.adapters import GmshCADKernel


def _write_box_step(path: Path, dx: float = 100.0, dy: float = 20.0, dz: float = 20.0) -> None:
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("box")
        gmsh.model.occ.addBox(0, 0, 0, dx, dy, dz)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def test_gmsh_cad_kernel_registered(tmp_path: Path) -> None:
    assert "gmsh-occ" in registered_cad_kernels()
    kernel = create_cad_kernel("gmsh-occ", CADConfig(work_dir=tmp_path))
    assert isinstance(kernel, GmshCADKernel)


def test_gmsh_cad_kernel_imports_step_box(tmp_path: Path) -> None:
    step = tmp_path / "box.step"
    _write_box_step(step, 100.0, 20.0, 20.0)

    result = GmshCADKernel(CADConfig(work_dir=tmp_path)).import_model(step)

    assert result.success is True
    summary = result.summary
    assert summary is not None
    assert summary.source_format == "step"
    assert summary.solid_count == 1
    assert summary.face_count == 6
    assert summary.edge_count == 12
    assert summary.watertight is True
    assert summary.volume == pytest.approx(40000.0, rel=1e-3)
    assert summary.surface_area == pytest.approx(8800.0, rel=1e-3)
    assert summary.bbox_max[0] == pytest.approx(100.0, abs=1e-6)
    assert summary.bbox_max[1] == pytest.approx(20.0, abs=1e-6)


def test_gmsh_cad_kernel_missing_file_returns_failure(tmp_path: Path) -> None:
    result = GmshCADKernel(CADConfig(work_dir=tmp_path)).import_model(tmp_path / "missing.step")
    assert result.success is False
    assert result.summary is None
    assert result.error_message is not None


def test_gmsh_cad_kernel_unsupported_format_returns_failure(tmp_path: Path) -> None:
    bad = tmp_path / "model.txt"
    bad.write_text("not a cad file", encoding="utf-8")

    result = GmshCADKernel(CADConfig(work_dir=tmp_path)).import_model(bad)

    assert result.success is False
    assert result.error_message is not None
    assert "不支持" in result.error_message

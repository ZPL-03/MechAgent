"""GeometryAgent 测试（使用真实 gmsh 导入 STEP）。"""

from __future__ import annotations

from pathlib import Path

import gmsh

from mechagent.config import MechAgentConfig
from mechagent.core.models import GeometryType
from mechagent.orchestrator.agents import GeometryAgent


def _write_box_step(path: Path, dx: float, dy: float, dz: float) -> None:
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("box")
        gmsh.model.occ.addBox(0, 0, 0, dx, dy, dz)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def test_geometry_agent_analyzes_step_into_candidate(tmp_path: Path) -> None:
    step = tmp_path / "beam.step"
    _write_box_step(step, 1000.0, 40.0, 40.0)

    analysis = GeometryAgent(MechAgentConfig(), tmp_path).analyze(step)

    assert analysis.success is True
    assert analysis.kernel == "gmsh-occ"
    assert analysis.summary is not None
    assert analysis.candidate is not None
    assert analysis.candidate.geometry_type is GeometryType.BEAM
    assert len(analysis.candidate.region_candidates) == 6
    assert analysis.candidate.missing_fields == ["material", "loads", "bcs"]


def test_geometry_agent_reports_missing_source(tmp_path: Path) -> None:
    analysis = GeometryAgent(MechAgentConfig(), tmp_path).analyze(tmp_path / "missing.step")

    assert analysis.success is False
    assert analysis.candidate is None
    assert analysis.error_message is not None

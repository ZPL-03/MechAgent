"""CAD 几何到求解链路（CAD 文件 → 几何候选 → 自然语言补全 → 求解）测试。"""

from __future__ import annotations

from pathlib import Path

import gmsh
import pytest

from mechagent.app import MechAgent
from mechagent.config import MechAgentConfig
from mechagent.core.cad import (
    CADGeometrySummary,
    GeometryCandidate,
    geometry_candidate_from_summary,
)
from mechagent.core.models import GeometryType
from mechagent.orchestrator.agents import GeometryAgent
from mechagent.orchestrator.agents.mesh import MeshAgent
from mechagent.orchestrator.static_parser import (
    build_static_request_from_geometry,
    parse_static_model_params_from_geometry,
)


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


def _write_assembly_step(path: Path) -> None:
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("assembly")
        gmsh.model.occ.addBox(0.0, 0.0, 0.0, 40.0, 40.0, 40.0)
        gmsh.model.occ.addBox(60.0, 0.0, 0.0, 40.0, 40.0, 40.0)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def _candidate(bbox_max: tuple[float, float, float]) -> GeometryCandidate:
    return geometry_candidate_from_summary(
        CADGeometrySummary(
            source_format="step",
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=bbox_max,
            volume=1.0,
            surface_area=1.0,
            solid_count=1,
            face_count=6,
            edge_count=12,
        )
    )


def test_bridge_beam_candidate_to_model_params() -> None:
    params = parse_static_model_params_from_geometry(
        _candidate((1000.0, 40.0, 40.0)),
        "材料钢，一端固支，端部向下1000N集中力",
    )
    assert params.case_id == "STATIC-BEAM"
    assert params.geometry.type is GeometryType.BEAM
    assert params.geometry.dimensions["length"] == 1000.0
    assert params.loads[0].type.value == "force"
    assert params.metadata["geometry_source"] == "cad"


def test_bridge_plate_candidate_to_model_params() -> None:
    params = parse_static_model_params_from_geometry(
        _candidate((300.0, 200.0, 5.0)),
        "材料铝，四边简支，承受0.01MPa均布压力",
    )
    assert params.case_id == "STATIC-PLATE"
    assert params.geometry.type is GeometryType.PLATE
    assert params.loads[0].type.value == "pressure"


def test_bridge_solid_candidate_to_model_params() -> None:
    params = parse_static_model_params_from_geometry(
        _candidate((100.0, 80.0, 60.0)),
        "材料钢，左端固定，右端承受10MPa轴向拉伸",
    )
    assert params.case_id == "STATIC-SOLID"
    assert params.geometry.type is GeometryType.SOLID


def test_bridge_requires_completion() -> None:
    with pytest.raises(ValueError):
        build_static_request_from_geometry(_candidate((1000.0, 40.0, 40.0)), "   ")


def test_geometry_agent_to_model_params_from_step(tmp_path: Path) -> None:
    step = tmp_path / "beam.step"
    _write_box_step(step, 1000.0, 40.0, 40.0)

    params = GeometryAgent(MechAgentConfig(), tmp_path).to_model_params(
        step, "材料钢，一端固支，端部向下1000N集中力"
    )

    assert params.case_id == "STATIC-BEAM"
    assert params.geometry.dimensions["length"] == 1000.0
    assert params.metadata["geometry_source"] == "cad"


def test_cad_topology_regions_reach_execution_case(tmp_path: Path) -> None:
    step = tmp_path / "beam.step"
    _write_box_step(step, 1000.0, 40.0, 40.0)

    params = GeometryAgent(MechAgentConfig(), tmp_path).to_model_params(
        step, "材料钢，一端固支，端部向下1000N集中力"
    )
    case = params.to_simulation_case(provenance_confidence=1.0)

    assert case.regions["root"].kind == "topology"
    assert case.regions["root"].stable_id.startswith("topology-")
    assert case.regions["root"].topology_ids
    assert case.regions["tip"].kind == "topology"
    assert case.execution_ready is True


def test_cad_region_without_unique_topology_is_not_executable() -> None:
    params = parse_static_model_params_from_geometry(
        _candidate((1000.0, 40.0, 40.0)),
        "材料钢，一端固支，端部向下1000N集中力",
    )
    case = params.to_simulation_case(provenance_confidence=1.0)

    assert case.regions["root"].kind == "unknown"
    assert case.execution_ready is False
    assert any("未完成拓扑或语义映射" in item for item in case.execution_readiness().blockers)


def test_cad_solid_direct_mesh_preserves_region_node_sets(tmp_path: Path) -> None:
    step = tmp_path / "solid.step"
    _write_box_step(step, 100.0, 40.0, 30.0)

    config = MechAgentConfig()
    params = GeometryAgent(config, tmp_path).to_model_params(
        step, "材料钢，左端固定，右端承受10MPa轴向拉伸"
    )
    output = MeshAgent(config, tmp_path / "mesh").generate_with_trace(params)

    assert output.model_params is not None
    assert output.model_params.mesh.element_type.value == "C3D4"
    assert output.mesh_result.success is True
    assert output.mesh_result.metadata["direct_cad"] is True
    assert output.mesh_result.metadata["region_node_sets"]["root"]
    assert output.mesh_result.metadata["region_node_sets"]["end_face"]
    assert output.mesh_result.mesh_file is not None
    mesh_text = output.mesh_result.mesh_file.read_text(encoding="utf-8")
    assert "*ELEMENT, TYPE=C3D4" in mesh_text
    assert "*NSET, NSET=ROOT" in mesh_text
    assert "*NSET, NSET=END_FACE" in mesh_text


def test_cad_mesh_rejects_topology_digest_drift(tmp_path: Path) -> None:
    step = tmp_path / "solid.step"
    _write_box_step(step, 100.0, 40.0, 30.0)

    config = MechAgentConfig()
    params = GeometryAgent(config, tmp_path).to_model_params(
        step, "材料钢，左端固定，右端承受10MPa轴向拉伸"
    )
    cad_geometry = dict(params.metadata["cad_geometry"])
    cad_geometry["topology_digest"] = "0" * 64
    bad_params = params.model_copy(
        update={"metadata": {**params.metadata, "cad_geometry": cad_geometry}}
    )
    output = MeshAgent(config, tmp_path / "mesh-drift").generate_with_trace(bad_params)

    assert output.mesh_result.success is False
    assert "拓扑摘要" in (output.mesh_result.error_message or "")


def test_cad_mesh_rejects_low_confidence_region_mapping(tmp_path: Path) -> None:
    step = tmp_path / "solid.step"
    _write_box_step(step, 100.0, 40.0, 30.0)

    config = MechAgentConfig()
    params = GeometryAgent(config, tmp_path).to_model_params(
        step, "材料钢，左端固定，右端承受10MPa轴向拉伸"
    )
    cad_geometry = dict(params.metadata["cad_geometry"])
    candidates = [dict(item) for item in cad_geometry["region_candidates"]]
    candidates[0]["confidence"] = 0.79
    cad_geometry["region_candidates"] = candidates
    bad_params = params.model_copy(
        update={"metadata": {**params.metadata, "cad_geometry": cad_geometry}}
    )

    output = MeshAgent(config, tmp_path / "mesh-low-confidence").generate_with_trace(bad_params)

    assert output.mesh_result.success is False
    assert "区域没有映射" in (output.mesh_result.error_message or "")


def test_cad_direct_mesh_rejects_multi_solid_assembly(tmp_path: Path) -> None:
    step = tmp_path / "assembly.step"
    _write_assembly_step(step)

    config = MechAgentConfig()
    params = GeometryAgent(config, tmp_path).to_model_params(
        step, "材料钢，左端固定，右端承受10MPa轴向拉伸"
    )
    output = MeshAgent(config, tmp_path / "mesh-assembly").generate_with_trace(params)

    assert output.mesh_result.success is False
    assert "单个封闭实体" in (output.mesh_result.error_message or "")
    assert output.mesh_result.metadata["solid_count"] == 2


@pytest.mark.real_solver
def test_cad_to_solve_closed_loop(tmp_path: Path) -> None:
    step = tmp_path / "beam.step"
    _write_box_step(step, 1000.0, 40.0, 40.0)

    analysis = GeometryAgent(MechAgentConfig(), tmp_path).analyze(step)
    assert analysis.candidate is not None
    request = build_static_request_from_geometry(
        analysis.candidate, "材料钢，一端固支，端部向下1000N集中力"
    )

    agent = MechAgent.from_config("config/mechagent.yaml")
    agent.config = agent.config.model_copy(
        update={"output": agent.config.output.model_copy(update={"output_dir": tmp_path / "runs"})}
    )
    result = agent.run(request)

    summary = result.summary
    assert summary["success"] is True
    solver_result = summary["tasks"][0]["solver_result"]
    assert solver_result["success"] is True
    assert solver_result["quantity"] == "tip_deflection"
    assert solver_result["predicted"] == pytest.approx(7.45, rel=0.05)

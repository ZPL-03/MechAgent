"""内置适配器测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from mechagent.core.adapters import CalculiXAdapter, CalculiXInpMesher
from mechagent.core.adapters.calculix import _parse_frd_data_line
from mechagent.core.exceptions import SolverError
from mechagent.core.mesher import MeshConfig
from mechagent.core.models import (
    AnalysisSpec,
    AnalysisType,
    BCSpec,
    BCType,
    GeometrySpec,
    GeometryType,
    LoadSpec,
    LoadType,
    MaterialType,
)
from mechagent.core.solver import SolverConfig, SolverResult
from mechagent.core.validation import tc01_model_params, tc02_model_params, tc03_model_params
from mechagent.orchestrator.static_parser import parse_static_model_params


def test_calculix_adapter_reports_missing_executable(tmp_path: Path) -> None:
    adapter = CalculiXAdapter(SolverConfig(solver_path="missing-ccx", work_dir=tmp_path))
    input_file = adapter.generate_input(tc01_model_params())

    result = adapter.solve(input_file)

    assert result.success is False
    assert result.error_message is not None
    assert "未找到 CalculiX" in result.error_message


def test_calculix_adapter_converts_timeout_to_solver_result(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    input_file = tmp_path / "timeout_case.inp"
    input_file.write_text("*HEADING\n", encoding="utf-8")
    adapter = CalculiXAdapter(
        SolverConfig(solver_path=sys.executable, work_dir=tmp_path, timeout=1)
    )

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="ccx", timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = adapter.solve(input_file)

    assert result.success is False
    assert result.error_message is not None
    assert "超时" in result.error_message


def test_calculix_adapter_sets_openmp_thread_count(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    input_file = tmp_path / "thread_case.inp"
    input_file.write_text("*HEADING\n", encoding="utf-8")
    adapter = CalculiXAdapter(
        SolverConfig(solver_path=sys.executable, work_dir=tmp_path, num_cpus=7)
    )
    captured: dict[str, str] = {}

    def fake_run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env")
        assert isinstance(env, dict)
        captured["OMP_NUM_THREADS"] = str(env["OMP_NUM_THREADS"])
        return subprocess.CompletedProcess(args=["ccx"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = adapter.solve(input_file)

    assert result.success is True
    assert captured["OMP_NUM_THREADS"] == "7"


def test_calculix_result_aliases_use_input_node_coordinates(tmp_path: Path) -> None:
    input_file = tmp_path / "result_alias.inp"
    input_file.write_text(
        "\n".join(
            [
                "*NODE",
                "1, 0, 0, 0",
                "2, 100, 0, 0",
                "3, 50, 50, 0",
                "4, 20, 20, 0",
                "*ELEMENT, TYPE=B31, ELSET=EALL",
                "1, 1, 2",
            ]
        ),
        encoding="utf-8",
    )
    frd_file = tmp_path / "result_alias.frd"
    frd_file.write_text(
        "\n".join(
            [
                " -4  DISP        4    1",
                _frd_disp_line(1, 0.0, 0.0, 0.0),
                _frd_disp_line(2, 0.25, -2.0, 0.2),
                _frd_disp_line(3, 0.1, -1.0, -0.5),
                _frd_disp_line(4, 0.4, -10.0, -9.0),
                " -3",
            ]
        ),
        encoding="utf-8",
    )
    adapter = CalculiXAdapter(SolverConfig(work_dir=tmp_path))

    extracted = adapter.extract_results(
        SolverResult(success=True, wall_time=0.0, output_files=[input_file, frd_file])
    )

    assert extracted["max_abs_u2_mm"] == pytest.approx(10.0)
    assert extracted["max_abs_u3_mm"] == pytest.approx(9.0)
    assert extracted["tip_deflection_mm"] == pytest.approx(2.0)
    assert extracted["center_deflection_mm"] == pytest.approx(0.5)
    assert extracted["axial_displacement_mm"] == pytest.approx(0.25)


def test_calculix_frd_data_line_parser_accepts_common_numeric_formats() -> None:
    assert _parse_frd_data_line("         7 1.00000E+00-2.50000E-03 3.0E+01") == (
        7,
        [7.0, 1.0, -0.0025, 30.0],
    )
    assert _parse_frd_data_line("  8+1E+00-2.0e-03+.5E+00") == (
        8,
        [8.0, 1.0, -0.002, 0.5],
    )
    assert _parse_frd_data_line("       6951.46199E-001-3.66143E+0009.06021E-005") == (
        695,
        [695.0, 0.146199, -3.66143, 9.06021e-5],
    )
    assert _parse_frd_data_line("        12 0.0 -4 5.") == (12, [12.0, 0.0, -4.0, 5.0])
    assert _parse_frd_data_line(" no node") is None


def test_calculix_inp_mesher_generates_beam_inp_without_external_process(
    tmp_path: Path,
) -> None:
    mesher = CalculiXInpMesher(MeshConfig(work_dir=tmp_path, seed_size=100.0))

    result = mesher.generate(tc01_model_params())

    assert result.success is True
    assert result.mesh_file is not None
    assert result.mesh_file.exists()
    assert result.metadata["format"] == "calculix_mesh_inp"
    assert result.metadata["source"] == "structured_line"
    assert result.metadata["seed_size_mm"] == 100.0


def test_calculix_inp_mesher_sanitizes_case_id_for_mesh_file(tmp_path: Path) -> None:
    params = tc01_model_params().model_copy(update={"case_id": "../unsafe case"})
    mesher = CalculiXInpMesher(MeshConfig(work_dir=tmp_path, seed_size=100.0))

    result = mesher.generate(params)

    assert result.success is True
    assert result.mesh_file is not None
    assert result.mesh_file.parent == tmp_path
    assert result.mesh_file.name == "unsafe_case_mesh.inp"


def test_calculix_inp_mesher_generates_plate_calculix_mesh(tmp_path: Path) -> None:
    mesher = CalculiXInpMesher(MeshConfig(work_dir=tmp_path, seed_size=20.0))

    result = mesher.generate(tc02_model_params())

    assert result.success is True
    assert result.mesh_file is not None
    assert result.mesh_file.suffix == ".inp"
    assert result.metadata["seed_size_mm"] == 20.0
    text = result.mesh_file.read_text(encoding="utf-8")
    assert "*NODE" in text
    assert "*ELEMENT, TYPE=S4, ELSET=EALL" in text


def test_calculix_inp_mesher_generates_solid_calculix_mesh(tmp_path: Path) -> None:
    mesher = CalculiXInpMesher(MeshConfig(work_dir=tmp_path, seed_size=10.0))

    result = mesher.generate(tc03_model_params())
    missing_height = tc03_model_params().model_copy(
        update={
            "geometry": GeometrySpec(
                type=GeometryType.SOLID,
                dimensions={"length": 200.0, "width": 20.0},
            )
        }
    )
    failed = mesher.generate(missing_height)

    assert result.success is True
    assert result.mesh_file is not None
    assert result.mesh_file.suffix == ".inp"
    assert result.metadata["seed_size_mm"] == 10.0
    text = result.mesh_file.read_text(encoding="utf-8")
    assert "*NODE" in text
    assert "*ELEMENT, TYPE=C3D8R, ELSET=EALL" in text
    assert failed.success is False
    assert failed.error_message is not None
    assert "缺少几何尺寸字段: height" in failed.error_message


def test_calculix_beam_input_distributes_line_load(tmp_path: Path) -> None:
    params = parse_static_model_params(
        "长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，向下1kN/m均布线载荷静力分析"
    )
    adapter = CalculiXAdapter(SolverConfig(work_dir=tmp_path))

    input_file = adapter.generate_input(params)
    text = input_file.read_text(encoding="utf-8")

    assert "MechAgent static beam" in text
    assert _sum_cload_values(text, dof=2) == pytest.approx(-1000.0)


def test_calculix_adapter_sanitizes_case_id_for_input_file(tmp_path: Path) -> None:
    params = tc01_model_params().model_copy(update={"case_id": "../unsafe case"})
    adapter = CalculiXAdapter(SolverConfig(work_dir=tmp_path))

    input_file = adapter.generate_input(params)

    assert input_file.parent == tmp_path
    assert input_file.name == "unsafe_case.inp"


def test_calculix_rejects_oblique_beam_load_for_bending_path(tmp_path: Path) -> None:
    params = tc01_model_params().model_copy(
        update={
            "loads": [
                LoadSpec(
                    type=LoadType.FORCE,
                    magnitude=1000.0,
                    region="tip",
                    direction=(0.0, -1.0, 0.05),
                )
            ]
        }
    )
    missing_dimensions = tc01_model_params().model_copy(
        update={
            "geometry": GeometrySpec(
                type=GeometryType.BEAM,
                dimensions={"length": 1000.0},
            )
        }
    )
    adapter = CalculiXAdapter(SolverConfig(work_dir=tmp_path))

    with pytest.raises(SolverError, match="缺少几何尺寸字段: width, height"):
        adapter.generate_input(missing_dimensions)
    with pytest.raises(SolverError, match="纯全局 Y 向横向载荷"):
        adapter.generate_input(params)


def test_calculix_rejects_unsupported_beam_boundary(tmp_path: Path) -> None:
    params = tc01_model_params().model_copy(
        update={
            "bcs": [
                BCSpec(
                    type=BCType.PINNED,
                    region="root",
                    dofs=["ux", "uy", "uz"],
                    values=[0.0, 0.0, 0.0],
                )
            ]
        }
    )
    adapter = CalculiXAdapter(SolverConfig(work_dir=tmp_path))

    with pytest.raises(SolverError, match="root 固支边界"):
        adapter.generate_input(params)


def test_calculix_rejects_non_isotropic_material_path(tmp_path: Path) -> None:
    base = tc01_model_params()
    params = base.model_copy(
        update={"material": base.material.model_copy(update={"type": MaterialType.ORTHOTROPIC})}
    )
    adapter = CalculiXAdapter(SolverConfig(work_dir=tmp_path))

    with pytest.raises(SolverError, match="各向同性线弹性材料"):
        adapter.generate_input(params)


def test_calculix_rejects_nonlinear_geometry_flag(tmp_path: Path) -> None:
    params = tc01_model_params().model_copy(
        update={"analysis": AnalysisSpec(type=AnalysisType.STATIC, nlgeom=True)}
    )
    adapter = CalculiXAdapter(SolverConfig(work_dir=tmp_path))

    with pytest.raises(SolverError, match="线性静力分析"):
        adapter.generate_input(params)


def test_calculix_plate_pressure_direction_controls_cload_sign(tmp_path: Path) -> None:
    pressure = LoadSpec(
        type=LoadType.PRESSURE,
        magnitude=0.01,
        region="top_surface",
        direction=(0.0, 0.0, 1.0),
    )
    params = tc02_model_params().model_copy(update={"loads": [pressure]})
    adapter = CalculiXAdapter(SolverConfig(work_dir=tmp_path))

    input_file = adapter.generate_input(params)
    text = input_file.read_text(encoding="utf-8")

    assert _sum_cload_values(text, dof=3) == pytest.approx(600.0)


def test_calculix_solid_input_distributes_end_face_pressure(tmp_path: Path) -> None:
    adapter = CalculiXAdapter(SolverConfig(work_dir=tmp_path))

    input_file = adapter.generate_input(tc03_model_params())
    text = input_file.read_text(encoding="utf-8")

    assert "MechAgent static solid" in text
    assert "*SOLID SECTION, ELSET=EALL, MATERIAL=MAT" in text
    assert _sum_cload_values(text, dof=1) == pytest.approx(4000.0)


def test_calculix_rejects_oblique_solid_end_face_load(tmp_path: Path) -> None:
    params = tc03_model_params().model_copy(
        update={
            "loads": [
                LoadSpec(
                    type=LoadType.FORCE,
                    magnitude=1000.0,
                    region="end_face",
                    direction=(1.0, 0.05, 0.0),
                )
            ]
        }
    )
    adapter = CalculiXAdapter(SolverConfig(work_dir=tmp_path))

    with pytest.raises(SolverError, match="纯全局 X 向端面轴向载荷"):
        adapter.generate_input(params)


def _sum_cload_values(text: str, dof: int) -> float:
    active = False
    total = 0.0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.upper().startswith("*CLOAD"):
            active = True
            continue
        if active and line.startswith("*"):
            break
        if not active or not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) == 3 and int(parts[1]) == dof:
            total += float(parts[2])
    return total


def _frd_disp_line(node_id: int, u1: float, u2: float, u3: float) -> str:
    return f" -1{node_id:10d}{u1:12.5E}{u2:12.5E}{u3:12.5E}"

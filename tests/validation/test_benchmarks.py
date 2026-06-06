"""结构力学验证案例测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from mechagent import MechAgent
from mechagent.core import validation as validation_module
from mechagent.core.validation import (
    BenchmarkResult,
    axial_bar_end_displacement,
    cantilever_root_bending_stress,
    cantilever_tip_deflection,
    cantilever_uniform_load_tip_deflection,
    evaluate_validation_case,
    run_core_benchmarks,
    run_tc01,
    run_tc02,
    run_tc03,
    run_tc04,
    run_tc05,
    simply_supported_plate_center_deflection,
    tc01_model_params,
    tc03_model_params,
)


def _solver_path() -> str:
    return MechAgent.from_config("config/mechagent.yaml").config.solver.calculix.path


@pytest.mark.real_solver
def test_tc01_cantilever_static_error_below_one_percent() -> None:
    result = run_tc01(solver_path=_solver_path())

    assert result.case_id == "TC-01"
    assert result.relative_error < 0.01
    assert result.passed


@pytest.mark.real_solver
def test_tc02_plate_bending_error_below_two_percent() -> None:
    result = run_tc02(solver_path=_solver_path())

    assert result.case_id == "TC-02"
    assert result.relative_error < 0.02
    assert result.passed


@pytest.mark.real_solver
def test_tc03_solid_axial_error_below_eight_percent() -> None:
    result = run_tc03(solver_path=_solver_path())

    assert result.case_id == "TC-03"
    assert result.relative_error < 0.08
    assert result.passed


@pytest.mark.real_solver
def test_tc04_cantilever_uniform_load_error_below_two_percent() -> None:
    result = run_tc04(solver_path=_solver_path())

    assert result.case_id == "TC-04"
    assert result.relative_error < 0.02
    assert result.passed


@pytest.mark.real_solver
def test_tc05_solid_axial_force_error_below_eight_percent() -> None:
    result = run_tc05(solver_path=_solver_path())

    assert result.case_id == "TC-05"
    assert result.relative_error < 0.08
    assert result.passed


@pytest.mark.real_solver
def test_core_benchmark_suite_contains_five_real_cases() -> None:
    results = run_core_benchmarks(solver_path=_solver_path())

    assert [result.case_id for result in results] == ["TC-01", "TC-02", "TC-03", "TC-04", "TC-05"]
    assert all(result.passed for result in results)


def test_core_benchmark_suite_forwards_solver_runtime_options(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[tuple[str, Path, int, int]] = []

    def fake_run_case(
        *,
        solver_path: str,
        work_dir: Path,
        num_cpus: int,
        timeout: int,
    ) -> BenchmarkResult:
        captured.append((solver_path, work_dir, num_cpus, timeout))
        return BenchmarkResult(
            case_id=f"TC-{len(captured):02d}",
            description="unit",
            predicted=1.0,
            reference=1.0,
            relative_error=0.0,
            tolerance=0.01,
            quantity="u",
            unit="mm",
            solver="unit",
        )

    for name in ("run_tc01", "run_tc02", "run_tc03", "run_tc04", "run_tc05"):
        monkeypatch.setattr(validation_module, name, fake_run_case)

    run_core_benchmarks(
        solver_path="custom-ccx",
        work_dir=tmp_path,
        num_cpus=7,
        timeout=123,
    )

    assert captured == [
        ("custom-ccx", tmp_path / "TC-01", 7, 123),
        ("custom-ccx", tmp_path / "TC-02", 7, 123),
        ("custom-ccx", tmp_path / "TC-03", 7, 123),
        ("custom-ccx", tmp_path / "TC-04", 7, 123),
        ("custom-ccx", tmp_path / "TC-05", 7, 123),
    ]


def test_solid_validation_prefers_axial_displacement_alias() -> None:
    params = tc03_model_params()
    reference = axial_bar_end_displacement(
        axial_load_n=4000.0,
        length_mm=200.0,
        area_mm2=400.0,
        elastic_modulus_mpa=210000.0,
    )

    result = evaluate_validation_case(
        "TC-03",
        params,
        {
            "success": True,
            "axial_displacement_mm": reference,
            "max_abs_u1_mm": reference * 100.0,
        },
        "unit",
    )

    assert result["predicted"] == pytest.approx(reference)
    assert result["passed"] is True


def test_validation_case_marks_failed_solver_result_as_failed() -> None:
    params = tc01_model_params()
    reference = cantilever_tip_deflection(
        load_n=1000.0,
        length_mm=1000.0,
        elastic_modulus_mpa=210000.0,
        width_mm=20.0,
        height_mm=40.0,
    )

    result = evaluate_validation_case(
        "TC-01",
        params,
        {"success": "failed", "tip_deflection_mm": reference},
        "unit",
    )

    assert result["relative_error"] == pytest.approx(0.0)
    assert result["passed"] is False
    assert result["verification_status"] == "failed"


def test_solid_benchmark_functions_prefer_axial_displacement_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_run_calculix_static(*_args: object, **_kwargs: object) -> dict[str, float]:
        return {"axial_displacement_mm": 0.01, "max_abs_u1_mm": 1.0}

    monkeypatch.setattr(validation_module, "_run_calculix_static", fake_run_calculix_static)

    assert run_tc03(solver_path="unit").predicted == pytest.approx(0.01)
    assert run_tc05(solver_path="unit").predicted == pytest.approx(0.01)


def test_cantilever_tip_deflection_matches_euler_bernoulli_value() -> None:
    value = cantilever_tip_deflection(
        load_n=1000.0,
        length_mm=1000.0,
        elastic_modulus_mpa=210000.0,
        width_mm=20.0,
        height_mm=40.0,
    )

    assert round(value, 6) == 14.880952


def test_cantilever_uniform_load_deflection_matches_euler_bernoulli_value() -> None:
    value = cantilever_uniform_load_tip_deflection(
        line_load_n_per_mm=1.0,
        length_mm=1000.0,
        elastic_modulus_mpa=210000.0,
        width_mm=20.0,
        height_mm=40.0,
    )

    assert round(value, 6) == 5.580357


def test_cantilever_root_stress_matches_euler_bernoulli_value() -> None:
    value = cantilever_root_bending_stress(
        load_n=1000.0,
        length_mm=1000.0,
        width_mm=20.0,
        height_mm=40.0,
    )

    assert round(value, 3) == 187.5


def test_axial_bar_displacement_matches_closed_form_value() -> None:
    value = axial_bar_end_displacement(
        axial_load_n=4000.0,
        length_mm=200.0,
        area_mm2=400.0,
        elastic_modulus_mpa=210000.0,
    )

    assert round(value, 8) == 0.00952381


def test_plate_reference_series_is_stable_at_high_truncation() -> None:
    coarse = simply_supported_plate_center_deflection(
        pressure_mpa=0.01,
        length_mm=300.0,
        width_mm=200.0,
        thickness_mm=5.0,
        elastic_modulus_mpa=70000.0,
        poisson_ratio=0.3,
        terms=51,
    )
    fine = simply_supported_plate_center_deflection(
        pressure_mpa=0.01,
        length_mm=300.0,
        width_mm=200.0,
        thickness_mm=5.0,
        elastic_modulus_mpa=70000.0,
        poisson_ratio=0.3,
        terms=151,
    )

    assert abs(coarse - fine) / fine < 1e-4


def test_plate_reference_accepts_stable_negative_poisson_ratio() -> None:
    value = simply_supported_plate_center_deflection(
        pressure_mpa=0.01,
        length_mm=300.0,
        width_mm=200.0,
        thickness_mm=5.0,
        elastic_modulus_mpa=70000.0,
        poisson_ratio=-0.2,
        terms=31,
    )

    assert value > 0.0

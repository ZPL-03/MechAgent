"""网格收敛契约测试。"""

from __future__ import annotations

import pytest

from mechagent.core.convergence import evaluate_mesh_convergence


def test_mesh_convergence_requires_reference_for_pass() -> None:
    report = evaluate_mesh_convergence(
        case_id="TC-01",
        quantity="tip_deflection",
        unit="mm",
        values=[(40.0, 14.0, 10, 9), (20.0, 14.8, 20, 19), (10.0, 14.9, 40, 39)],
        stabilization_tolerance=0.01,
    )
    assert report.status == "unverified"
    assert report.points[-1].relative_change is not None


def test_mesh_convergence_passes_only_when_change_and_reference_pass() -> None:
    report = evaluate_mesh_convergence(
        case_id="TC-01",
        quantity="tip_deflection",
        unit="mm",
        values=[(40.0, 14.0, 10, 9), (20.0, 14.8, 20, 19), (10.0, 14.88, 40, 39)],
        stabilization_tolerance=0.01,
        reference=14.880952,
        reference_tolerance=0.01,
    )
    assert report.status == "passed"
    assert report.failure_reasons == []


def test_mesh_convergence_rejects_non_decreasing_sizes() -> None:
    with pytest.raises(ValueError, match="严格递减"):
        evaluate_mesh_convergence(
            case_id="TC-01",
            quantity="tip_deflection",
            unit="mm",
            values=[(10.0, 14.0, 10, 9), (20.0, 14.8, 20, 19)],
            stabilization_tolerance=0.01,
            reference=14.88,
            reference_tolerance=0.01,
        )

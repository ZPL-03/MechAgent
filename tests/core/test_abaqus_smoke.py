"""独立 Abaqus 工具检查的参考值与失败门禁。"""

from typing import Any

import pytest
from scripts.run_abaqus_smoke import validate_result


def result() -> dict[str, Any]:
    return {
        "end_ux_mm": 100 / 210000,
        "reference_ux_mm": 100 / 210000,
        "mean_s11_mpa": 1.0,
        "reference_s11_mpa": 1.0,
        "volume_mm3": 10000.0,
        "job_status": "COMPLETED",
        "node_count": 189,
        "element_count": 80,
    }


def test_abaqus_reference_case_passes() -> None:
    assert validate_result(result())["passed"] is True


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("end_ux_mm", 0),
        ("mean_s11_mpa", 1.02),
        ("volume_mm3", 9999),
        ("node_count", 0),
        ("element_count", 0),
        ("job_status", "ABORTED"),
    ],
)
def test_abaqus_invalid_results_fail(key: str, value: Any) -> None:
    assert validate_result({**result(), key: value})["passed"] is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("end_ux_mm", float("nan")),
        ("mean_s11_mpa", float("inf")),
        ("volume_mm3", float("nan")),
        ("reference_ux_mm", 0),
        ("reference_s11_mpa", 2),
    ],
)
def test_abaqus_nonfinite_or_changed_reference_is_rejected(key: str, value: float) -> None:
    with pytest.raises(ValueError):
        validate_result({**result(), key: value})

"""CAD 几何摘要到几何候选的映射测试。"""

from __future__ import annotations

from mechagent.core import CADGeometrySummary, geometry_candidate_from_summary
from mechagent.core.models import GeometryType


def _summary(
    bbox_min: tuple[float, float, float], bbox_max: tuple[float, float, float]
) -> CADGeometrySummary:
    return CADGeometrySummary(
        source_format="step",
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        volume=1.0,
        surface_area=1.0,
        solid_count=1,
        face_count=6,
        edge_count=12,
    )


def test_infers_beam_for_slender_box() -> None:
    candidate = geometry_candidate_from_summary(_summary((0.0, 0.0, 0.0), (1000.0, 40.0, 40.0)))
    assert candidate.geometry_type is GeometryType.BEAM


def test_infers_plate_for_thin_box() -> None:
    candidate = geometry_candidate_from_summary(_summary((0.0, 0.0, 0.0), (300.0, 200.0, 5.0)))
    assert candidate.geometry_type is GeometryType.PLATE


def test_infers_solid_for_blocky_box() -> None:
    candidate = geometry_candidate_from_summary(_summary((0.0, 0.0, 0.0), (100.0, 80.0, 60.0)))
    assert candidate.geometry_type is GeometryType.SOLID


def test_region_candidates_and_missing_fields() -> None:
    candidate = geometry_candidate_from_summary(_summary((0.0, 0.0, 0.0), (100.0, 20.0, 20.0)))

    assert candidate.dimensions == {"length": 100.0, "width": 20.0, "height": 20.0}
    assert candidate.missing_fields == ["material", "loads", "bcs"]
    region_names = {region.name for region in candidate.region_candidates}
    assert region_names == {"x_min", "x_max", "y_min", "y_max", "z_min", "z_max"}

    x_max = next(region for region in candidate.region_candidates if region.name == "x_max")
    assert x_max.axis == "x"
    assert x_max.side == "max"
    assert x_max.center[0] == 100.0
    assert x_max.area == 400.0

"""CAD 产物、几何校验和区域绑定契约测试。"""

from __future__ import annotations

from mechagent.core import (
    CADGeometrySummary,
    CADPartSummary,
    CADTopologyEntity,
    RegionCandidate,
    validate_cad_summary,
)


def _valid_summary() -> CADGeometrySummary:
    edge = CADTopologyEntity(
        stable_id="edge-1",
        dimension=1,
        native_tag=1,
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(0.0, 1.0, 0.0),
        center=(0.0, 0.5, 0.0),
        measure=1.0,
    )
    face = CADTopologyEntity(
        stable_id="face-1",
        dimension=2,
        native_tag=1,
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(0.0, 1.0, 1.0),
        center=(0.0, 0.5, 0.5),
        measure=1.0,
        children=[edge.stable_id],
    )
    solid = CADTopologyEntity(
        stable_id="solid-1",
        dimension=3,
        native_tag=1,
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(10.0, 10.0, 10.0),
        center=(5.0, 5.0, 5.0),
        measure=1000.0,
        children=[face.stable_id],
    )
    return CADGeometrySummary(
        source_format="step",
        source_sha256="a" * 64,
        topology_digest="b" * 64,
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(10.0, 10.0, 10.0),
        volume=1000.0,
        surface_area=600.0,
        solid_count=1,
        face_count=1,
        edge_count=1,
        watertight=True,
        topology_entities=[solid, face, edge],
        parts=[
            CADPartSummary(
                part_id=solid.stable_id,
                bbox_min=solid.bbox_min,
                bbox_max=solid.bbox_max,
                volume=solid.measure,
                surface_area=face.measure,
                face_ids=[face.stable_id],
                edge_ids=[edge.stable_id],
            )
        ],
        region_candidates=[
            RegionCandidate(
                name="root",
                axis="x",
                side="min",
                center=(0.0, 0.5, 0.5),
                area=1.0,
                topology_ids=[face.stable_id],
                part_ids=[solid.stable_id],
                confidence=1.0,
                status="mapped",
            )
        ],
    )


def test_valid_cad_summary_is_execution_ready() -> None:
    validation = validate_cad_summary(_valid_summary())

    assert validation.status == "passed"
    assert validation.execution_ready is True
    assert validation.blockers == []
    assert validation.checks == {
        "bbox": "passed",
        "solid_geometry": "passed",
        "topology": "passed",
        "parts": "passed",
        "source_integrity": "passed",
        "topology_digest": "passed",
        "regions": "passed",
    }


def test_invalid_cad_summary_keeps_blockers_explicit() -> None:
    summary = _valid_summary().model_copy(
        update={
            "watertight": False,
            "region_candidates": [
                _valid_summary()
                .region_candidates[0]
                .model_copy(update={"topology_ids": ["face-missing"]})
            ],
        }
    )

    validation = validate_cad_summary(summary)

    assert validation.status == "failed"
    assert validation.execution_ready is False
    assert any("水密" in blocker for blocker in validation.blockers)
    assert any("未知拓扑实体" in blocker for blocker in validation.blockers)

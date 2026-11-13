"""CAD 直接网格独立性契约测试。"""

from __future__ import annotations

import hashlib

import pytest

from mechagent.core.cad_convergence import (
    CADMeshConvergenceRun,
    evaluate_cad_mesh_convergence,
    region_contract_digest,
)

_SOURCE = hashlib.sha256(b"source").hexdigest()
_TOPOLOGY = hashlib.sha256(b"topology").hexdigest()
_REGIONS = hashlib.sha256(b"regions").hexdigest()


def _run(seed: float, value: float, *, topology: str = _TOPOLOGY) -> CADMeshConvergenceRun:
    return CADMeshConvergenceRun(
        seed_size=seed,
        value=value,
        node_count=10,
        element_count=9,
        quality_metric="min_sicn",
        min_quality=0.45,
        quality_threshold=0.3,
        mesh_sha256=hashlib.sha256(f"mesh-{seed}".encode()).hexdigest(),
        source_sha256=_SOURCE,
        topology_digest=topology,
        region_contract_digest=_REGIONS,
        region_node_counts={"root": 4, "end_face": 4},
        solver_success=True,
    )


def test_cad_convergence_requires_reference_for_pass() -> None:
    report = evaluate_cad_mesh_convergence(
        case_id="CAD-BOX",
        quantity="end_face_mean_ux",
        unit="mm",
        solver="calculix",
        source_sha256=_SOURCE,
        topology_digest=_TOPOLOGY,
        region_contract_digest=_REGIONS,
        runs=[_run(20.0, 0.0045), _run(10.0, 0.0047), _run(5.0, 0.00471)],
        stabilization_tolerance=0.01,
        quality_threshold=0.3,
    )
    assert report.status == "unverified"
    assert report.runs[-1].relative_change is not None


def test_cad_convergence_passes_with_reference_and_quality() -> None:
    report = evaluate_cad_mesh_convergence(
        case_id="CAD-BOX",
        quantity="end_face_mean_ux",
        unit="mm",
        solver="calculix",
        source_sha256=_SOURCE,
        topology_digest=_TOPOLOGY,
        region_contract_digest=_REGIONS,
        runs=[_run(20.0, 0.0045), _run(10.0, 0.0047), _run(5.0, 0.00471)],
        stabilization_tolerance=0.01,
        quality_threshold=0.3,
        reference=0.0047619,
        reference_tolerance=0.03,
    )
    assert report.status == "passed"
    assert report.failure_reasons == []


def test_cad_convergence_rejects_identity_drift() -> None:
    with pytest.raises(ValueError, match="同一源文件、拓扑摘要和区域契约"):
        evaluate_cad_mesh_convergence(
            case_id="CAD-BOX",
            quantity="end_face_mean_ux",
            unit="mm",
            solver="calculix",
            source_sha256=_SOURCE,
            topology_digest=_TOPOLOGY,
            region_contract_digest=_REGIONS,
            runs=[
                _run(20.0, 0.0045),
                _run(10.0, 0.0047, topology=hashlib.sha256(b"drift").hexdigest()),
            ],
            stabilization_tolerance=0.01,
            quality_threshold=0.3,
        )


def test_region_contract_digest_is_order_independent() -> None:
    assert region_contract_digest({"root": {"id": 1}, "end_face": {"id": 2}}) == (
        region_contract_digest({"end_face": {"id": 2}, "root": {"id": 1}})
    )

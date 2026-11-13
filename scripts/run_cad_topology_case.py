"""运行 CAD 拓扑到实体网格、区域集合和 CalculiX 的完整验证案例。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import gmsh

ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT / "packages" / "mechagent-core" / "src",
    ROOT / "packages" / "mechagent" / "src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from mechagent.config import MechAgentConfig  # noqa: E402
from mechagent.core.adapters.calculix import CalculiXAdapter  # noqa: E402
from mechagent.core.adapters.gmsh_cad_mesh import GmshCADInpMesher  # noqa: E402
from mechagent.core.mesher import MeshConfig  # noqa: E402
from mechagent.core.models import ElementType  # noqa: E402
from mechagent.core.solver import SolverConfig  # noqa: E402
from mechagent.evidence import stable_artifact_records  # noqa: E402
from mechagent.orchestrator.agents.geometry import GeometryAgent  # noqa: E402

_HOLE_CENTER = (50.0, 20.0)
_HOLE_RADIUS = 8.0
_SOLID_BOUNDS = (100.0, 40.0, 30.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cad", type=Path, help="输入 STEP/IGES/BREP 文件。")
    parser.add_argument(
        "--generate-box",
        action="store_true",
        help="在输出目录生成确定性的实体 STEP 作为本机验证输入。",
    )
    parser.add_argument(
        "--generate-hole-box",
        action="store_true",
        help="生成带贯穿圆孔的实体 STEP，验证非包围盒拓扑。",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("mechagent_output/cad-topology-evidence")
    )
    parser.add_argument(
        "--calculix",
        required=True,
        help="CalculiX 可执行文件路径或命令名。",
    )
    parser.add_argument(
        "--completion",
        default="材料钢，左端固定，右端承受10MPa轴向拉伸",
        help="材料、载荷和边界补全文本。",
    )
    parser.add_argument(
        "--seed-size",
        type=float,
        default=None,
        help="Gmsh 初始网格尺寸；实体块默认 15 mm，贯穿孔实体默认 8 mm。",
    )
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)
    generators = int(args.generate_box) + int(args.generate_hole_box)
    if args.cad is None and generators != 1:
        parser.error("必须指定 --cad、--generate-box 或 --generate-hole-box 之一。")
    if args.cad is not None and generators:
        parser.error("--cad 不能与生成选项同时指定。")
    seed_size = (
        args.seed_size if args.seed_size is not None else (8.0 if args.generate_hole_box else 15.0)
    )
    if seed_size <= 0:
        parser.error("--seed-size 必须为正数。")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = (
        args.cad.resolve()
        if args.cad is not None
        else args.output_dir / ("hole_box.step" if args.generate_hole_box else "box.step")
    )
    if args.generate_box:
        _write_box_step(source)
    elif args.generate_hole_box:
        _write_hole_box_step(source)
    if not source.is_file():
        parser.error(f"CAD 文件不存在: {source}")

    config = MechAgentConfig()
    geometry = GeometryAgent(config, args.output_dir / "cad-work")
    analysis = geometry.analyze(source)
    manifest: dict[str, object]
    if not analysis.success or analysis.candidate is None:
        manifest = {
            "schema_version": 1,
            "status": "failed",
            "stage": "cad_import",
            "error": analysis.error_message,
            "seed_size": seed_size,
        }
        manifest["artifacts"] = stable_artifact_records(args.output_dir)
        _write_json(args.output_dir / "manifest.json", manifest)
        _print_summary(manifest, args.output_dir / "manifest.json")
        return 1

    try:
        params = geometry.to_model_params(source, args.completion, analysis=analysis)
        params = params.model_copy(
            update={
                "mesh": params.mesh.model_copy(
                    update={"element_type": ElementType.C3D4, "seed_size": seed_size}
                )
            }
        )
        case = params.to_simulation_case(
            raw_request=args.completion,
            parser="cad-import",
            provenance_confidence=1.0,
        )
        mesh_params = case.attach_region_contract(params)
        mesh = GmshCADInpMesher(
            MeshConfig(
                work_dir=args.output_dir / "mesh",
                seed_size=seed_size,
                min_quality=0.3,
            )
        ).generate(mesh_params)
        if not mesh.success or mesh.mesh_file is None:
            raise RuntimeError(mesh.error_message or "CAD 直接网格失败。")
        case = case.model_copy(
            update={
                "model": params.model_copy(update={"mesh_file": mesh.mesh_file}),
            }
        )
        solver = CalculiXAdapter(
            SolverConfig(
                solver_path=args.calculix,
                work_dir=args.output_dir / "solver",
                timeout=args.timeout,
            )
        )
        result = solver.run_case(case)
        passed, checks = _checks(
            analysis,
            case,
            mesh,
            result,
            require_through_hole=args.generate_hole_box,
        )
        manifest = {
            "schema_version": 1,
            "status": "passed" if passed else "failed",
            "source": str(source),
            "source_sha256": _sha256_file(source),
            "seed_size": seed_size,
            "artifact": analysis.artifact.model_dump(mode="json")
            if analysis.artifact is not None
            else None,
            "geometry_validation": analysis.validation.model_dump(mode="json")
            if analysis.validation is not None
            else None,
            "region_bindings": [item.model_dump(mode="json") for item in analysis.region_bindings],
            "candidate": analysis.candidate.model_dump(mode="json"),
            "case": case.model_dump(mode="json"),
            "mesh": {
                "file": str(mesh.mesh_file),
                "sha256": _sha256_file(mesh.mesh_file),
                "quality": mesh.quality,
                "metadata": mesh.metadata,
            },
            "solver": result,
            "checks": checks,
        }
    except Exception as exc:  # noqa: BLE001 - 证据清单必须保留失败原因
        manifest = {"schema_version": 1, "status": "failed", "error": str(exc)}

    manifest["artifacts"] = stable_artifact_records(args.output_dir)
    _write_json(args.output_dir / "manifest.json", manifest)
    _print_summary(manifest, args.output_dir / "manifest.json")
    return 0 if manifest["status"] == "passed" else 1


def _checks(
    analysis: object,
    case: object,
    mesh: object,
    result: dict[str, object],
    *,
    require_through_hole: bool = False,
) -> tuple[bool, dict[str, bool]]:
    candidate = analysis.candidate  # type: ignore[attr-defined]
    regions = case.regions  # type: ignore[attr-defined]
    metadata = mesh.metadata  # type: ignore[attr-defined]
    artifact = analysis.artifact  # type: ignore[attr-defined]
    validation = analysis.validation  # type: ignore[attr-defined]
    fields = result.get("fields")
    checks = {
        "cad_topology_entities": bool(candidate.topology_entities),
        "cad_region_candidates": bool(candidate.region_candidates),
        "cad_artifact": (
            artifact is not None
            and artifact.source_sha256 == candidate.source_sha256
            and artifact.topology_digest == candidate.topology_digest
        ),
        "geometry_validation": (
            validation is not None and validation.status == "passed" and validation.execution_ready
        ),
        "region_bindings": bool(analysis.region_bindings),  # type: ignore[attr-defined]
        "through_hole_topology": (
            _has_generated_through_hole(candidate) if require_through_hole else True
        ),
        "case_root_topology": (
            regions.get("root").kind == "topology" if "root" in regions else False
        ),
        "case_load_topology": (
            regions.get("end_face").kind == "topology" if "end_face" in regions else False
        ),
        "case_region_contract": bool(metadata.get("case_regions")),
        "direct_cad_mesh": bool(metadata.get("direct_cad")),
        "c3d4_mesh": metadata.get("element_type") == "C3D4",
        "root_node_set": bool(metadata.get("region_node_sets", {}).get("root")),
        "load_node_set": bool(metadata.get("region_node_sets", {}).get("end_face")),
        "solver_success": bool(result.get("success")),
        "result_fields": isinstance(fields, dict)
        and all(name in fields for name in ("displacement", "stress", "reaction_force", "energy")),
    }
    return all(checks.values()), checks


def _has_generated_through_hole(candidate: object) -> bool:
    """确认生成案例中的贯穿圆孔面仍作为独立 CAD 面存在。"""

    bbox_min = candidate.bbox_min  # type: ignore[attr-defined]
    bbox_max = candidate.bbox_max  # type: ignore[attr-defined]
    expected_area = 2.0 * math.pi * _HOLE_RADIUS * _SOLID_BOUNDS[2]
    tolerance = 1.0e-5
    for entity in candidate.topology_entities:  # type: ignore[attr-defined]
        if entity.dimension != 2:
            continue
        entity_min = entity.bbox_min
        entity_max = entity.bbox_max
        spans_height = (
            abs(entity_min[2] - bbox_min[2]) <= tolerance
            and abs(entity_max[2] - bbox_max[2]) <= tolerance
        )
        interior_xy = (
            entity_min[0] > bbox_min[0] + 1.0
            and entity_max[0] < bbox_max[0] - 1.0
            and entity_min[1] > bbox_min[1] + 1.0
            and entity_max[1] < bbox_max[1] - 1.0
        )
        if (
            spans_height
            and interior_xy
            and math.isclose(entity.measure, expected_area, rel_tol=1.0e-6, abs_tol=1.0e-4)
        ):
            expected_half_width = _HOLE_RADIUS
            center_x, center_y = _HOLE_CENTER
            if (
                abs((entity_min[0] + entity_max[0]) / 2.0 - center_x) > tolerance
                or abs((entity_min[1] + entity_max[1]) / 2.0 - center_y) > tolerance
                or abs((entity_max[0] - entity_min[0]) / 2.0 - expected_half_width) > tolerance
                or abs((entity_max[1] - entity_min[1]) / 2.0 - expected_half_width) > tolerance
            ):
                continue
            return True
    return False


def _write_box_step(path: Path) -> None:
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("mechagent_cad_case")
        gmsh.model.occ.addBox(0.0, 0.0, 0.0, *_SOLID_BOUNDS)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def _write_hole_box_step(path: Path) -> None:
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("mechagent_cad_hole_case")
        box = gmsh.model.occ.addBox(0.0, 0.0, 0.0, *_SOLID_BOUNDS)
        hole = gmsh.model.occ.addCylinder(
            _HOLE_CENTER[0], _HOLE_CENTER[1], 0.0, 0.0, 0.0, _SOLID_BOUNDS[2], _HOLE_RADIUS
        )
        gmsh.model.occ.cut([(3, box)], [(3, hole)], removeObject=True, removeTool=True)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


def _print_summary(manifest: dict[str, object], manifest_path: Path) -> None:
    """输出可供终端和 CI 读取的短摘要；完整清单保存在 manifest_path。"""

    summary: dict[str, object] = {
        "status": manifest.get("status"),
        "manifest": str(manifest_path),
    }
    checks = manifest.get("checks")
    if isinstance(checks, dict):
        summary["checks"] = checks
    if manifest.get("error"):
        summary["error"] = manifest["error"]
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main())

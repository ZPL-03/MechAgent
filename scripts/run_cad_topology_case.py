"""运行 CAD 拓扑到实体网格、区域集合和 CalculiX 的完整验证案例。"""

from __future__ import annotations

import argparse
import hashlib
import json
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
from mechagent.evidence import artifact_records  # noqa: E402
from mechagent.orchestrator.agents.geometry import GeometryAgent  # noqa: E402


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
    parser.add_argument("--seed-size", type=float, default=15.0)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)
    generators = int(args.generate_box) + int(args.generate_hole_box)
    if args.cad is None and generators != 1:
        parser.error("必须指定 --cad、--generate-box 或 --generate-hole-box 之一。")
    if args.cad is not None and generators:
        parser.error("--cad 不能与生成选项同时指定。")
    if args.seed_size <= 0:
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
        manifest = {"status": "failed", "stage": "cad_import", "error": analysis.error_message}
        manifest["artifacts"] = artifact_records(args.output_dir)
        _write_json(args.output_dir / "manifest.json", manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 1

    try:
        params = geometry.to_model_params(source, args.completion)
        params = params.model_copy(
            update={
                "mesh": params.mesh.model_copy(
                    update={"element_type": ElementType.C3D4, "seed_size": args.seed_size}
                )
            }
        )
        case = params.to_simulation_case(
            raw_request=args.completion,
            parser="cad-import",
            provenance_confidence=1.0,
        )
        mesh = GmshCADInpMesher(
            MeshConfig(
                work_dir=args.output_dir / "mesh",
                seed_size=args.seed_size,
                min_quality=0.3,
            )
        ).generate(params)
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
        passed, checks = _checks(analysis, case, mesh, result)
        manifest = {
            "schema_version": 1,
            "status": "passed" if passed else "failed",
            "source": str(source),
            "source_sha256": _sha256_file(source),
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

    manifest["artifacts"] = artifact_records(args.output_dir)
    _write_json(args.output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return 0 if manifest["status"] == "passed" else 1


def _checks(
    analysis: object, case: object, mesh: object, result: dict[str, object]
) -> tuple[bool, dict[str, bool]]:
    candidate = analysis.candidate  # type: ignore[attr-defined]
    regions = case.regions  # type: ignore[attr-defined]
    metadata = mesh.metadata  # type: ignore[attr-defined]
    fields = result.get("fields")
    checks = {
        "cad_topology_entities": bool(candidate.topology_entities),
        "cad_region_candidates": bool(candidate.region_candidates),
        "case_root_topology": (
            regions.get("root").kind == "topology" if "root" in regions else False
        ),
        "case_load_topology": (
            regions.get("end_face").kind == "topology" if "end_face" in regions else False
        ),
        "direct_cad_mesh": bool(metadata.get("direct_cad")),
        "c3d4_mesh": metadata.get("element_type") == "C3D4",
        "root_node_set": bool(metadata.get("region_node_sets", {}).get("root")),
        "load_node_set": bool(metadata.get("region_node_sets", {}).get("end_face")),
        "solver_success": bool(result.get("success")),
        "result_fields": isinstance(fields, dict)
        and all(name in fields for name in ("displacement", "stress", "reaction_force", "energy")),
    }
    return all(checks.values()), checks


def _write_box_step(path: Path) -> None:
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("mechagent_cad_case")
        gmsh.model.occ.addBox(0.0, 0.0, 0.0, 100.0, 40.0, 30.0)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def _write_hole_box_step(path: Path) -> None:
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("mechagent_cad_hole_case")
        box = gmsh.model.occ.addBox(0.0, 0.0, 0.0, 100.0, 40.0, 30.0)
        hole = gmsh.model.occ.addCylinder(50.0, 20.0, 0.0, 0.0, 0.0, 30.0, 8.0)
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


if __name__ == "__main__":
    raise SystemExit(main())

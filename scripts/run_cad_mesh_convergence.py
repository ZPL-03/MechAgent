"""使用真实 CalculiX 运行 CAD 直接网格的网格独立性案例。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT / "packages" / "mechagent-core" / "src",
    ROOT / "packages" / "mechagent" / "src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from mechagent.config import MechAgentConfig  # noqa: E402
from mechagent.core import (  # noqa: E402
    CADMeshConvergenceRun,
    evaluate_cad_mesh_convergence,
    region_contract_digest,
)
from mechagent.core.adapters.calculix import CalculiXAdapter  # noqa: E402
from mechagent.core.adapters.gmsh_cad_mesh import GmshCADInpMesher  # noqa: E402
from mechagent.core.mesher import MeshConfig  # noqa: E402
from mechagent.core.models import ElementType  # noqa: E402
from mechagent.core.solver import SolverConfig  # noqa: E402
from mechagent.evidence import write_manifest  # noqa: E402
from mechagent.orchestrator.agents.geometry import GeometryAgent  # noqa: E402
from run_cad_topology_case import (  # noqa: E402
    _SOLID_BOUNDS,
    _write_box_step,
    _write_hole_box_step,
)

_DEFAULT_SEEDS = {
    "box": (20.0, 10.0, 5.0),
    "hole-box": (12.0, 8.0, 5.0),
}


class CADMeshRunError(RuntimeError):
    """保留 CAD 收敛执行中已经完成的运行记录。"""

    def __init__(self, message: str, runs: list[CADMeshConvergenceRun], failed_seed: float) -> None:
        super().__init__(message)
        self.runs = runs
        self.failed_seed = failed_seed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cad", type=Path, help="输入 STEP/IGES/BREP 文件。")
    parser.add_argument("--generate-box", action="store_true")
    parser.add_argument("--generate-hole-box", action="store_true")
    parser.add_argument("--case-id")
    parser.add_argument("--calculix", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--completion", default="材料钢，左端固定，右端承受10MPa轴向拉伸")
    parser.add_argument("--seed-size", action="append", type=float)
    parser.add_argument("--stabilization-tolerance", type=float, default=0.01)
    parser.add_argument("--reference", type=float)
    parser.add_argument("--reference-tolerance", type=float)
    parser.add_argument("--quality-threshold", type=float, default=0.3)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)
    args.case_id = args.case_id or ("CAD-HOLE-BOX" if args.generate_hole_box else "CAD-BOX")

    generator_count = int(args.generate_box) + int(args.generate_hole_box)
    if args.cad is None and generator_count != 1:
        parser.error("必须指定 --cad、--generate-box 或 --generate-hole-box 之一。")
    if args.cad is not None and generator_count:
        parser.error("--cad 不能与生成选项同时指定。")
    if args.reference is not None and args.reference_tolerance is None:
        parser.error("--reference 必须同时指定 --reference-tolerance。")
    if args.reference_tolerance is not None and args.reference is None:
        parser.error("--reference-tolerance 必须同时指定 --reference。")
    if args.output_dir.exists():
        parser.error(f"输出目录已存在，拒绝覆盖: {args.output_dir}")
    if args.stabilization_tolerance <= 0:
        parser.error("--stabilization-tolerance 必须为正数。")
    if args.quality_threshold < 0:
        parser.error("--quality-threshold 必须为非负数。")

    geometry_kind = "hole-box" if args.generate_hole_box else "box"
    seeds = tuple(args.seed_size or _DEFAULT_SEEDS[geometry_kind])
    if len(seeds) < 2 or any(seed <= 0 for seed in seeds):
        parser.error("至少需要两个正的 --seed-size。")
    if any(left <= right for left, right in zip(seeds, seeds[1:], strict=False)):
        parser.error("--seed-size 必须按从粗到细严格递减。")
    args.output_dir.mkdir(parents=True)

    source = _source_path(args.cad, args.output_dir, args.generate_box, args.generate_hole_box)
    try:
        analysis, params, contract_digest = _prepare_case(args, source)
        runs = _run_sizes(
            args,
            params=params,
            contract_digest=contract_digest,
            source=source,
            seeds=seeds,
        )
        report = evaluate_cad_mesh_convergence(
            case_id=args.case_id,
            quantity="end_face_mean_ux",
            unit="mm",
            solver="calculix",
            source_sha256=_sha256_file(source),
            topology_digest=analysis.candidate.topology_digest,
            region_contract_digest=contract_digest,
            runs=runs,
            stabilization_tolerance=args.stabilization_tolerance,
            quality_threshold=args.quality_threshold,
            reference=args.reference,
            reference_tolerance=args.reference_tolerance,
        )
        details = {
            **report.model_dump(mode="json"),
            "geometry_kind": geometry_kind,
            "source": str(source),
            "solid_bounds_mm": list(_SOLID_BOUNDS) if geometry_kind == "box" else None,
        }
        _write_json(args.output_dir / "convergence.json", details)
        write_manifest(args.output_dir, status=report.status, details=details)
        _print_summary(details, args.output_dir / "manifest.json")
        return 0 if report.status == "passed" else 1
    except Exception as exc:  # noqa: BLE001 - 保留完整失败证据
        details = {
            "schema_version": 1,
            "status": "failed",
            "case_id": args.case_id,
            "geometry_kind": geometry_kind,
            "source": str(source),
            "error": str(exc),
        }
        if isinstance(exc, CADMeshRunError):
            details["completed_runs"] = [item.model_dump(mode="json") for item in exc.runs]
            details["failed_seed_size"] = exc.failed_seed
        _write_json(args.output_dir / "convergence.json", details)
        write_manifest(args.output_dir, status="failed", details=details)
        _print_summary(details, args.output_dir / "manifest.json")
        return 1


def _source_path(
    cad: Path | None,
    output_dir: Path,
    generate_box: bool,
    generate_hole_box: bool,
) -> Path:
    if cad is not None:
        source = cad.resolve()
    else:
        source = output_dir / ("hole_box.step" if generate_hole_box else "box.step")
        if generate_box:
            _write_box_step(source)
        else:
            _write_hole_box_step(source)
    if not source.is_file():
        raise FileNotFoundError(f"CAD 文件不存在: {source}")
    return source


def _prepare_case(args: argparse.Namespace, source: Path) -> tuple[Any, Any, str]:
    geometry = GeometryAgent(MechAgentConfig(), args.output_dir / "cad-work")
    analysis = geometry.analyze(source)
    if not analysis.success or analysis.candidate is None:
        raise RuntimeError(analysis.error_message or "CAD 几何分析失败。")
    params = geometry.to_model_params(source, args.completion, analysis=analysis)
    params = params.model_copy(
        update={"mesh": params.mesh.model_copy(update={"element_type": ElementType.C3D4})}
    )
    case = params.to_simulation_case(
        raw_request=args.completion,
        parser="cad-import",
        provenance_confidence=1.0,
    )
    params = params.model_copy(update={"case_id": args.case_id})
    case = case.model_copy(update={"case_id": args.case_id, "model": params})
    contract = {
        name: region.model_dump(mode="json") for name, region in sorted(case.regions.items())
    }
    return analysis, params, region_contract_digest(contract)


def _run_sizes(
    args: argparse.Namespace,
    *,
    params: Any,
    contract_digest: str,
    source: Path,
    seeds: tuple[float, ...],
) -> list[CADMeshConvergenceRun]:
    runs: list[CADMeshConvergenceRun] = []
    source_hash = _sha256_file(source)
    for index, seed in enumerate(seeds, start=1):
        run_dir = args.output_dir / f"mesh_{index:02d}_{seed:g}"
        run_dir.mkdir()
        try:
            run_params = params.model_copy(
                update={"mesh": params.mesh.model_copy(update={"seed_size": seed})}
            )
            case = run_params.to_simulation_case(
                raw_request=args.completion,
                parser="cad-import",
                provenance_confidence=1.0,
            )
            mesh_params = case.attach_region_contract(run_params)
            mesh = GmshCADInpMesher(
                MeshConfig(
                    work_dir=run_dir / "mesh",
                    seed_size=seed,
                    min_quality=args.quality_threshold,
                )
            ).generate(mesh_params)
            if not mesh.success or mesh.mesh_file is None:
                raise RuntimeError(mesh.error_message or "CAD 直接网格失败。")
            solve_case = case.model_copy(
                update={
                    "case_id": args.case_id,
                    "model": run_params.model_copy(update={"mesh_file": mesh.mesh_file}),
                }
            )
            result = CalculiXAdapter(
                SolverConfig(
                    solver_path=args.calculix,
                    work_dir=run_dir / "solver",
                    timeout=args.timeout,
                )
            ).run_case(solve_case)
            if not result.get("success"):
                raise RuntimeError(str(result.get("error") or result.get("error_message")))
            value = _end_face_mean_ux(result, mesh.metadata)
            mesh_hash = _sha256_file(mesh.mesh_file)
            run_topology_digest = mesh.metadata.get("topology_digest")
            if not isinstance(run_topology_digest, str) or not run_topology_digest:
                raise ValueError("CAD 网格结果缺少 topology_digest。")
            region_node_sets = mesh.metadata.get("region_node_sets")
            if not isinstance(region_node_sets, dict) or not region_node_sets:
                raise ValueError("CAD 网格结果缺少 region_node_sets。")
            _write_json(run_dir / "result.json", result)
            _write_json(
                run_dir / "run.json",
                {
                    "seed_size": seed,
                    "value": value,
                    "mesh": {
                        "file": str(mesh.mesh_file),
                        "sha256": mesh_hash,
                        "quality": mesh.quality,
                        "metadata": mesh.metadata,
                    },
                    "solver_success": result.get("success"),
                },
            )
            runs.append(
                CADMeshConvergenceRun(
                    seed_size=seed,
                    value=value,
                    node_count=int(mesh.metadata.get("node_count", 0)),
                    element_count=int(mesh.metadata.get("element_count", 0)),
                    quality_metric=str(mesh.metadata.get("quality_metric", "")),
                    min_quality=float(mesh.quality.get("min_sicn", 0.0)),
                    quality_threshold=args.quality_threshold,
                    mesh_sha256=mesh_hash,
                    source_sha256=source_hash,
                    topology_digest=run_topology_digest,
                    region_contract_digest=contract_digest,
                    region_node_counts={
                        name: len(values)
                        for name, values in region_node_sets.items()
                        if isinstance(values, list)
                    },
                    solver_success=bool(result.get("success")),
                )
            )
        except Exception as exc:  # noqa: BLE001 - 保留失败尺寸和已完成运行
            _write_json(run_dir / "failure.json", {"seed_size": seed, "error": str(exc)})
            raise CADMeshRunError(str(exc), runs, seed) from exc
    return runs


def _end_face_mean_ux(result: dict[str, Any], metadata: dict[str, Any]) -> float:
    fields = result.get("fields")
    displacement = fields.get("displacement") if isinstance(fields, dict) else None
    values = displacement.get("values") if isinstance(displacement, dict) else None
    regions = metadata.get("region_node_sets")
    node_ids = regions.get("end_face") if isinstance(regions, dict) else None
    if not isinstance(values, dict) or not isinstance(node_ids, list) or not node_ids:
        raise ValueError("CAD 收敛结果缺少 end_face 位移场或区域节点集合。")
    ux_values: list[float] = []
    for node_id in node_ids:
        vector = values.get(str(node_id))
        if not isinstance(vector, list) or not vector:
            continue
        ux_values.append(float(vector[0]))
    if not ux_values:
        raise ValueError("end_face 区域没有可用的 ux 结果。")
    return sum(ux_values) / len(ux_values)


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


def _print_summary(details: dict[str, Any], manifest: Path) -> None:
    print(
        json.dumps({"status": details.get("status"), "manifest": str(manifest)}, ensure_ascii=False)
    )


if __name__ == "__main__":
    raise SystemExit(main())

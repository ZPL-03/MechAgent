"""在同一个 SimulationCase 上运行选定适配器并生成跨工具比较证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT / "packages" / "mechagent-core" / "src",
    ROOT / "packages" / "mechagent" / "src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from mechagent.core.adapters.abaqus import AbaqusAdapter  # noqa: E402
from mechagent.core.adapters.calculix import CalculiXAdapter  # noqa: E402
from mechagent.core.compare import (  # noqa: E402
    ComparisonTolerance,
    compare_backend_results,
    derive_comparison_fields,
)
from mechagent.core.models import ModelParams, SimulationCase  # noqa: E402
from mechagent.core.solver import SolverConfig  # noqa: E402
from mechagent.core.validation import (  # noqa: E402
    tc01_model_params,
    tc02_model_params,
    tc03_model_params,
    tc04_model_params,
    tc05_model_params,
)
from mechagent.evidence import artifact_records  # noqa: E402

_CASE_BUILDERS: dict[str, Callable[[], ModelParams]] = {
    "TC-01": tc01_model_params,
    "TC-02": tc02_model_params,
    "TC-03": tc03_model_params,
    "TC-04": tc04_model_params,
    "TC-05": tc05_model_params,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-id",
        action="append",
        choices=sorted(_CASE_BUILDERS),
        default=None,
        help="标准案例编号，可重复指定；默认 TC-01。",
    )
    parser.add_argument("--calculix", required=True, help="CalculiX 可执行文件路径或命令名。")
    parser.add_argument("--abaqus", required=True, help="Abaqus launcher 路径或命令名。")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("mechagent_output/backend-comparison")
    )
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--relative", type=float, default=1.0e-2)
    parser.add_argument("--absolute", type=float, default=1.0e-9)
    parser.add_argument(
        "--mapped-relative",
        type=float,
        default=1.0e-1,
        help="统一单元质心场的相对误差阈值；默认 10%%，覆盖节点到质心投影误差。",
    )
    args = parser.parse_args(argv)
    if (
        not math.isfinite(args.relative)
        or not math.isfinite(args.absolute)
        or args.relative < 0.0
        or args.absolute < 0.0
        or not math.isfinite(args.mapped_relative)
        or args.mapped_relative < 0.0
    ):
        parser.error("误差阈值必须是非负数。")

    case_ids = list(dict.fromkeys(args.case_id or ["TC-01"]))
    rows: list[dict[str, object]] = []
    for case_id in case_ids:
        rows.append(
            _run_case(
                case_id,
                calculix=args.calculix,
                abaqus=args.abaqus,
                output_dir=args.output_dir,
                timeout=args.timeout,
                tolerance=ComparisonTolerance(relative=args.relative, absolute=args.absolute),
                mapped_tolerance=ComparisonTolerance(
                    relative=args.mapped_relative, absolute=args.absolute
                ),
            )
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "comparison.json"
    output.write_text(
        json.dumps({"cases": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "status": "passed" if all(row["status"] == "passed" for row in rows) else "failed",
        "case_ids": case_ids,
        "comparison": output.name,
    }
    manifest["artifacts"] = artifact_records(args.output_dir)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(output), "cases": rows}, ensure_ascii=False, indent=2))
    return 0 if all(row["status"] == "passed" for row in rows) else 1


def _run_case(
    case_id: str,
    *,
    calculix: str,
    abaqus: str,
    output_dir: Path,
    timeout: int,
    tolerance: ComparisonTolerance,
    mapped_tolerance: ComparisonTolerance,
) -> dict[str, object]:
    case = SimulationCase.from_model_params(
        _CASE_BUILDERS[case_id](),
        raw_request=f"validation case {case_id}",
        provenance_confidence=1.0,
    )
    case_payload = case.model_dump(mode="json")
    case_digest = hashlib.sha256(
        json.dumps(case_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    case_dir = output_dir / case_id
    left_dir = case_dir / "calculix"
    right_dir = case_dir / "abaqus"
    left_dir.mkdir(parents=True, exist_ok=True)
    right_dir.mkdir(parents=True, exist_ok=True)
    left: dict[str, object]
    right: dict[str, object]
    try:
        left = CalculiXAdapter(
            SolverConfig(solver_path=calculix, work_dir=left_dir, timeout=timeout)
        ).run_case(case)
    except Exception as exc:  # noqa: BLE001 - 命令行证据必须保留后端失败原因
        left = {"success": False, "error": str(exc)}
    try:
        right = AbaqusAdapter(
            SolverConfig(solver_path=abaqus, work_dir=right_dir, timeout=timeout)
        ).run_case(case)
    except Exception as exc:  # noqa: BLE001 - 命令行证据必须保留后端失败原因
        right = {"success": False, "error": str(exc)}
    (left_dir / "result.json").write_text(
        json.dumps(left, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (right_dir / "result.json").write_text(
        json.dumps(right, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if not bool(left.get("success")) or not bool(right.get("success")):
        comparison: dict[str, object] = {
            "status": "failed",
            "error": "至少一个后端执行失败。",
            "left_error": left.get("error") or left.get("error_message"),
            "right_error": right.get("error") or right.get("error_message"),
        }
    else:
        requested_comparison = compare_backend_results(
            left,
            right,
            left_backend="calculix",
            right_backend="abaqus",
            tolerance=tolerance,
        )
        raw_comparison = compare_backend_results(
            left,
            right,
            left_backend="calculix",
            right_backend="abaqus",
            tolerance=tolerance,
            field_source="fields",
        )
        left["comparison_fields"] = derive_comparison_fields(
            left,
            elastic_modulus=case.model.material.E,
            poisson_ratio=case.model.material.nu,
        )
        right["comparison_fields"] = derive_comparison_fields(
            right,
            elastic_modulus=case.model.material.E,
            poisson_ratio=case.model.material.nu,
        )
        (left_dir / "result.json").write_text(
            json.dumps(left, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )
        (right_dir / "result.json").write_text(
            json.dumps(right, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )
        semantic_comparison = compare_backend_results(
            left,
            right,
            left_backend="calculix",
            right_backend="abaqus",
            tolerance=tolerance,
            field_source="comparison_fields",
        )
        mapped_comparison = compare_backend_results(
            left,
            right,
            left_backend="calculix",
            right_backend="abaqus",
            tolerance=mapped_tolerance,
            field_source="mapped_fields",
        )
        comparison = {
            "status": _combined_status(
                requested_comparison.status,
                semantic_comparison.status,
                mapped_comparison.status,
            ),
            "requested_fields": requested_comparison.model_dump(mode="json"),
            "raw_fields": raw_comparison.model_dump(mode="json"),
            "mapped_fields": mapped_comparison.model_dump(mode="json"),
            "comparison_fields": semantic_comparison.model_dump(mode="json"),
        }
    return {
        "case_id": case_id,
        "case_digest": case_digest,
        "case": case_payload,
        "calculix_result": str((left_dir / "result.json").resolve()),
        "abaqus_result": str((right_dir / "result.json").resolve()),
        "comparison": comparison,
        "status": comparison["status"],
    }


def _combined_status(*statuses: str) -> str:
    if "failed" in statuses:
        return "failed"
    if "unverified" in statuses:
        return "unverified"
    return "passed"


if __name__ == "__main__":
    raise SystemExit(main())

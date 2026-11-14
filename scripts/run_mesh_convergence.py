"""使用 CalculiX 真实运行生成网格独立性证据。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT / "packages" / "mechagent-core" / "src",
    ROOT / "packages" / "mechagent" / "src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from mechagent.core.adapters.calculix import CalculiXAdapter  # noqa: E402
from mechagent.core.convergence import evaluate_mesh_convergence  # noqa: E402
from mechagent.core.models import ModelParams, SimulationCase  # noqa: E402
from mechagent.core.solver import SolverConfig  # noqa: E402
from mechagent.core.validation import (  # noqa: E402
    evaluate_validation_case,
    tc01_model_params,
    tc02_model_params,
    tc03_model_params,
    tc04_model_params,
    tc05_model_params,
)
from mechagent.evidence import write_manifest  # noqa: E402

_CASE_BUILDERS: dict[str, Callable[[], ModelParams]] = {
    "TC-01": tc01_model_params,
    "TC-02": tc02_model_params,
    "TC-03": tc03_model_params,
    "TC-04": tc04_model_params,
    "TC-05": tc05_model_params,
}
_DEFAULT_SEEDS: dict[str, tuple[float, ...]] = {
    "TC-01": (40.0, 20.0, 10.0, 5.0),
    "TC-02": (20.0, 10.0, 5.0, 2.5),
    "TC-03": (40.0, 20.0, 10.0, 5.0),
    "TC-04": (40.0, 20.0, 10.0, 5.0),
    "TC-05": (40.0, 20.0, 10.0, 5.0),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", choices=sorted(_CASE_BUILDERS), default="TC-01")
    parser.add_argument("--calculix", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed-size", action="append", type=float)
    parser.add_argument("--stabilization-tolerance", type=float, default=0.01)
    parser.add_argument("--reference-tolerance", type=float)
    args = parser.parse_args(argv)
    seeds = tuple(args.seed_size or _DEFAULT_SEEDS[args.case_id])
    if len(seeds) < 2 or any(seed <= 0 for seed in seeds):
        parser.error("至少需要两个正的 --seed-size。")
    if any(left <= right for left, right in zip(seeds, seeds[1:], strict=False)):
        parser.error("--seed-size 必须按从粗到细严格递减。")
    if args.output_dir.exists():
        parser.error(f"输出目录已存在，拒绝覆盖: {args.output_dir}")
    if args.stabilization_tolerance <= 0:
        parser.error("--stabilization-tolerance 必须为正数。")
    if args.reference_tolerance is not None and args.reference_tolerance < 0:
        parser.error("--reference-tolerance 必须为非负数。")

    args.output_dir.mkdir(parents=True)
    values: list[tuple[float, float, int, int]] = []
    runs: list[dict[str, object]] = []
    for index, seed in enumerate(seeds, start=1):
        base_model = _CASE_BUILDERS[args.case_id]()
        model = base_model.model_copy(
            update={"mesh": base_model.mesh.model_copy(update={"seed_size": seed})}
        )
        case = SimulationCase.from_model_params(
            model, raw_request=f"mesh convergence {args.case_id}", provenance_confidence=1.0
        )
        run_dir = args.output_dir / f"mesh_{index:02d}_{seed:g}"
        run_dir.mkdir()
        try:
            result = CalculiXAdapter(
                SolverConfig(solver_path=args.calculix, work_dir=run_dir, timeout=3600)
            ).run_case(case)
            if not bool(result.get("success")):
                raise RuntimeError(str(result.get("error") or result.get("error_message")))
            evaluated = evaluate_validation_case(args.case_id, model, result, "calculix")
            input_path = _input_path(result, run_dir)
            node_count, element_count = _mesh_counts(input_path)
            value = float(evaluated["predicted"])
            values.append((seed, value, node_count, element_count))
            (run_dir / "result.json").write_text(
                json.dumps(evaluated, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            runs.append(
                {
                    "seed_size": seed,
                    "value": value,
                    "reference": evaluated["reference"],
                    "relative_error": evaluated["relative_error"],
                    "node_count": node_count,
                    "element_count": element_count,
                    "work_dir": run_dir.name,
                    "status": "passed" if evaluated["passed"] else "failed",
                }
            )
        except Exception as exc:  # noqa: BLE001 - 保留真实失败证据
            (run_dir / "failure.json").write_text(
                json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            report = {
                "schema_version": 1,
                "status": "failed",
                "case_id": args.case_id,
                "runs": runs,
                "failed_seed_size": seed,
                "error": str(exc),
            }
            (args.output_dir / "convergence.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            write_manifest(
                args.output_dir,
                status="failed",
                details=report,
                tool_commands={"calculix": args.calculix},
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

    reference = float(cast(float, runs[-1]["reference"]))
    reference_tolerance = (
        args.reference_tolerance
        if args.reference_tolerance is not None
        else _reference_tolerance(args.case_id)
    )
    convergence = evaluate_mesh_convergence(
        case_id=args.case_id,
        quantity=_quantity(args.case_id),
        unit="mm",
        values=values,
        stabilization_tolerance=args.stabilization_tolerance,
        reference=reference,
        reference_tolerance=reference_tolerance,
    )
    report = {
        **convergence.model_dump(mode="json"),
        "solver": "calculix",
        "runs": runs,
        "executable": (
            str(Path(args.calculix).resolve()) if Path(args.calculix).is_file() else args.calculix
        ),
    }
    (args.output_dir / "convergence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_manifest(
        args.output_dir,
        status=convergence.status,
        details=report,
        tool_commands={"calculix": args.calculix},
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if convergence.status == "passed" else 1


def _input_path(result: dict[str, object], run_dir: Path) -> Path:
    output_files = result.get("output_files", [])
    if not isinstance(output_files, (list, tuple)):
        output_files = []
    for value in output_files:
        path = Path(str(value))
        if path.suffix.lower() == ".inp" and path.is_file():
            return path
    candidate = run_dir / f"{run_dir.name}.inp"
    if candidate.is_file():
        return candidate
    files = list(run_dir.glob("*.inp"))
    if len(files) == 1:
        return files[0]
    raise FileNotFoundError("求解结果未保留唯一 .inp 网格输入文件。")


def _mesh_counts(input_path: Path) -> tuple[int, int]:
    lines = input_path.read_text(encoding="utf-8").splitlines()
    section = ""
    nodes = elements = 0
    for line in lines:
        upper = line.strip().upper()
        if upper.startswith("*"):
            section = upper.split(",", 1)[0]
            continue
        if section == "*NODE" and line.strip():
            nodes += 1
        elif section == "*ELEMENT" and line.strip():
            elements += 1
    if nodes < 1 or elements < 1:
        raise ValueError(f"网格计数无效: nodes={nodes}, elements={elements}")
    return nodes, elements


def _quantity(case_id: str) -> str:
    return {
        "TC-01": "tip_deflection",
        "TC-02": "center_deflection",
        "TC-03": "axial_displacement",
        "TC-04": "tip_deflection",
        "TC-05": "axial_displacement",
    }[case_id]


def _reference_tolerance(case_id: str) -> float:
    return {"TC-01": 0.01, "TC-02": 0.02, "TC-03": 0.08, "TC-04": 0.02, "TC-05": 0.08}[case_id]


if __name__ == "__main__":
    raise SystemExit(main())

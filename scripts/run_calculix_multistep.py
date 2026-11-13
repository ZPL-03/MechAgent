"""在本机 CalculiX 上运行双步案例并保存完整结果场证据。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
for source in (
    ROOT / "packages" / "mechagent-core" / "src",
    ROOT / "packages" / "mechagent" / "src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from mechagent.core.adapters.calculix import CalculiXAdapter  # noqa: E402
from mechagent.core.models import SimulationCase  # noqa: E402
from mechagent.core.results import compute_case_digest, compute_physical_case_digest  # noqa: E402
from mechagent.core.solver import SolverConfig  # noqa: E402
from mechagent.evidence import stable_artifact_records  # noqa: E402
from run_abaqus_multistep import (  # noqa: E402
    _case,
    _summary,
    _write_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calculix", required=True, help="CalculiX 可执行文件路径或命令名。")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("mechagent_output/calculix-multistep")
    )
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    case = _case_for_calculix()
    case_digest = compute_case_digest(case)
    physical_case_digest = compute_physical_case_digest(case)
    adapter = CalculiXAdapter(
        SolverConfig(solver_path=args.calculix, work_dir=args.output_dir, timeout=args.timeout)
    )
    try:
        result = adapter.run_case(case)
    except Exception as exc:  # noqa: BLE001 - evidence must retain the adapter failure
        failure = {"success": False, "error": str(exc)}
        _write_json(args.output_dir / "result.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1

    _write_json(args.output_dir / "result.json", result)
    summary = _summary(
        result,
        case_digest,
        physical_case_digest=physical_case_digest,
        case_id="TC-01-multistep-calculix",
        required_history=set(),
        minimum_frames=1,
        minimum_history_count=2,
    )
    summary["artifacts"] = stable_artifact_records(args.output_dir)
    _write_json(args.output_dir / "manifest.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "passed" else 1


def _case_for_calculix() -> SimulationCase:
    case = _case()
    native_locations = {
        "stress_sxx": "node",
        "strain": "node",
        "volume": "element",
        "strain_energy_density": "element",
        "reaction_force": "node",
        "energy": "element",
    }
    fields = [
        field.model_copy(update={"location": native_locations.get(field.name, field.location)})
        for field in case.result_fields
    ]
    return cast(
        SimulationCase,
        case.model_copy(
            update={
                "result_fields": fields,
                "load_steps": [
                    step.model_copy(update={"result_fields": [field.name for field in fields]})
                    for step in case.load_steps
                ],
            },
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())

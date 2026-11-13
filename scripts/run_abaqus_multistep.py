"""在本机 Abaqus/Standard 上运行双步案例并保存完整结果场证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT / "packages" / "mechagent-core" / "src",
    ROOT / "packages" / "mechagent" / "src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from mechagent.core.adapters.abaqus import AbaqusAdapter  # noqa: E402
from mechagent.core.models import LoadStepSpec, ResultFieldSpec, SimulationCase  # noqa: E402
from mechagent.core.solver import SolverConfig  # noqa: E402
from mechagent.core.validation import tc01_model_params  # noqa: E402
from mechagent.evidence import stable_artifact_records  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abaqus", required=True, help="Abaqus launcher 路径或命令名。")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("mechagent_output/abaqus-multistep")
    )
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    case = _case()
    case_payload = case.model_dump(mode="json")
    case_digest = hashlib.sha256(
        json.dumps(case_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    adapter = AbaqusAdapter(
        SolverConfig(solver_path=args.abaqus, work_dir=args.output_dir, timeout=args.timeout)
    )
    try:
        result = adapter.run_case(case)
    except Exception as exc:  # noqa: BLE001 - evidence must retain the adapter failure
        failure = {"success": False, "error": str(exc)}
        _write_json(args.output_dir / "result.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1

    _write_json(args.output_dir / "result.json", result)
    summary = _summary(result, case_digest)
    summary["artifacts"] = stable_artifact_records(args.output_dir)
    _write_json(args.output_dir / "manifest.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "passed" else 1


def _case() -> SimulationCase:
    params = tc01_model_params()
    fields = [
        ResultFieldSpec(
            name="displacement",
            quantity="U",
            location="node",
            invariant="magnitude",
            unit="mm",
        ),
        ResultFieldSpec(
            name="stress_sxx",
            quantity="S",
            location="integration_point",
            component="sxx",
            unit="MPa",
        ),
        ResultFieldSpec(name="strain", quantity="E", location="integration_point"),
        ResultFieldSpec(name="volume", quantity="EVOL", location="element", unit="mm^3"),
        ResultFieldSpec(
            name="strain_energy_density",
            quantity="SENER",
            location="integration_point",
            unit="N/mm^2",
        ),
        ResultFieldSpec(name="reaction_force", quantity="RF", location="node", unit="N"),
        ResultFieldSpec(name="energy", quantity="ENER", location="global", unit="N*mm"),
    ]
    return SimulationCase.from_model_params(params, provenance_confidence=1.0).model_copy(
        update={
            "result_fields": fields,
            "load_steps": [
                LoadStepSpec(
                    step_id="step-1",
                    sequence=1,
                    analysis=params.analysis.type,
                    result_fields=[field.name for field in fields],
                ),
                LoadStepSpec(
                    step_id="step-2",
                    sequence=2,
                    analysis=params.analysis.type,
                    load_scale=0.5,
                    result_fields=[field.name for field in fields],
                ),
            ],
        }
    )


def _summary(
    result: dict[str, object],
    case_digest: str,
    *,
    case_id: str = "TC-01-multistep",
    required_history: set[str] | None = None,
    minimum_frames: int = 2,
    minimum_history_count: int = 4,
) -> dict[str, object]:
    steps = result.get("steps")
    fields = result.get("fields")
    history = result.get("field_history")
    requested = result.get("requested_fields")
    step_results = result.get("step_results")
    step_result_items = step_results if isinstance(step_results, list) else []
    valid_steps = isinstance(steps, list) and len(steps) == 2
    step_rows: list[dict[str, object]] = []
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_fields = step.get("fields")
            frames = step.get("frames")
            frame_items = frames if isinstance(frames, list) else []
            frame_field_counts = [
                _field_counts(frame.get("fields"))
                for frame in frame_items
                if isinstance(frame, dict) and isinstance(frame.get("fields"), dict)
            ]
            step_history = step.get("history")
            history_counts = (
                {
                    str(key): len(value)
                    for key, value in step_history.items()
                    if isinstance(value, list)
                }
                if isinstance(step_history, dict)
                else {}
            )
            step_rows.append(
                {
                    "name": step.get("name"),
                    "frame": step.get("frame"),
                    "frame_count": len(step.get("frames", []))
                    if isinstance(step.get("frames"), list)
                    else 0,
                    "field_counts": _field_counts(step_fields),
                    "frame_field_counts": frame_field_counts,
                    "history_keys": sorted(step.get("history", {}).keys())
                    if isinstance(step.get("history"), dict)
                    else [],
                    "history_counts": history_counts,
                }
            )
    field_counts = _field_counts(fields)
    required = {
        "displacement",
        "stress",
        "strain",
        "volume",
        "strain_energy_density",
        "reaction_force",
        "energy",
    }
    requested_counts = _field_counts(requested)
    requested_names = {
        "displacement",
        "stress_sxx",
        "strain",
        "volume",
        "strain_energy_density",
        "reaction_force",
        "energy",
    }
    step_result_names = [
        sorted(item.get("fields", {}).keys())
        for item in step_result_items
        if isinstance(item, dict) and isinstance(item.get("fields"), dict)
    ]
    selected_fields_complete = (
        isinstance(requested, dict)
        and requested_names.issubset(requested_counts)
        and len(step_result_items) == 2
        and len(step_result_names) == 2
        and all(requested_names.issubset(set(names)) for names in step_result_names)
    )
    step_fields_complete = all(_step_row_complete(row, required) for row in step_rows)
    frame_fields_complete = all(_step_frames_complete(row, required) for row in step_rows)
    history_keys = (
        {"ALLIE", "ALLSE", "ALLWK", "ALLPD"} if required_history is None else required_history
    )
    history_complete = all(_step_history_complete(row, history_keys) for row in step_rows)
    history_count = len(history) if isinstance(history, list) else 0
    nodes = result.get("nodes")
    node_count = len(nodes) if isinstance(nodes, dict) else 0
    passed = (
        bool(result.get("success"))
        and valid_steps
        and isinstance(history, list)
        and history_count >= minimum_history_count
        and step_fields_complete
        and frame_fields_complete
        and history_complete
        and selected_fields_complete
        and node_count > 0
        and required.issubset(field_counts)
        and all(count > 0 for key, count in field_counts.items() if key in required)
        and all(_step_row_has_frames(row, minimum=minimum_frames) for row in step_rows)
    )
    return {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "case_id": case_id,
        "case_digest": case_digest,
        "step_count": len(steps) if isinstance(steps, list) else 0,
        "field_history_count": history_count,
        "node_count": node_count,
        "field_counts": field_counts,
        "requested_field_counts": requested_counts,
        "step_result_fields": step_result_names,
        "required_fields": sorted(required),
        "required_history": sorted(history_keys),
        "steps": step_rows,
        "result_json": "result.json",
        "input": _output_name(result, ".inp"),
        "field_json": Path(str(result.get("field_json", ""))).name
        if result.get("field_json")
        else None,
        "odb": Path(str(result.get("odb", ""))).name if result.get("odb") else None,
    }


def _field_counts(fields: object) -> dict[str, int]:
    if not isinstance(fields, dict):
        return {}
    return {
        str(key): len(value.get("values", {}))
        for key, value in fields.items()
        if isinstance(value, dict) and isinstance(value.get("values"), dict)
    }


def _step_row_complete(row: dict[str, object], required: set[str]) -> bool:
    values = row.get("field_counts")
    if not isinstance(values, dict):
        return False
    aliases = {
        "U": "displacement",
        "S": "stress",
        "E": "strain",
        "EVOL": "volume",
        "SENER": "strain_energy_density",
        "RF": "reaction_force",
        "ENER": "energy",
    }
    normalized = {aliases.get(str(name), str(name)): count for name, count in values.items()}
    return required.issubset(normalized) and all(
        isinstance(normalized.get(name), int) and normalized[name] > 0 for name in required
    )


def _step_frames_complete(row: dict[str, object], required: set[str]) -> bool:
    frames = row.get("frame_field_counts")
    if not isinstance(frames, list) or not frames:
        return False
    return all(
        isinstance(counts, dict) and _step_row_complete({"field_counts": counts}, required)
        for counts in frames
    )


def _step_history_complete(row: dict[str, object], required: set[str]) -> bool:
    counts = row.get("history_counts")
    return isinstance(counts, dict) and all(
        isinstance(counts.get(name), int) and counts[name] > 0 for name in required
    )


def _step_row_has_frames(row: dict[str, object], *, minimum: int) -> bool:
    frame_count = row.get("frame_count")
    return isinstance(frame_count, int) and frame_count >= minimum


def _output_name(result: dict[str, object], suffix: str) -> str | None:
    files = result.get("output_files")
    if not isinstance(files, list):
        return None
    for item in files:
        path = Path(str(item))
        if path.suffix.lower() == suffix:
            return path.name
    return None


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())

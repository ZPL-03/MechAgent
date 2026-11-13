"""运行独立自然语言静力验证案例。"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "packages" / "mechagent-core" / "src"
APP_SRC = ROOT / "packages" / "mechagent" / "src"
for src in (str(ROOT), str(CORE_SRC), str(APP_SRC)):
    if src not in sys.path:
        sys.path.insert(0, src)

from scripts.natural_language_cases import STATIC_LANGUAGE_CASES  # noqa: E402

from mechagent import MechAgent  # noqa: E402
from mechagent.config import OrchestratorSettings, OutputSettings  # noqa: E402
from mechagent.evidence import write_manifest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """执行全部自然语言静力案例。

    Args:
        argv: 命令行参数。

    Returns:
        int: 全部通过返回 0，否则返回 1。

    Raises:
        RuntimeError: 当求解流程异常失败时抛出。

    Example:
        >>> isinstance(main(), int)
        True
    """

    parser = ArgumentParser(description="运行独立自然语言静力验证案例。")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/mechagent.yaml"),
        help="配置文件路径。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="案例输出目录，默认使用配置输出目录下的 natural_language_cases。",
    )
    args = parser.parse_args(argv)

    base_config = MechAgent.from_config(args.config).config
    output_dir = args.output_dir or base_config.output.output_dir / "natural_language_cases"
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error(f"输出目录必须为空: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    config = base_config.model_copy(
        update={
            "orchestrator": OrchestratorSettings(mode="dag", use_llm_agents=False),
            "output": OutputSettings(output_dir=output_dir),
        }
    )
    agent = MechAgent(config)
    rows: list[dict[str, Any]] = []
    for case in STATIC_LANGUAGE_CASES:
        try:
            rows.append(_evaluate_case(case, agent.run(case.request)))
        except Exception as exc:  # noqa: BLE001 - 保留每个案例的根因并继续验证其余案例
            rows.append(
                {
                    "case_id": case.case_id,
                    "expected_model_case_id": case.model_case_id,
                    "actual_model_case_id": "",
                    "expected_geometry_type": case.geometry_type,
                    "actual_geometry_type": "",
                    "expected_load_type": case.load_type,
                    "actual_load_type": "",
                    "parsed_ok": False,
                    "quantity": None,
                    "predicted": None,
                    "reference": None,
                    "relative_error": None,
                    "tolerance": None,
                    "solver_success": False,
                    "verification_status": "failed",
                    "reference_checked": False,
                    "reference_passed": False,
                    "passed": False,
                    "report_path": None,
                    "error": str(exc),
                }
            )
    status = "passed" if all(bool(row["passed"]) for row in rows) else "failed"
    results_path = output_dir / "results.json"
    results_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = write_manifest(
        output_dir,
        status=status,
        details={
            "case_count": len(rows),
            "passed_count": sum(bool(row["passed"]) for row in rows),
            "results_path": results_path.name,
        },
    )
    print(
        json.dumps(
            {"status": status, "results": rows, "manifest": str(manifest)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "passed" else 1


def _evaluate_case(case: Any, result: Any) -> dict[str, Any]:
    task = result.summary["tasks"][0]
    model_params = task.get("model_params") or {}
    geometry = model_params.get("geometry") or {}
    loads = model_params.get("loads") or []
    actual_model_case_id = str(model_params.get("case_id", ""))
    actual_geometry_type = str(geometry.get("type", ""))
    actual_load_type = str(loads[0].get("type", "")) if loads else ""
    solver_result = task["solver_result"]
    parsed_ok = (
        actual_model_case_id == case.model_case_id
        and actual_geometry_type == case.geometry_type
        and actual_load_type == case.load_type
    )
    solver_success = bool(solver_result.get("success", solver_result.get("passed", False)))
    reference = solver_result.get("reference")
    verification_status = str(solver_result.get("verification_status", "unverified"))
    reference_checked = reference is not None or verification_status == "passed"
    reference_passed = bool(solver_result.get("passed", False)) if reference_checked else None
    case_passed = parsed_ok and solver_success
    if reference_checked:
        case_passed = case_passed and bool(reference_passed)
    return {
        "case_id": case.case_id,
        "expected_model_case_id": case.model_case_id,
        "actual_model_case_id": actual_model_case_id,
        "expected_geometry_type": case.geometry_type,
        "actual_geometry_type": actual_geometry_type,
        "expected_load_type": case.load_type,
        "actual_load_type": actual_load_type,
        "parsed_ok": parsed_ok,
        "quantity": solver_result.get("quantity"),
        "predicted": solver_result.get("predicted"),
        "reference": reference,
        "relative_error": solver_result.get("relative_error"),
        "tolerance": solver_result.get("tolerance"),
        "solver_success": solver_success,
        "verification_status": verification_status,
        "reference_checked": reference_checked,
        "reference_passed": reference_passed,
        "passed": case_passed,
        "report_path": result.summary.get("report_path"),
    }


if __name__ == "__main__":
    raise SystemExit(main())

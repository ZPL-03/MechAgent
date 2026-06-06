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
    config = base_config.model_copy(
        update={
            "orchestrator": OrchestratorSettings(mode="dag", use_llm_agents=False),
            "output": OutputSettings(output_dir=output_dir),
        }
    )
    agent = MechAgent(config)
    rows: list[dict[str, Any]] = []
    for case in STATIC_LANGUAGE_CASES:
        result = agent.run(case.request)
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
        solver_passed = bool(solver_result.get("passed", False))
        rows.append(
            {
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
                "reference": solver_result.get("reference"),
                "relative_error": solver_result.get("relative_error"),
                "tolerance": solver_result.get("tolerance"),
                "solver_passed": solver_passed,
                "passed": parsed_ok and solver_passed,
                "report_path": result.summary.get("report_path"),
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0 if all(bool(row["passed"]) for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

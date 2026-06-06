"""运行远端 LLM Agent 端到端 smoke 验证。"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "packages" / "mechagent-core" / "src"
APP_SRC = ROOT / "packages" / "mechagent" / "src"
for src in (str(ROOT), str(CORE_SRC), str(APP_SRC)):
    if src not in sys.path:
        sys.path.insert(0, src)

from mechagent import MechAgent  # noqa: E402

DEFAULT_REQUEST = (
    "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力的静力响应"
)
TASK_TRACE_KEYS = ("planner_llm_trace", "designer_llm_trace", "mesh_llm_trace")
SOLVER_TRACE_KEY = "solver_llm_trace"
POST_TRACE_KEYS = ("postproc_llm_trace", "analyst_llm_trace")


def main(argv: Sequence[str] | None = None) -> int:
    """执行一次真实 LLM Agent 闭环并校验公开摘要。"""

    args = _parse_args(argv)
    base_config = MechAgent.from_config(args.config).config
    output_dir = args.output_dir or base_config.output.output_dir / "llm_smoke"
    active_config = base_config.model_copy(
        update={
            "orchestrator": base_config.orchestrator.model_copy(update={"use_llm_agents": True}),
            "output": base_config.output.model_copy(update={"output_dir": output_dir}),
        },
        deep=True,
    )
    result = MechAgent(active_config).run(args.request, use_llm_agents=True)
    smoke = evaluate_llm_smoke_summary(result.summary)
    print(json.dumps(smoke, ensure_ascii=False, indent=2))
    return 0 if smoke["passed"] else 1


def evaluate_llm_smoke_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """校验 SDK 公开摘要中的 LLM trace 与求解验收状态。"""

    checks: list[dict[str, Any]] = []
    tasks = _list_value(summary.get("tasks"))
    report_path = _optional_path(summary.get("report_path"))
    _append_check(checks, "workflow_success", summary.get("success") is True)
    _append_check(checks, "has_task", bool(tasks))
    _append_check(checks, "report_path", report_path is not None and report_path.exists())
    _append_check(checks, "reporter_trace", _trace_ok(summary.get("reporter_llm_trace")))

    task_rows: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        task_id = str(_dict_value(task).get("task_id") or f"TASK_{index}")
        task_checks = _evaluate_task(task_id, _dict_value(task))
        checks.extend(task_checks)
        task_rows.append(_task_public_row(task_id, _dict_value(task)))

    passed = all(bool(item["passed"]) for item in checks)
    return {
        "passed": passed,
        "check_count": len(checks),
        "checks": checks,
        "tasks": task_rows,
        "report_path": summary.get("report_path"),
        "work_dir": summary.get("work_dir"),
    }


def _parse_args(argv: Sequence[str] | None) -> Namespace:
    parser = ArgumentParser(description="运行远端 LLM Agent 端到端 smoke 验证。")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/mechagent.yaml"),
        help="配置文件路径。",
    )
    parser.add_argument(
        "--request",
        default=DEFAULT_REQUEST,
        help="自然语言仿真请求。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="smoke 运行输出目录，默认使用配置输出目录下的 llm_smoke。",
    )
    return parser.parse_args(argv)


def _evaluate_task(task_id: str, task: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    model_params = _dict_value(task.get("model_params"))
    solver = _dict_value(task.get("solver_result"))
    post = _dict_value(task.get("post_summary"))

    _append_check(checks, f"{task_id}.model_params", bool(model_params))
    _append_check(checks, f"{task_id}.solver_success", solver.get("success") is True)
    _append_check(checks, f"{task_id}.solver_passed", solver.get("passed") is True)
    _append_check(
        checks, f"{task_id}.solver_verified", solver.get("verification_status") == "passed"
    )

    for key in TASK_TRACE_KEYS:
        _append_check(checks, f"{task_id}.{key}", _trace_ok(task.get(key)))
    _append_check(checks, f"{task_id}.{SOLVER_TRACE_KEY}", _trace_ok(solver.get(SOLVER_TRACE_KEY)))
    for key in POST_TRACE_KEYS:
        _append_check(checks, f"{task_id}.{key}", _trace_ok(post.get(key)))
    return checks


def _task_public_row(task_id: str, task: dict[str, Any]) -> dict[str, Any]:
    model_params = _dict_value(task.get("model_params"))
    solver = _dict_value(task.get("solver_result"))
    return {
        "task_id": task_id,
        "capability_id": task.get("capability_id"),
        "model_case_id": model_params.get("case_id"),
        "solver_success": solver.get("success"),
        "solver_passed": solver.get("passed"),
        "quantity": solver.get("quantity"),
        "relative_error": solver.get("relative_error"),
    }


def _trace_ok(value: Any) -> bool:
    trace = _dict_value(value)
    return (
        trace.get("used") is True
        and trace.get("error") in (None, "")
        and _positive_int(trace.get("prompt_chars"))
        and _positive_int(trace.get("response_chars"))
    )


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and value > 0


def _optional_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def _append_check(checks: list[dict[str, Any]], name: str, passed: bool) -> None:
    checks.append({"name": name, "passed": bool(passed)})


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())

"""运行 MechAgent 标准验证算例。"""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "packages" / "mechagent-core" / "src"
APP_SRC = ROOT / "packages" / "mechagent" / "src"
for src in (str(CORE_SRC), str(APP_SRC)):
    if src not in sys.path:
        sys.path.insert(0, src)

from mechagent import MechAgent  # noqa: E402
from mechagent.core.validation import run_core_benchmarks  # noqa: E402
from mechagent.evidence import write_manifest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """运行核心标准验证算例。

    Args:
        argv: 命令行参数。

    Returns:
        int: 全部通过返回 0，否则返回 1。

    Raises:
        OSError: 当输出目录无法创建或结果文件无法写入时抛出。

    Example:
        >>> isinstance(main(), int)
        True
    """

    parser = ArgumentParser(description="运行 MechAgent 标准验证算例。")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/mechagent.yaml"),
        help="配置文件路径。",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="求解中间产物目录；未指定时使用系统临时目录。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="独立验证证据目录；必须是新的空目录。未指定时保持旧的配置输出路径。",
    )
    args = parser.parse_args(argv)
    agent = MechAgent.from_config(args.config)
    calculix = agent.config.solver.calculix
    evidence_dir = args.output_dir
    if evidence_dir is not None:
        if evidence_dir.exists() and any(evidence_dir.iterdir()):
            parser.error(f"证据目录必须为空: {evidence_dir}")
        evidence_dir.mkdir(parents=True, exist_ok=True)
    try:
        results = run_core_benchmarks(
            solver_path=calculix.path,
            work_dir=args.work_dir,
            num_cpus=calculix.num_cpus,
            timeout=calculix.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - 证据模式保留执行根因
        if evidence_dir is None:
            raise
        manifest = write_manifest(
            evidence_dir,
            status="failed",
            details={"error": str(exc)},
            config_paths={"config": args.config},
            tool_commands={"calculix": calculix.path},
        )
        print(json.dumps({"status": "failed", "manifest": str(manifest)}, ensure_ascii=False))
        return 1
    rows: list[dict[str, Any]] = [
        {
            "case_id": item.case_id,
            "description": item.description,
            "quantity": item.quantity,
            "unit": item.unit,
            "solver": item.solver,
            "predicted": item.predicted,
            "reference": item.reference,
            "relative_error": item.relative_error,
            "tolerance": item.tolerance,
            "passed": item.passed,
        }
        for item in results
    ]
    for row, item in zip(rows, results, strict=True):
        if item.equilibrium is not None:
            row["equilibrium"] = item.equilibrium.model_dump(mode="json")
    output_dir = evidence_dir or agent.config.output.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "benchmark_results.json"
    output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status = (
        "passed"
        if all(
            item.passed and (item.equilibrium is None or item.equilibrium.status == "passed")
            for item in results
        )
        else "failed"
    )
    if evidence_dir is None:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        manifest = write_manifest(
            evidence_dir,
            status=status,
            details={
                "case_count": len(rows),
                "passed_count": sum(item.passed for item in results),
                "equilibrium_status_counts": {
                    status: sum(
                        item.equilibrium is not None and item.equilibrium.status == status
                        for item in results
                    )
                    for status in ("passed", "failed", "unverified")
                },
                "results_path": output_path.name,
            },
            config_paths={"config": args.config},
            tool_commands={"calculix": calculix.path},
        )
        print(
            json.dumps(
                {"status": status, "results": rows, "manifest": str(manifest)},
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

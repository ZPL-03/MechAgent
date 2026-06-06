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
    args = parser.parse_args(argv)
    agent = MechAgent.from_config(args.config)
    calculix = agent.config.solver.calculix
    results = run_core_benchmarks(
        solver_path=calculix.path,
        num_cpus=calculix.num_cpus,
        timeout=calculix.timeout,
    )
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
    output_dir = agent.config.output.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "benchmark_results.json"
    output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0 if all(item.passed for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

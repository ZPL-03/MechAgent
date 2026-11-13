"""比较两个求解器结果 JSON 的请求场量。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal, cast

from mechagent.core.compare import (
    BackendComparison,
    BackendStepComparison,
    ComparisonTolerance,
    compare_backend_results,
    compare_backend_step_fields,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--left-backend", required=True)
    parser.add_argument("--right-backend", required=True)
    parser.add_argument("--relative", type=float, default=1.0e-3)
    parser.add_argument("--absolute", type=float, default=1.0e-9)
    parser.add_argument(
        "--field-source",
        choices=("requested_fields", "fields", "mapped_fields", "comparison_fields"),
        default="requested_fields",
        help="比较案例选择字段、后端原始场或统一语义字段。",
    )
    parser.add_argument(
        "--steps",
        action="store_true",
        help="按分析步和输出帧比较逐步结果；需要结果包含 step_results 或 mapped_step_fields。",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    left = json.loads(args.left.read_text(encoding="utf-8"))
    right = json.loads(args.right.read_text(encoding="utf-8"))
    field_source = cast(
        Literal["requested_fields", "fields", "mapped_fields", "comparison_fields"],
        args.field_source,
    )
    tolerance = ComparisonTolerance(relative=args.relative, absolute=args.absolute)
    comparison: BackendComparison | BackendStepComparison
    if args.steps:
        comparison = compare_backend_step_fields(
            left,
            right,
            left_backend=args.left_backend,
            right_backend=args.right_backend,
            tolerance=tolerance,
            field_source=field_source,
        )
    else:
        comparison = compare_backend_results(
            left,
            right,
            left_backend=args.left_backend,
            right_backend=args.right_backend,
            tolerance=tolerance,
            field_source=field_source,
        )
    content = json.dumps(comparison.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0 if comparison.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

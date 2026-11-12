"""比较两个求解器结果 JSON 的请求场量。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mechagent.core.compare import ComparisonTolerance, compare_backend_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--left-backend", required=True)
    parser.add_argument("--right-backend", required=True)
    parser.add_argument("--relative", type=float, default=1.0e-3)
    parser.add_argument("--absolute", type=float, default=1.0e-9)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    left = json.loads(args.left.read_text(encoding="utf-8"))
    right = json.loads(args.right.read_text(encoding="utf-8"))
    comparison = compare_backend_results(
        left,
        right,
        left_backend=args.left_backend,
        right_backend=args.right_backend,
        tolerance=ComparisonTolerance(relative=args.relative, absolute=args.absolute),
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

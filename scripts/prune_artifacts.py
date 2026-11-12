"""按作业引用和保留时间清理结果对象。"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from mechagent.runtime.artifacts import create_artifact_store
from mechagent.runtime.store import JobStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--older-than-days", type=float, required=True)
    parser.add_argument("--backend", choices=("filesystem", "s3"), default="filesystem")
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--bucket", default="")
    parser.add_argument("--prefix", default="mechagent")
    parser.add_argument("--apply", action="store_true", help="确认删除候选对象")
    args = parser.parse_args(argv)
    if args.older_than_days <= 0:
        parser.error("--older-than-days 必须大于 0。")
    store = JobStore(
        args.database,
        artifact_store=create_artifact_store(
            args.backend,
            root=args.artifact_root or args.database.resolve().parent / "objects",
            bucket=args.bucket,
            prefix=args.prefix,
        ),
    )
    cutoff = time.time() - args.older_than_days * 86400.0
    candidates = store.prune_artifacts(older_than=cutoff, apply=args.apply)
    print(
        json.dumps(
            {
                "status": "applied" if args.apply else "dry_run",
                "candidate_count": len(candidates),
                "candidates": candidates,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""创建或验证 Studio 队列冷备份。"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from mechagent.runtime.artifacts import create_artifact_store
from mechagent.runtime.backup import backup_studio, verify_backup


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--database", type=Path, required=True)
    create.add_argument("--destination", type=Path, required=True)
    create.add_argument("--artifact-backend", choices=("filesystem", "s3"), default="filesystem")
    create.add_argument("--bucket", default="")
    create.add_argument("--prefix", default="mechagent")
    create.add_argument("--endpoint-url", default="")
    create.add_argument("--region", default="")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "create":
        artifact_store = None
        if args.artifact_backend == "s3":
            artifact_store = create_artifact_store(
                "s3",
                bucket=args.bucket,
                prefix=args.prefix,
                endpoint_url=args.endpoint_url,
                region_name=args.region,
            )
        print(backup_studio(args.database, args.destination, artifact_store=artifact_store))
        return 0
    errors = verify_backup(args.backup)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

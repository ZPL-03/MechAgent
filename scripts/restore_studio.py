"""校验并恢复 Studio 冷备份，输出可复核的恢复摘要。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from mechagent.runtime.backup import restore_studio, verify_backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    errors = verify_backup(args.backup)
    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    if args.verify_only:
        print(
            json.dumps(
                {"status": "verified", "backup": str(args.backup.resolve())},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.destination is None:
        parser.error("恢复模式必须提供 --destination。")
    database = restore_studio(args.backup, args.destination)
    with sqlite3.connect(database) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        jobs = int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
    if integrity != "ok":
        raise RuntimeError(f"恢复数据库完整性检查失败: {integrity}")
    print(
        json.dumps(
            {
                "status": "restored",
                "database": str(database.resolve()),
                "jobs": jobs,
                "integrity": integrity,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

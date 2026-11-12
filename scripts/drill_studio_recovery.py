"""执行 Studio SQLite 冷备份、校验和恢复演练，并输出 RTO/RPO 证据。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mechagent.evidence import atomic_json
from mechagent.runtime.backup import backup_studio, restore_studio, verify_backup

SCHEMA_VERSION = 1
ACTIVE_STATUSES = {"queued", "starting", "running", "cancelling"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _database_snapshot(database: Path) -> dict[str, Any]:
    """读取不含请求正文的数据库快照。"""

    if database.is_symlink() or not database.is_file():
        raise FileNotFoundError(database)
    with sqlite3.connect(database) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"数据库完整性检查失败: {integrity}")
        rows = connection.execute("SELECT job_id,status FROM jobs ORDER BY job_id").fetchall()
    job_ids = {str(row[0]) for row in rows}
    status_counts: dict[str, int] = {}
    for _, status in rows:
        status_counts[str(status)] = status_counts.get(str(status), 0) + 1
    return {
        "integrity": integrity,
        "job_count": len(job_ids),
        "job_ids": job_ids,
        "status_counts": status_counts,
        "active_job_count": sum(status_counts.get(status, 0) for status in ACTIVE_STATUSES),
    }


def _tree_size(root: Path) -> int:
    """返回不跟随符号链接的目录文件字节数。"""

    total = 0
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        total += path.stat().st_size
    return total


def _ensure_absent(path: Path, label: str) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"{label} 已存在，演练不会覆盖已有数据：{path}")


def run_recovery_drill(
    database: Path,
    workspace: Path,
    *,
    rto_target_seconds: float,
    rpo_max_lost_jobs: int,
    output: Path | None = None,
) -> dict[str, Any]:
    """执行一次完整恢复演练并返回证据文档。

    演练只读取源数据库并将备份、恢复目录写入独立 workspace；任何已有目标目录都会
    直接失败，避免覆盖历史证据。RPO 以演练开始时可见的作业 ID 为基准，RTO 从演练
    开始到恢复数据库完整性检查结束计算。
    """

    if rto_target_seconds < 0:
        raise ValueError("rto_target_seconds 必须是非负数。")
    if rpo_max_lost_jobs < 0:
        raise ValueError("rpo_max_lost_jobs 必须是非负整数。")
    database = database.resolve()
    workspace = workspace.resolve()
    report_path = (output or workspace / "recovery-drill.json").resolve()
    backup_dir = workspace / "backup"
    restore_dir = workspace / "restore"
    _ensure_absent(backup_dir, "备份目录")
    _ensure_absent(restore_dir, "恢复目录")
    _ensure_absent(report_path, "演练报告")

    started_at = _utc_now()
    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "started_at": started_at,
        "finished_at": None,
        "database": str(database),
        "workspace": str(workspace),
        "targets": {
            "rto_seconds": rto_target_seconds,
            "rpo_max_lost_jobs": rpo_max_lost_jobs,
        },
        "checks": {},
    }
    try:
        source = _database_snapshot(database)
        if source["active_job_count"]:
            raise RuntimeError("源数据库包含未终态作业，必须停止调度器后再执行恢复演练。")
        report["source"] = {
            "integrity": source["integrity"],
            "job_count": source["job_count"],
            "status_counts": source["status_counts"],
        }

        backup_started = time.perf_counter()
        backup_studio(database, backup_dir)
        backup_seconds = time.perf_counter() - backup_started
        report["backup"] = {
            "path": str(backup_dir),
            "seconds": backup_seconds,
            "bytes": _tree_size(backup_dir),
        }
        verification_errors = verify_backup(backup_dir)
        report["backup"]["verification_errors"] = verification_errors
        if verification_errors:
            raise RuntimeError("备份清单校验失败：" + "；".join(verification_errors))

        restore_started = time.perf_counter()
        restored_database = restore_studio(backup_dir, restore_dir)
        restore_seconds = time.perf_counter() - restore_started
        restored = _database_snapshot(restored_database)
        report["restore"] = {
            "path": str(restore_dir),
            "database": str(restored_database),
            "seconds": restore_seconds,
            "integrity": restored["integrity"],
            "job_count": restored["job_count"],
            "status_counts": restored["status_counts"],
        }

        lost_job_ids = sorted(source["job_ids"] - restored["job_ids"])
        rpo_lost_jobs = len(lost_job_ids)
        total_rto_seconds = time.perf_counter() - started
        report["rpo"] = {
            "lost_jobs": rpo_lost_jobs,
            "lost_job_ids": lost_job_ids,
        }
        report["rto"] = {"seconds": total_rto_seconds}
        report["checks"] = {
            "source_integrity": source["integrity"] == "ok",
            "backup_manifest": not verification_errors,
            "restored_integrity": restored["integrity"] == "ok",
            "job_ids_preserved": rpo_lost_jobs <= rpo_max_lost_jobs,
            "rto_within_target": total_rto_seconds <= rto_target_seconds,
        }
        report["status"] = "passed" if all(report["checks"].values()) else "failed"
    except Exception as exc:
        report["error"] = str(exc)
        report["rto"] = {"seconds": time.perf_counter() - started}
    report["finished_at"] = _utc_now()
    atomic_json(report_path, report)
    report["report"] = str(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="为空的新目录；脚本在其中创建 backup、restore 和 recovery-drill.json。",
    )
    parser.add_argument("--rto-target-seconds", type=float, required=True)
    parser.add_argument("--rpo-max-lost-jobs", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_recovery_drill(
            args.database,
            args.workspace,
            rto_target_seconds=args.rto_target_seconds,
            rpo_max_lost_jobs=args.rpo_max_lost_jobs,
            output=args.output,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

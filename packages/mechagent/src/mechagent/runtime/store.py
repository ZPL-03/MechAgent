"""SQLite 队列。事务定义领取、取消和终态提交的竞争顺序。"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from mechagent.evidence import atomic_json, sha256

ACTIVE = ("starting", "running", "cancelling")
TERMINAL = ("succeeded", "failed", "cancelled", "interrupted")
DATABASE_SCHEMA_VERSION = 2


class QueueFullError(ValueError):
    """队列达到配置容量。"""


class IdempotencyError(ValueError):
    """同一个幂等键对应不同请求。"""


def iso_time(value: float | None) -> str | None:
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


class JobStore:
    def __init__(self, database: Path) -> None:
        self.database = database.resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > DATABASE_SCHEMA_VERSION:
                raise ValueError(f"不支持的作业数据库版本：{current}")
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._migrate(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """在一个事务中完成可重复执行的向前迁移。

        v1 是早期队列表结构；v2 增加迁移记录并确保提交时保存配置哈希。
        迁移只做可回滚的加法操作。缺少配置文件的历史作业保留空哈希，worker
        会拒绝执行并要求显式重新提交，避免把未经确认的旧输入静默求解。
        """

        connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL
            )"""
        )
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "jobs" not in tables:
            connection.execute(
                """
                CREATE TABLE jobs (
                    job_id TEXT PRIMARY KEY, request TEXT NOT NULL,
                    use_llm_agents INTEGER NOT NULL, config_path TEXT NOT NULL,
                    cwd TEXT NOT NULL, status TEXT NOT NULL,
                    created_at REAL NOT NULL, started_at REAL, finished_at REAL,
                    heartbeat REAL, token TEXT, pid INTEGER, process_created REAL,
                    error TEXT, error_code TEXT, idempotency_key TEXT UNIQUE,
                    parent_job_id TEXT REFERENCES jobs(job_id), result_hash TEXT,
                    config_hash TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id), payload TEXT NOT NULL
                )
                """
            )
        else:
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "config_hash" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN config_hash TEXT")
                rows = connection.execute("SELECT job_id,config_path FROM jobs").fetchall()
                for row in rows:
                    config = Path(str(row[1]))
                    value = sha256(config) if config.is_file() else None
                    connection.execute(
                        "UPDATE jobs SET config_hash=? WHERE job_id=?", (value, row[0])
                    )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id), payload TEXT NOT NULL
                )"""
            )
        connection.execute("CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS events_job ON events(job_id, sequence)")
        known = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        now = time.time()
        if 1 not in known:
            connection.execute(
                "INSERT INTO schema_migrations(version,applied_at) VALUES(1,?)", (now,)
            )
        if 2 not in known:
            connection.execute(
                "INSERT INTO schema_migrations(version,applied_at) VALUES(2,?)", (now,)
            )
        connection.execute(f"PRAGMA user_version={DATABASE_SCHEMA_VERSION}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def directory(self, job_id: str) -> Path:
        if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
            raise KeyError(job_id)
        return self.database.parent / "jobs" / job_id

    def submit(
        self,
        request: str,
        use_llm_agents: bool,
        config_path: Path,
        *,
        max_queued: int,
        idempotency_key: str | None = None,
        parent_job_id: str | None = None,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            if idempotency_key is not None:
                existing = connection.execute(
                    "SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
                if existing is not None:
                    if (
                        existing["request"],
                        bool(existing["use_llm_agents"]),
                        existing["parent_job_id"],
                        existing["config_path"],
                    ) != (request, use_llm_agents, parent_job_id, str(config_path.resolve())):
                        raise IdempotencyError("幂等键已用于不同请求。")
                    return dict(existing)
            count = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='queued'"
            ).fetchone()[0]
            if count >= max_queued:
                raise QueueFullError("作业队列已满。")
            job_id = uuid4().hex
            connection.execute(
                """INSERT INTO jobs (job_id,request,use_llm_agents,config_path,cwd,status,
                    created_at,idempotency_key,parent_job_id,config_hash)
                    VALUES (?,?,?,?,?,'queued',?,?,?,?)""",
                (
                    job_id,
                    request,
                    int(use_llm_agents),
                    str(config_path.resolve()),
                    str(Path.cwd()),
                    time.time(),
                    idempotency_key,
                    parent_job_id,
                    sha256(config_path),
                ),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def list_jobs(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC,job_id LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            ]

    def active(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM jobs WHERE status IN ('starting','running','cancelling')"
                )
            ]

    def claim(self, max_workers: int) -> dict[str, Any] | None:
        with self.transaction() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('starting','running','cancelling')"
            ).fetchone()[0]
            if count >= max_workers:
                return None
            row = connection.execute(
                "SELECT job_id FROM jobs WHERE status='queued' ORDER BY created_at,job_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            job_id = str(row[0])
            connection.execute(
                "UPDATE jobs SET status='starting',token=?,started_at=?,heartbeat=? WHERE job_id=?",
                (uuid4().hex, time.time(), time.time(), job_id),
            )
        return self.get(job_id)

    def register(self, job_id: str, token: str, pid: int, created: float) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET pid=?,process_created=?,heartbeat=?,
                status=CASE WHEN status='starting' THEN 'running' ELSE status END
                WHERE job_id=? AND token=?
                AND status IN ('starting','cancelling') AND pid IS NULL""",
                (pid, created, time.time(), job_id, token),
            )
            return cursor.rowcount == 1

    def heartbeat(self, job_id: str, token: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET heartbeat=? WHERE job_id=? AND token=? AND status='running'",
                (time.time(), job_id, token),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("作业已停止接受 worker 心跳。")

    def event(self, job_id: str, token: str, payload: dict[str, Any]) -> None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status,token FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or row["token"] != token or row["status"] != "running":
                raise RuntimeError("作业已停止接受进度事件。")
            connection.execute(
                "INSERT INTO events (job_id,payload) VALUES (?,?)",
                (job_id, json.dumps(payload, ensure_ascii=False)),
            )
            connection.execute(
                """DELETE FROM events WHERE job_id=? AND sequence NOT IN (
                SELECT sequence FROM events WHERE job_id=? ORDER BY sequence DESC LIMIT 256)""",
                (job_id, job_id),
            )

    def cancel(self, job_id: str) -> None:
        with self.transaction() as connection:
            row = connection.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row[0] == "queued":
                connection.execute(
                    "UPDATE jobs SET status='cancelled',finished_at=? WHERE job_id=?",
                    (time.time(), job_id),
                )
            elif row[0] in ACTIVE:
                connection.execute("UPDATE jobs SET status='cancelling' WHERE job_id=?", (job_id,))

    def finish(
        self,
        job_id: str,
        token: str,
        status: str,
        *,
        error: str | None = None,
        error_code: str | None = None,
        result: dict[str, Any] | None = None,
        require_unregistered: bool = False,
    ) -> bool:
        if status not in TERMINAL:
            raise ValueError(status)
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None or row["token"] != token or row["status"] not in ACTIVE:
                return False
            if require_unregistered and row["pid"] is not None:
                return False
            # 取消请求在事务中先于结果提交时，只有调度器确认进程结束才能确认取消。
            if row["status"] == "cancelling" and status != "cancelled":
                return False
            result_hash = None
            if result is not None:
                path = self.directory(job_id) / "result.json"
                atomic_json(path, result)
                result_hash = sha256(path)
            connection.execute(
                """UPDATE jobs SET status=?,finished_at=?,error=?,error_code=?,result_hash=?
                WHERE job_id=?""",
                (status, time.time(), error, error_code, result_hash, job_id),
            )
            return True

    def payload(self, job: dict[str, Any], *, include_result: bool = True) -> dict[str, Any]:
        result = None
        if include_result and job["result_hash"]:
            path = self.directory(job["job_id"]) / "result.json"
            if not path.is_file() or sha256(path) != job["result_hash"]:
                raise ValueError("作业结果文件缺失或完整性校验失败。")
            result = json.loads(path.read_text(encoding="utf-8"))
        with self.connect() as connection:
            events = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT payload FROM events WHERE job_id=? ORDER BY sequence", (job["job_id"],)
                )
            ]
        return {
            **{
                key: job[key]
                for key in ("job_id", "request", "status", "error", "error_code", "parent_job_id")
            },
            "use_llm_agents": bool(job["use_llm_agents"]),
            **{key: iso_time(job[key]) for key in ("created_at", "started_at", "finished_at")},
            "duration_ms": int(((job["finished_at"] or time.time()) - job["started_at"]) * 1000)
            if job["started_at"]
            else None,
            "result": result,
            "events": events,
        }

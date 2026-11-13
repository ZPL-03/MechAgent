"""SQLite 队列。事务定义领取、取消和终态提交的竞争顺序。"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import shutil
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from mechagent.evidence import atomic_json, sha256, verify_manifest
from mechagent.runtime.artifacts import ArtifactStore
from mechagent.runtime.auth import Principal, normalize_identity_fields

ACTIVE = ("starting", "running", "cancelling")
TERMINAL = ("succeeded", "failed", "cancelled", "interrupted")
DATABASE_SCHEMA_VERSION = 7
DEFAULT_MAX_RESULT_BYTES = 100 * 1024 * 1024


class QueueFullError(ValueError):
    """队列达到配置容量。"""


class IdempotencyError(ValueError):
    """同一个幂等键对应不同请求。"""


class StorageQuotaError(ValueError):
    """Studio 工作目录超过配置的本机存储配额。"""


def iso_time(value: float | None) -> str | None:
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def _nonnegative_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    normalized = float(value)
    if normalized < 0 or not math.isfinite(normalized):
        raise ValueError("资源 CPU 时间必须是非负有限数值。")
    return normalized


def _nonnegative_int(value: float | int | None) -> int | None:
    if value is None:
        return None
    normalized = int(value)
    if normalized < 0 or float(value) != normalized:
        raise ValueError("资源峰值内存必须是非负整数。")
    return normalized


def _validate_identity_expiry(value: float | None) -> float | None:
    """校验新建或明确设置的主体过期时间。"""

    if value is None:
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= time.time():
        raise ValueError("expires_at 必须是晚于当前时间的有限时间戳。")
    return normalized


class JobStore:
    def __init__(
        self,
        database: Path,
        artifact_root: Path | None = None,
        *,
        artifact_store: Any | None = None,
        max_active_jobs_per_project: int | None = 8,
        max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
        max_storage_bytes: int | None = None,
    ) -> None:
        if max_active_jobs_per_project is not None and max_active_jobs_per_project < 1:
            raise ValueError("max_active_jobs_per_project 必须为正数。")
        if max_result_bytes < 1024:
            raise ValueError("max_result_bytes 不能小于 1024。")
        if max_storage_bytes is not None and max_storage_bytes < 1024:
            raise ValueError("max_storage_bytes 不能小于 1024。")
        self.database = database.resolve()
        self.max_active_jobs_per_project = max_active_jobs_per_project
        self.max_result_bytes = max_result_bytes
        self.max_storage_bytes = max_storage_bytes
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts = artifact_store or ArtifactStore(
            artifact_root or self.database.parent / "objects"
        )
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

        v1 是早期队列表结构；v2 增加迁移记录并确保提交时保存配置哈希；v3
        为作业增加主体和项目归属，v4 保存结果字节数，v5 保存 worker 资源用量，v6
        增加主体目录，v7 为作业和审计记录增加组织归属。
        旧作业归入 local/default。
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
                    result_bytes INTEGER,
                    cpu_user_seconds REAL, cpu_system_seconds REAL, peak_rss_bytes INTEGER,
                    config_hash TEXT NOT NULL, owner TEXT NOT NULL DEFAULT 'local',
                    project_id TEXT NOT NULL DEFAULT 'default',
                    organization TEXT NOT NULL DEFAULT 'local'
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
            if "owner" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN owner TEXT NOT NULL DEFAULT 'local'"
                )
            if "project_id" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default'"
                )
            if "result_bytes" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN result_bytes INTEGER")
            if "cpu_user_seconds" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN cpu_user_seconds REAL")
            if "cpu_system_seconds" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN cpu_system_seconds REAL")
            if "peak_rss_bytes" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN peak_rss_bytes INTEGER")
            if "organization" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN organization TEXT NOT NULL DEFAULT 'local'"
                )
        connection.execute("CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS events_job ON events(job_id, sequence)")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                subject TEXT NOT NULL,
                action TEXT NOT NULL,
                project_id TEXT NOT NULL,
                job_id TEXT,
                outcome TEXT NOT NULL,
                details TEXT NOT NULL
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS audit_project ON audit_events(project_id, created_at)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS identities (
                subject TEXT PRIMARY KEY,
                organization TEXT NOT NULL,
                roles TEXT NOT NULL,
                projects TEXT NOT NULL,
                api_key_sha256 TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL
            )"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS identities_org ON identities(organization)")
        audit_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(audit_events)").fetchall()
        }
        if "organization" not in audit_columns:
            connection.execute(
                "ALTER TABLE audit_events ADD COLUMN organization TEXT NOT NULL DEFAULT 'local'"
            )
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
        if 3 not in known:
            connection.execute(
                "INSERT INTO schema_migrations(version,applied_at) VALUES(3,?)", (now,)
            )
        if 4 not in known:
            connection.execute(
                "INSERT INTO schema_migrations(version,applied_at) VALUES(4,?)", (now,)
            )
        if 5 not in known:
            connection.execute(
                "INSERT INTO schema_migrations(version,applied_at) VALUES(5,?)", (now,)
            )
        if 6 not in known:
            connection.execute(
                "INSERT INTO schema_migrations(version,applied_at) VALUES(6,?)", (now,)
            )
        if 7 not in known:
            connection.execute(
                "INSERT INTO schema_migrations(version,applied_at) VALUES(7,?)", (now,)
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
        owner: str = "local",
        project_id: str = "default",
        organization: str = "local",
    ) -> dict[str, Any]:
        if not organization.strip() or len(organization.strip()) > 128:
            raise ValueError("组织标识必须为 1 到 128 个字符。")
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
                        existing["owner"],
                        existing["project_id"],
                        existing["organization"],
                    ) != (
                        request,
                        use_llm_agents,
                        parent_job_id,
                        str(config_path.resolve()),
                        owner,
                        project_id,
                        organization,
                    ):
                        raise IdempotencyError("幂等键已用于不同请求。")
                    return dict(existing)
            self._ensure_storage_quota()
            count = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='queued'"
            ).fetchone()[0]
            if count >= max_queued:
                raise QueueFullError("作业队列已满。")
            if self.max_active_jobs_per_project is not None:
                project_count = connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE project_id=? AND status IN "
                    "('queued','starting','running','cancelling') AND organization=?",
                    (project_id, organization),
                ).fetchone()[0]
                if project_count >= self.max_active_jobs_per_project:
                    raise QueueFullError("项目作业配额已满。")
            job_id = uuid4().hex
            connection.execute(
                """INSERT INTO jobs (job_id,request,use_llm_agents,config_path,cwd,status,
                    created_at,idempotency_key,parent_job_id,config_hash,owner,project_id,organization)
                    VALUES (?,?,?,?,?,'queued',?,?,?,?,?,?,?)""",
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
                    owner,
                    project_id,
                    organization,
                ),
            )
        return self.get(job_id)

    def storage_usage_bytes(self) -> int:
        """返回本地 Studio 工作目录内不跟随符号链接的文件总大小。"""

        total = 0
        roots = [self.database.parent]
        artifact_root = getattr(self.artifacts, "root", None)
        if isinstance(artifact_root, Path):
            resolved_artifact_root = artifact_root.resolve()
            if not resolved_artifact_root.is_relative_to(self.database.parent.resolve()):
                roots.append(resolved_artifact_root)
        for root in roots:
            for path in root.rglob("*"):
                if path.is_symlink() or not path.is_file():
                    continue
                total += path.stat().st_size
        return total

    def _ensure_storage_quota(self) -> None:
        if self.max_storage_bytes is None:
            return
        usage = self.storage_usage_bytes()
        if usage > self.max_storage_bytes:
            raise StorageQuotaError(
                f"Studio 工作目录超过存储配额 {self.max_storage_bytes} 字节（当前 {usage} 字节）。"
            )

    def get(self, job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def list_jobs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        owner: str | None = None,
        project_id: str | None = None,
        organization: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            clauses: list[str] = []
            values: list[Any] = []
            if owner is not None:
                clauses.append("owner=?")
                values.append(owner)
            if project_id is not None:
                clauses.append("project_id=?")
                values.append(project_id)
            if organization is not None:
                clauses.append("organization=?")
                values.append(organization)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM jobs"
                    + where
                    + " ORDER BY created_at DESC,job_id LIMIT ? OFFSET ?",
                    (*values, limit, offset),
                )
            ]

    def authenticate_identity(self, token: str | None) -> Principal:
        """Authenticate a managed identity without storing or returning its token."""

        if token is None or not token.strip():
            raise ValueError("需要有效的 Bearer API key。")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.time()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM identities WHERE active=1 AND api_key_sha256=? "
                "AND (expires_at IS NULL OR expires_at>?)",
                (digest, now),
            ).fetchone()
        if row is None or not hmac.compare_digest(str(row["api_key_sha256"]), digest):
            raise ValueError("API key 无效。")
        return Principal(
            subject=str(row["subject"]),
            organization=str(row["organization"]),
            roles=frozenset(json.loads(str(row["roles"]))),
            project_ids=frozenset(json.loads(str(row["projects"]))),
        )

    def list_identities(self, *, organization: str | None = None) -> list[dict[str, Any]]:
        """List managed identities without exposing API key digests."""

        with self.connect() as connection:
            if organization is None:
                rows = connection.execute(
                    "SELECT * FROM identities ORDER BY organization,subject"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM identities WHERE organization=? ORDER BY subject",
                    (organization,),
                ).fetchall()
        return [self._identity_public(row) for row in rows]

    def get_identity(self, subject: str) -> dict[str, Any]:
        return self._identity_public(self._identity_row(subject))

    def create_identity(
        self,
        *,
        subject: str,
        organization: str,
        roles: list[str] | tuple[str, ...],
        projects: list[str] | tuple[str, ...],
        expires_at: float | None = None,
        api_key: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        normalized_subject, normalized_org, normalized_roles, normalized_projects = (
            normalize_identity_fields(
                subject=subject, organization=organization, roles=roles, projects=projects
            )
        )
        secret = api_key.strip() if api_key is not None else "mech_" + secrets.token_urlsafe(32)
        if len(secret) < 16 or any(char.isspace() for char in secret):
            raise ValueError("API key 必须至少包含 16 个非空白字符。")
        expires_at = _validate_identity_expiry(expires_at)
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        now = time.time()
        with self.transaction() as connection:
            try:
                connection.execute(
                    """INSERT INTO identities
                    (subject,organization,roles,projects,api_key_sha256,active,created_at,updated_at,expires_at)
                    VALUES (?,?,?,?,?,1,?,?,?)""",
                    (
                        normalized_subject,
                        normalized_org,
                        json.dumps(sorted(normalized_roles)),
                        json.dumps(sorted(normalized_projects)),
                        digest,
                        now,
                        now,
                        expires_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("主体标识或 API key 已存在。") from exc
            row = connection.execute(
                "SELECT * FROM identities WHERE subject=?", (normalized_subject,)
            ).fetchone()
        if row is None:
            raise RuntimeError("主体创建后无法读取。")
        return self._identity_public(row), secret

    def update_identity(
        self,
        subject: str,
        *,
        organization: str,
        roles: list[str] | tuple[str, ...] | None = None,
        projects: list[str] | tuple[str, ...] | None = None,
        active: bool | None = None,
        expires_at: float | None = None,
        preserve_expires_at: bool = False,
    ) -> dict[str, Any]:
        current = self._identity_row(subject)
        next_roles = roles if roles is not None else tuple(json.loads(str(current["roles"])))
        next_projects = (
            projects if projects is not None else tuple(json.loads(str(current["projects"])))
        )
        _, normalized_org, normalized_roles, normalized_projects = normalize_identity_fields(
            subject=subject,
            organization=organization,
            roles=next_roles,
            projects=next_projects,
        )
        next_active = int(bool(current["active"])) if active is None else int(active)
        next_expires_at = (
            float(current["expires_at"])
            if preserve_expires_at and current["expires_at"] is not None
            else _validate_identity_expiry(expires_at)
        )
        with self.transaction() as connection:
            connection.execute(
                """UPDATE identities SET organization=?,roles=?,projects=?,active=?,
                    updated_at=?,expires_at=? WHERE subject=?""",
                (
                    normalized_org,
                    json.dumps(sorted(normalized_roles)),
                    json.dumps(sorted(normalized_projects)),
                    next_active,
                    time.time(),
                    next_expires_at,
                    subject,
                ),
            )
            row = connection.execute(
                "SELECT * FROM identities WHERE subject=?", (subject,)
            ).fetchone()
        if row is None:
            raise RuntimeError("主体更新后无法读取。")
        return self._identity_public(row)

    def rotate_identity(self, subject: str) -> tuple[dict[str, Any], str]:
        self._identity_row(subject)
        secret = "mech_" + secrets.token_urlsafe(32)
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE identities SET api_key_sha256=?,updated_at=? WHERE subject=?",
                (digest, time.time(), subject),
            )
            row = connection.execute(
                "SELECT * FROM identities WHERE subject=?", (subject,)
            ).fetchone()
        if row is None:
            raise RuntimeError("主体轮换后无法读取。")
        return self._identity_public(row), secret

    def disable_identity(self, subject: str) -> dict[str, Any]:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE identities SET active=0,updated_at=? WHERE subject=?",
                (time.time(), subject),
            )
            if cursor.rowcount != 1:
                raise KeyError(subject)
            row = connection.execute(
                "SELECT * FROM identities WHERE subject=?", (subject,)
            ).fetchone()
        if row is None:
            raise RuntimeError("主体停用后无法读取。")
        return self._identity_public(row)

    def _identity_row(self, subject: str) -> sqlite3.Row:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM identities WHERE subject=?", (subject,)
            ).fetchone()
        if row is None:
            raise KeyError(subject)
        return cast(sqlite3.Row, row)

    @staticmethod
    def _identity_public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "subject": str(row["subject"]),
            "organization": str(row["organization"]),
            "roles": sorted(json.loads(str(row["roles"]))),
            "projects": sorted(json.loads(str(row["projects"]))),
            "active": bool(row["active"]),
            "created_at": iso_time(float(row["created_at"])),
            "updated_at": iso_time(float(row["updated_at"])),
            "expires_at": iso_time(float(row["expires_at"])) if row["expires_at"] else None,
        }

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

    def audit(
        self,
        *,
        subject: str,
        action: str,
        project_id: str,
        outcome: str,
        organization: str = "local",
        job_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """记录不含凭据和原始请求的主体操作审计事件。"""

        if not subject or not action or not project_id or not organization or not outcome:
            raise ValueError("审计事件主体、动作、项目、组织和结果不能为空。")
        payload = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO audit_events
                (created_at,subject,action,project_id,organization,job_id,outcome,details)
                VALUES (?,?,?,?,?,?,?,?)""",
                (time.time(), subject, action, project_id, organization, job_id, outcome, payload),
            )

    def list_audit_events(
        self,
        *,
        limit: int = 100,
        project_id: str | None = None,
        organization: str | None = None,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("审计查询 limit 必须位于 1 到 1000。")
        with self.connect() as connection:
            if project_id is None and organization is None:
                rows = connection.execute(
                    "SELECT * FROM audit_events ORDER BY sequence DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                clauses: list[str] = []
                values: list[Any] = []
                if project_id is not None:
                    clauses.append("project_id=?")
                    values.append(project_id)
                if organization is not None:
                    clauses.append("organization=?")
                    values.append(organization)
                rows = connection.execute(
                    "SELECT * FROM audit_events WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY sequence DESC LIMIT ?",
                    (*values, limit),
                ).fetchall()
        return [
            {
                **dict(row),
                "details": json.loads(str(row["details"])),
                "created_at": iso_time(float(row["created_at"])),
            }
            for row in rows
        ]

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

    def prune_artifacts(self, *, older_than: float, apply: bool = False) -> list[str]:
        """列出或删除没有作业引用且早于阈值的结果对象。

        维护操作在数据库写事务内读取引用并检查活动作业，避免清理与终态提交交叉执行。
        默认只返回候选摘要；删除必须显式传入 ``apply=True``，且由对象存储后端执行。
        """

        with self.transaction() as connection:
            active = connection.execute(
                "SELECT 1 FROM jobs WHERE status IN "
                "('queued','starting','running','cancelling') LIMIT 1"
            ).fetchone()
            if active is not None:
                raise RuntimeError("存在未终态 Studio 作业，拒绝清理结果对象。")
            rows = connection.execute(
                "SELECT result_hash FROM jobs WHERE result_hash IS NOT NULL"
            ).fetchall()
            referenced = {str(row[0]) for row in rows}
            prune = getattr(self.artifacts, "prune_unreferenced", None)
            if not callable(prune):
                raise TypeError("对象存储后端不支持结果对象保留清理。")
            return list(prune(referenced, older_than=older_than, apply=apply))

    def finish(
        self,
        job_id: str,
        token: str,
        status: str,
        *,
        error: str | None = None,
        error_code: str | None = None,
        result: dict[str, Any] | None = None,
        resources: dict[str, float | int] | None = None,
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
            result_bytes = None
            cpu_user_seconds = None
            cpu_system_seconds = None
            peak_rss_bytes = None
            if resources is not None:
                cpu_user_seconds = _nonnegative_float(resources.get("cpu_user_seconds"))
                cpu_system_seconds = _nonnegative_float(resources.get("cpu_system_seconds"))
                peak_rss_bytes = _nonnegative_int(resources.get("peak_rss_bytes"))
            if result is not None:
                path = self.directory(job_id) / "result.json"
                encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
                if len(encoded) > self.max_result_bytes:
                    path.unlink(missing_ok=True)
                    result = None
                    status = "failed"
                    error = f"作业结果超过配置上限 {self.max_result_bytes} 字节。"
                    error_code = "result_too_large"
                else:
                    atomic_json(path, result)
                    result_bytes = path.stat().st_size
                    if result_bytes > self.max_result_bytes:
                        path.unlink(missing_ok=True)
                        result = None
                        status = "failed"
                        error = f"作业结果超过配置上限 {self.max_result_bytes} 字节。"
                        error_code = "result_too_large"
                        result_bytes = None
                    else:
                        result_hash = sha256(path)
                        self.artifacts.put_file(path)
            if status == "succeeded" and self.max_storage_bytes is not None:
                usage = self.storage_usage_bytes()
                if usage > self.max_storage_bytes:
                    status = "failed"
                    error = (
                        f"Studio 工作目录超过存储配额 {self.max_storage_bytes} 字节"
                        f"（当前 {usage} 字节）。"
                    )
                    error_code = "storage_quota_exceeded"
                    result = None
                    result_hash = None
                    result_bytes = None
                    (self.directory(job_id) / "result.json").unlink(missing_ok=True)
            connection.execute(
                """UPDATE jobs SET status=?,finished_at=?,error=?,error_code=?,
                result_hash=?,result_bytes=?,cpu_user_seconds=?,cpu_system_seconds=?,
                peak_rss_bytes=? WHERE job_id=?""",
                (
                    status,
                    time.time(),
                    error,
                    error_code,
                    result_hash,
                    result_bytes,
                    cpu_user_seconds,
                    cpu_system_seconds,
                    peak_rss_bytes,
                    job_id,
                ),
            )
            return True

    def payload(self, job: dict[str, Any], *, include_result: bool = True) -> dict[str, Any]:
        result = None
        if include_result and job["result_hash"]:
            path = self.directory(job["job_id"]) / "result.json"
            digest = str(job["result_hash"])
            if not self.artifacts.verify(digest):
                raise ValueError("作业结果对象缺失或完整性校验失败。")
            if not path.is_file():
                self.artifacts.get_file(digest, path)
            if not path.is_file() or sha256(path) != digest:
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
            "owner": job["owner"],
            "project_id": job["project_id"],
            "organization": job["organization"],
            **{key: iso_time(job[key]) for key in ("created_at", "started_at", "finished_at")},
            "duration_ms": int(((job["finished_at"] or time.time()) - job["started_at"]) * 1000)
            if job["started_at"]
            else None,
            "result_bytes": job.get("result_bytes"),
            "resources": {
                "cpu_user_seconds": job.get("cpu_user_seconds"),
                "cpu_system_seconds": job.get("cpu_system_seconds"),
                "peak_rss_bytes": job.get("peak_rss_bytes"),
            },
            "result": result,
            "events": events,
        }

    def metrics(
        self,
        *,
        project_id: str | None = None,
        owner: str | None = None,
        organization: str | None = None,
    ) -> dict[str, Any]:
        """返回从持久化作业和证据状态计算的脱敏运行指标。

        指标只包含计数、时长、大小、错误码和 worker 资源用量，不返回请求文本、文件路径、
        主体凭据或原始诊断。所有时间均以秒为单位，统计范围由项目和主体过滤条件决定，
        因而在服务重启后仍保持一致的历史口径。
        """

        clauses: list[str] = []
        values: list[Any] = []
        if project_id is not None:
            clauses.append("project_id=?")
            values.append(project_id)
        if owner is not None:
            clauses.append("owner=?")
            values.append(owner)
        if organization is not None:
            clauses.append("organization=?")
            values.append(organization)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as connection:
            status_rows = connection.execute(
                "SELECT status,COUNT(*) AS count FROM jobs" + where + " GROUP BY status",
                values,
            ).fetchall()
            aggregate = connection.execute(
                """SELECT COUNT(*) AS total,
                    AVG(CASE WHEN started_at IS NOT NULL THEN started_at-created_at END) AS wait,
                    AVG(CASE WHEN finished_at IS NOT NULL AND started_at IS NOT NULL
                        THEN finished_at-started_at END) AS execution,
                    COALESCE(SUM(result_bytes),0) AS result_bytes,
                    COUNT(result_hash) AS result_objects,
                    SUM(cpu_user_seconds) AS cpu_user,
                    SUM(cpu_system_seconds) AS cpu_system,
                    MAX(peak_rss_bytes) AS peak_rss,
                    COUNT(cpu_user_seconds) AS measured_resources
                    FROM jobs"""
                + where,
                values,
            ).fetchone()
            failure_rows = connection.execute(
                "SELECT COALESCE(error_code,'unknown') AS code,COUNT(*) AS count FROM jobs"
                + (where + " AND " if where else " WHERE ")
                + "status IN ('failed','interrupted') GROUP BY COALESCE(error_code,'unknown')"
                + " ORDER BY code",
                values,
            ).fetchall()
            queued = connection.execute(
                "SELECT COUNT(*) AS count,MIN(created_at) AS oldest FROM jobs"
                + (where + " AND " if where else " WHERE ")
                + "status='queued'",
                values,
            ).fetchone()
            evidence_rows = connection.execute(
                "SELECT job_id,status FROM jobs"
                + (where + " AND " if where else " WHERE ")
                + "status IN ('succeeded','failed','cancelled','interrupted')",
                values,
            ).fetchall()
        now = time.time()
        storage: dict[str, Any]
        try:
            workspace_bytes = self.storage_usage_bytes()
        except OSError:
            workspace_bytes = None
        try:
            disk = shutil.disk_usage(self.database.parent)
            storage = {
                "available": True,
                "filesystem_total_bytes": int(disk.total),
                "filesystem_used_bytes": int(disk.used),
                "filesystem_free_bytes": int(disk.free),
                "workspace_bytes": workspace_bytes,
                "quota_bytes": self.max_storage_bytes,
                "over_quota": (
                    workspace_bytes is not None
                    and self.max_storage_bytes is not None
                    and workspace_bytes > self.max_storage_bytes
                ),
                "result_bytes": int(aggregate["result_bytes"] or 0),
            }
        except OSError:
            storage = {
                "available": False,
                "filesystem_total_bytes": None,
                "filesystem_used_bytes": None,
                "filesystem_free_bytes": None,
                "workspace_bytes": workspace_bytes,
                "quota_bytes": self.max_storage_bytes,
                "over_quota": (
                    workspace_bytes is not None
                    and self.max_storage_bytes is not None
                    and workspace_bytes > self.max_storage_bytes
                ),
                "result_bytes": int(aggregate["result_bytes"] or 0),
            }
        evidence = {"checked": 0, "valid": 0, "invalid": 0, "missing": 0}
        for row in evidence_rows:
            evidence["checked"] += 1
            manifest = self.directory(str(row["job_id"])) / "manifest.json"
            if not manifest.is_file():
                evidence["missing"] += 1
            else:
                try:
                    invalid = verify_manifest(manifest)
                except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                    invalid = ["invalid_manifest"]
                if invalid:
                    evidence["invalid"] += 1
                else:
                    evidence["valid"] += 1
        statuses = {str(row["status"]): int(row["count"]) for row in status_rows}
        return {
            "scope": {"organization": organization, "project_id": project_id, "owner": owner},
            "generated_at": iso_time(now),
            "jobs": {
                "total": int(aggregate["total"] or 0),
                "by_status": statuses,
                "queued": int(queued["count"] or 0),
                "oldest_queued_age_seconds": (
                    max(0.0, now - float(queued["oldest"]))
                    if queued["oldest"] is not None
                    else None
                ),
                "average_wait_seconds": (
                    max(0.0, float(aggregate["wait"])) if aggregate["wait"] is not None else None
                ),
                "average_execution_seconds": (
                    max(0.0, float(aggregate["execution"]))
                    if aggregate["execution"] is not None
                    else None
                ),
            },
            "failures_by_code": {str(row["code"]): int(row["count"]) for row in failure_rows},
            "results": {
                "object_count": int(aggregate["result_objects"] or 0),
                "bytes": int(aggregate["result_bytes"] or 0),
            },
            "storage": storage,
            "resources": {
                "measurement_scope": "worker_process_and_available_descendants",
                "measured_jobs": int(aggregate["measured_resources"] or 0),
                "cpu_user_seconds": float(aggregate["cpu_user"] or 0.0),
                "cpu_system_seconds": float(aggregate["cpu_system"] or 0.0),
                "peak_rss_bytes": (
                    int(aggregate["peak_rss"]) if aggregate["peak_rss"] is not None else None
                ),
            },
            "evidence": evidence,
        }

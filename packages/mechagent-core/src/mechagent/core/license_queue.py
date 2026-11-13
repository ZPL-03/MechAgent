"""基于 SQLite 的跨进程许可证槽位队列。"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class LicenseQueueError(RuntimeError):
    """许可证队列无法提供一致的槽位租约。"""


class FileLicenseQueue:
    """在共享文件系统上协调多个 Python 进程的许可证槽位。

    队列使用 SQLite 事务保证同一个资源的容量不会被并发领取超过。租约带
    过期时间并由后台心跳续租，进程异常退出后其他进程可以回收孤儿租约。
    不同进程必须使用同一个数据库路径和容量；不同容量会被拒绝，避免配置
    漂移造成超配。该实现不提供跨主机数据库或许可证服务器的高可用保证。
    """

    def __init__(
        self,
        path: Path,
        resource: str,
        capacity: int,
        *,
        lease_seconds: float = 900.0,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        if capacity < 1:
            raise ValueError("许可证队列容量必须为正数。")
        if lease_seconds <= 0 or not _finite(lease_seconds):
            raise ValueError("许可证租约时间必须为正的有限数值。")
        if poll_interval_seconds <= 0 or not _finite(poll_interval_seconds):
            raise ValueError("许可证队列轮询间隔必须为正的有限数值。")
        normalized_resource = resource.strip()
        if not normalized_resource:
            raise ValueError("许可证队列资源标识不能为空。")
        self.path = path.expanduser().resolve()
        self.resource = normalized_resource
        self.capacity = capacity
        self.lease_seconds = float(lease_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def acquire(self, timeout: float) -> Iterator["_LicenseLease"]:
        """在超时前领取一个槽位，退出上下文时释放租约。"""

        if timeout <= 0 or not _finite(timeout):
            raise ValueError("许可证队列超时必须为正的有限数值。")
        lease = self._claim_until(time.monotonic() + timeout)
        try:
            yield lease
        finally:
            lease.release()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                _create_schema(connection)
                self._check_capacity(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _claim_until(self, deadline: float) -> "_LicenseLease":
        while True:
            try:
                lease = self._try_claim()
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise LicenseQueueError(f"许可证队列数据库不可用: {exc}") from exc
                lease = None
            if lease is not None:
                return lease
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LicenseQueueError("Abaqus 许可证队列已满，等待共享槽位超时。")
            time.sleep(min(self.poll_interval_seconds, remaining))

    def _try_claim(self) -> "_LicenseLease | None":
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                _create_schema(connection)
                self._check_capacity(connection)
                connection.execute(
                    "DELETE FROM license_leases WHERE resource=? AND expires_at<=?",
                    (self.resource, now),
                )
                active = connection.execute(
                    "SELECT COUNT(*) FROM license_leases WHERE resource=?", (self.resource,)
                ).fetchone()
                if active is None or int(active[0]) >= self.capacity:
                    connection.rollback()
                    return None
                lease_id = uuid4().hex
                connection.execute(
                    """INSERT INTO license_leases
                    (lease_id, resource, owner_pid, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (lease_id, self.resource, os.getpid(), now, now + self.lease_seconds),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return _LicenseLease(self, lease_id)

    def _check_capacity(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT capacity FROM license_queue_config WHERE resource=?", (self.resource,)
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO license_queue_config(resource, capacity) VALUES (?, ?)",
                (self.resource, self.capacity),
            )
            return
        if int(row[0]) != self.capacity:
            raise LicenseQueueError(
                f"许可证队列资源 {self.resource!r} 的容量已登记为 {int(row[0])}，"
                f"当前配置为 {self.capacity}。"
            )

    def _renew(self, lease_id: str) -> bool:
        expires_at = time.time() + self.lease_seconds
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "UPDATE license_leases SET expires_at=? WHERE lease_id=? AND resource=?",
                    (expires_at, lease_id, self.resource),
                )
                return cursor.rowcount == 1
        except sqlite3.Error:
            return False

    def _release(self, lease_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM license_leases WHERE lease_id=? AND resource=?",
                (lease_id, self.resource),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.row_factory = sqlite3.Row
        return connection


class _LicenseLease:
    def __init__(self, queue: FileLicenseQueue, lease_id: str) -> None:
        self._queue = queue
        self.lease_id = lease_id
        self._stop = threading.Event()
        self._released = False
        self._thread = threading.Thread(
            target=self._heartbeat,
            name=f"license-lease-{lease_id[:8]}",
            daemon=True,
        )
        self._thread.start()

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._queue.poll_interval_seconds * 4))
        self._queue._release(self.lease_id)

    def _heartbeat(self) -> None:
        interval = max(0.1, min(30.0, self._queue.lease_seconds / 3.0))
        while not self._stop.wait(interval):
            if not self._queue._renew(self.lease_id):
                return


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS license_queue_config (
            resource TEXT PRIMARY KEY,
            capacity INTEGER NOT NULL CHECK(capacity > 0)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS license_leases (
            lease_id TEXT PRIMARY KEY,
            resource TEXT NOT NULL,
            owner_pid INTEGER NOT NULL,
            acquired_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS license_leases_resource ON license_leases(resource, expires_at)"
    )


def _finite(value: float) -> bool:
    return value == value and value not in {float("inf"), float("-inf")}

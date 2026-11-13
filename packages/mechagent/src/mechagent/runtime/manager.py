"""数据库协调的本机调度器；停止 API 不终止已领取的 worker。"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from threading import Event, Thread
from typing import Any

from mechagent.config import StudioSettings
from mechagent.evidence import write_manifest
from mechagent.redaction import redact_sensitive_text
from mechagent.runtime.process import identified_process, stop_process
from mechagent.runtime.store import JobStore

logger = logging.getLogger(__name__)


class JobManager:
    def __init__(self, store: JobStore, settings: StudioSettings) -> None:
        self.store = store
        self.settings = settings
        self.error: str | None = None
        self._stop = Event()
        self._thread: Thread | None = None
        # 保留已退出但仍对应活动作业的句柄，以便取得真实退出码并写入终态。
        self._children: dict[str, subprocess.Popen[bytes]] = {}

    def start(self) -> None:
        self._thread = Thread(target=self._loop, name="studio-dispatch", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=20)
            if self._thread.is_alive():
                raise RuntimeError("作业调度器未能停止。")

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(0.25)
        except Exception as exc:
            self.error = redact_sensitive_text(str(exc))
            logger.error("Studio 调度停止：%s", self.error)

    def tick(self) -> None:
        for active_job in self.store.active():
            self._reconcile(active_job)
        active_ids = {str(job["job_id"]) for job in self.store.active()}
        self._children = {
            job_id: child for job_id, child in self._children.items() if job_id in active_ids
        }
        while not self._stop.is_set():
            job = self.store.claim(self.settings.max_workers)
            if job is None:
                break
            directory = self.store.directory(job["job_id"])
            directory.mkdir(parents=True, exist_ok=True)
            try:
                with (directory / "worker.log").open("ab") as log:
                    child = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "mechagent.runtime.worker",
                            "--database",
                            str(self.store.database),
                            "--job-id",
                            job["job_id"],
                            "--token",
                            job["token"],
                        ],
                        cwd=job["cwd"],
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                        start_new_session=os.name != "nt",
                    )
                self._children[str(job["job_id"])] = child
            except OSError as exc:
                self._end(job, "failed", "worker_start_failed", redact_sensitive_text(str(exc)))

    def _reconcile(self, job: dict[str, Any]) -> None:
        now = time.time()
        if job["pid"] is None:
            if now - job["started_at"] > self.settings.startup_timeout:
                status = "cancelled" if job["status"] == "cancelling" else "interrupted"
                self._end(job, status, "worker_not_registered", "执行进程未在启动期限内登记。")
            return
        process = identified_process(job["pid"], job["process_created"])
        if process is None:
            status = "cancelled" if job["status"] == "cancelling" else "interrupted"
            exit_code = self._worker_exit_code(str(job["job_id"]))
            if exit_code is None:
                code, message = "worker_exited", "执行进程已退出，未取得退出码。"
            else:
                code, message = (
                    "worker_exited",
                    f"执行进程已退出，退出码 {exit_code}。",
                )
            self._end(job, status, code, message, worker_exit_code=exit_code)
            return
        code = message = ""
        status = "interrupted"
        if job["status"] == "cancelling":
            status, code, message = "cancelled", "user_cancelled", "作业已取消。"
        elif now - job["started_at"] > self.settings.job_timeout:
            status, code, message = "failed", "job_timeout", "作业超过执行时限。"
        elif now - job["heartbeat"] > self.settings.heartbeat_timeout:
            code, message = "heartbeat_lost", "执行进程心跳超时。"
        if code:
            stop_process(job["pid"], job["process_created"])
            self._end(job, status, code, message)

    def _worker_exit_code(self, job_id: str) -> int | None:
        child = self._children.get(job_id)
        if child is None:
            return None
        return child.poll()

    def _end(
        self,
        job: dict[str, Any],
        status: str,
        code: str,
        message: str,
        *,
        worker_exit_code: int | None = None,
    ) -> None:
        # 先保存部分产物证据，再提交终态；保存失败会中止调度并公开错误。
        latest = self.store.get(job["job_id"])
        if latest["status"] not in ("starting", "running", "cancelling"):
            return
        if latest["status"] == "cancelling":
            status = "cancelled"
        write_manifest(
            self.store.directory(job["job_id"]),
            status=status,
            details={
                "job_id": job["job_id"],
                "error_code": code,
                "error": message,
                **({"worker_exit_code": worker_exit_code} if worker_exit_code is not None else {}),
            },
        )
        self.store.finish(
            job["job_id"],
            job["token"],
            status,
            error=message,
            error_code=code,
            worker_exit_code=worker_exit_code,
            require_unregistered=job["pid"] is None,
        )

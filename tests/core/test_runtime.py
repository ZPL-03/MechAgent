"""持久队列、进程故障和运行证据的行为验证。"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psutil
import pytest
from typer.testing import CliRunner

from mechagent.app import MechAgent
from mechagent.cli import app
from mechagent.config import MechAgentConfig, StudioSettings, config_to_public_dict
from mechagent.evidence import verify_manifest, write_manifest
from mechagent.runtime.manager import JobManager
from mechagent.runtime.process import identified_process, stop_process
from mechagent.runtime.store import IdempotencyError, JobStore, QueueFullError


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    return JobStore(tmp_path / "jobs.sqlite3")


def submit(store: JobStore, **kwargs: Any) -> dict[str, Any]:
    return store.submit(
        "不支持的仿真请求", False, store.database.parent / "config.yaml", max_queued=5, **kwargs
    )


def test_concurrent_idempotency_and_capacity(store: JobStore) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(lambda _: submit(store, idempotency_key="same"), range(16)))
    assert len({job["job_id"] for job in jobs}) == 1
    with pytest.raises(IdempotencyError):
        store.submit(
            "不同输入",
            False,
            store.database.parent / "config.yaml",
            max_queued=1,
            idempotency_key="same",
        )
    with pytest.raises(QueueFullError):
        store.submit("输入", False, store.database.parent / "config.yaml", max_queued=1)


def test_multiple_dispatchers_claim_atomically(store: JobStore) -> None:
    for _ in range(5):
        submit(store)
    other = JobStore(store.database)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda i: (store if i % 2 else other).claim(2), range(8)))
    assert len([job for job in claimed if job]) == 2
    assert len(store.active()) == 2


def test_cancel_wins_over_late_result_and_terminals_are_immutable(store: JobStore) -> None:
    submit(store)
    job = store.claim(1)
    assert job
    store.cancel(job["job_id"])
    assert not store.finish(job["job_id"], job["token"], "succeeded", result={"success": True})
    assert not store.finish(job["job_id"], "wrong-token", "cancelled")
    assert store.finish(job["job_id"], job["token"], "cancelled")
    assert not store.register(job["job_id"], job["token"], os.getpid(), time.time())
    assert not store.finish(job["job_id"], job["token"], "failed")
    store.cancel(job["job_id"])
    assert store.get(job["job_id"])["status"] == "cancelled"


def test_queued_cancel_does_not_execute(store: JobStore) -> None:
    job = submit(store)
    store.cancel(job["job_id"])
    assert store.claim(1) is None
    assert JobStore(store.database).get(job["job_id"])["status"] == "cancelled"


def test_event_retention_and_result_integrity(store: JobStore) -> None:
    submit(store)
    job = store.claim(1)
    assert job and store.register(
        job["job_id"], job["token"], os.getpid(), psutil.Process().create_time()
    )
    for index in range(260):
        store.event(job["job_id"], job["token"], {"index": index})
    assert store.finish(job["job_id"], job["token"], "succeeded", result={"success": True})
    payload = store.payload(store.get(job["job_id"]))
    assert len(payload["events"]) == 256
    assert payload["events"][0]["index"] == 4
    assert payload["result"]["success"]
    (store.directory(job["job_id"]) / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="完整性"):
        store.payload(store.get(job["job_id"]))
    with pytest.raises(RuntimeError):
        store.heartbeat(job["job_id"], job["token"])


def test_future_database_version_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "future.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="数据库版本"):
        JobStore(database)


def test_startup_failure_is_interrupted_without_reexecution(store: JobStore) -> None:
    submit(store)
    job = store.claim(1)
    assert job
    with store.connect() as connection:
        connection.execute("UPDATE jobs SET started_at=0 WHERE job_id=?", (job["job_id"],))
    manager = JobManager(store, StudioSettings())
    manager.tick()
    assert store.get(job["job_id"])["status"] == "interrupted"
    assert not store.active()
    assert store.claim(1) is None
    assert verify_manifest(store.directory(job["job_id"]) / "manifest.json") == []


def test_pid_reuse_is_not_treated_as_our_worker(store: JobStore) -> None:
    submit(store)
    job = store.claim(1)
    assert job
    created = psutil.Process().create_time()
    assert identified_process(os.getpid(), created) is not None
    assert identified_process(os.getpid(), created - 100) is None
    store.register(job["job_id"], job["token"], os.getpid(), created - 100)
    JobManager(store, StudioSettings()).tick()
    assert store.get(job["job_id"])["status"] == "interrupted"
    assert psutil.Process().is_running()


@pytest.mark.parametrize("reason", ["cancel", "heartbeat", "timeout"])
def test_process_tree_stops_and_partial_evidence_survives(
    store: JobStore, tmp_path: Path, reason: str
) -> None:
    submit(store)
    job = store.claim(1)
    assert job
    ready = tmp_path / "ready.json"
    script = (
        "import os,sys,time,json,subprocess,psutil; from pathlib import Path; "
        "from mechagent.runtime.process import process_boundary; "
        "boundary=process_boundary(); boundary.__enter__(); "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(90)']); "
        "Path(sys.argv[1]).write_text(json.dumps([os.getpid(),psutil.Process().create_time(),"
        "child.pid,psutil.Process(child.pid).create_time()])); time.sleep(90)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(ready)], start_new_session=os.name != "nt"
    )
    child_pid: int | None = None
    child_created: float | None = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        pid, created, child_pid, child_created = json.loads(ready.read_text(encoding="utf-8"))
        assert store.register(job["job_id"], job["token"], pid, created)
        directory = store.directory(job["job_id"])
        directory.mkdir(parents=True)
        (directory / "partial.inp").write_text("*NODE", encoding="utf-8")
        manager = JobManager(store, StudioSettings())
        manager.start()
        manager.close()
        assert identified_process(pid, created) is not None  # API 停止不杀 worker。
        if reason == "cancel":
            store.cancel(job["job_id"])
        else:
            column = "heartbeat" if reason == "heartbeat" else "started_at"
            with store.connect() as connection:
                connection.execute(f"UPDATE jobs SET {column}=0 WHERE job_id=?", (job["job_id"],))
        JobManager(JobStore(store.database), StudioSettings()).tick()
        status = {"cancel": "cancelled", "heartbeat": "interrupted", "timeout": "failed"}[reason]
        assert store.get(job["job_id"])["status"] == status
        assert identified_process(pid, created) is None
        for _ in range(100):
            if identified_process(child_pid, child_created) is None:
                break
            time.sleep(0.02)
        assert identified_process(child_pid, child_created) is None
        assert (directory / "partial.inp").exists()
        assert verify_manifest(directory / "manifest.json") == []
    finally:
        if process.poll() is None:
            stop_process(process.pid, psutil.Process(process.pid).create_time())
        process.wait(timeout=10)
        child = identified_process(child_pid, child_created)
        if child is not None:
            child.kill()


def test_worker_rejects_config_changed_after_submission(store: JobStore) -> None:
    job = submit(store)
    (store.database.parent / "config.yaml").write_text("orchestrator: {}", encoding="utf-8")
    manager = JobManager(store, StudioSettings())
    manager.start()
    try:
        deadline = time.monotonic() + 20
        while store.get(job["job_id"])["status"] not in ("failed", "interrupted"):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        payload = store.payload(store.get(job["job_id"]))
        assert payload["status"] == "failed"
        assert "配置文件" in payload["error"]
    finally:
        manager.close()


def test_manifest_detects_changes_missing_files_and_escape(tmp_path: Path) -> None:
    artifact = tmp_path / "input.inp"
    artifact.write_text("*NODE", encoding="utf-8")
    path = write_manifest(tmp_path, status="succeeded", details={})
    assert verify_manifest(path) == []
    assert CliRunner().invoke(app, ["verify-evidence", str(path)]).exit_code == 0
    artifact.write_text("*NOPE", encoding="utf-8")
    assert verify_manifest(path) == ["hash_mismatch: input.inp"]
    assert CliRunner().invoke(app, ["verify-evidence", str(path)]).exit_code == 1
    artifact.unlink()
    assert verify_manifest(path) == ["missing: input.inp"]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["path"] = "../outside"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_manifest(path) == ["invalid_path: ../outside"]


def test_sdk_failure_manifest_and_config_do_not_expose_secrets(tmp_path: Path) -> None:
    config = MechAgentConfig.model_validate(
        {
            "llm": {
                "api_key": "private-test-value",
                "base_url": "https://example.com/v1?token=private-query",
            },
            "output": {"output_dir": tmp_path},
        }
    )
    public = json.dumps(config_to_public_dict(config))
    assert "private-test-value" not in public and "private-query" not in public
    result = MechAgent(config).run("不支持的仿真请求")
    assert not result.summary["success"]
    assert result.manifest_path
    assert verify_manifest(result.manifest_path) == []
    contents = result.manifest_path.read_text(encoding="utf-8")
    assert "private-test-value" not in contents and "private-query" not in contents
    assert json.loads(contents)["status"] == "failed"

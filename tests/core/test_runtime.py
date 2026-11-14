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
from mechagent.config import (
    AuthPrincipalSettings,
    MechAgentConfig,
    StudioSettings,
    config_to_public_dict,
)
from mechagent.evidence import (
    artifact_records,
    public_value,
    sha256,
    stable_artifact_records,
    verify_manifest,
    write_manifest,
)
from mechagent.runtime.manager import JobManager
from mechagent.runtime.process import identified_process, stop_process
from mechagent.runtime.rate_limit import SlidingWindowRateLimiter
from mechagent.runtime.store import IdempotencyError, JobStore, QueueFullError


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    return JobStore(tmp_path / "jobs.sqlite3")


def submit(store: JobStore, **kwargs: Any) -> dict[str, Any]:
    return store.submit(
        "不支持的仿真请求", False, store.database.parent / "config.yaml", max_queued=5, **kwargs
    )


def test_sliding_window_rate_limiter_expires_events() -> None:
    current = [100.0]
    limiter = SlidingWindowRateLimiter(2, 10.0, clock=lambda: current[0])

    assert limiter.check("client").remaining == 1
    assert limiter.check("client").remaining == 0
    blocked = limiter.check("client")
    assert blocked.allowed is False
    assert blocked.retry_after == 10

    current[0] = 110.0
    assert limiter.check("client").allowed is True
    assert limiter.check("other").allowed is True


def test_studio_auth_required_rejects_missing_or_malformed_digest() -> None:
    with pytest.raises(ValueError, match="auth_required=true"):
        StudioSettings(auth_required=True)
    with pytest.raises(ValueError, match="64 位 SHA-256"):
        StudioSettings(auth_api_key_sha256="secret")


def test_studio_auth_directory_and_s3_settings_require_explicit_scope() -> None:
    settings = StudioSettings(
        auth_required=True,
        auth_principals=[
            AuthPrincipalSettings(
                subject="alice",
                api_key_sha256="a" * 64,
                organization="org-a",
                roles=["runner"],
                projects=["project-a"],
            )
        ],
        artifact_backend="s3",
        artifact_s3_bucket="results",
    )
    assert settings.auth_principals[0].organization == "org-a"
    with pytest.raises(ValueError, match="artifact_s3_bucket"):
        StudioSettings(artifact_backend="s3")


def test_expired_managed_identity_cannot_authenticate(store: JobStore) -> None:
    _, secret = store.create_identity(
        subject="expired",
        organization="engineering",
        roles=["viewer"],
        projects=["project-a"],
        expires_at=time.time() + 3600,
        api_key="expired-key-123456",
    )
    with store.transaction() as connection:
        connection.execute(
            "UPDATE identities SET expires_at=? WHERE subject=?",
            (time.time() - 1, "expired"),
        )

    with pytest.raises(ValueError, match="API key 无效"):
        store.authenticate_identity(secret)


def test_public_config_redacts_configured_studio_key_digests() -> None:
    config = MechAgentConfig(
        studio=StudioSettings(
            auth_api_key_sha256="a" * 64,
            auth_principals=[AuthPrincipalSettings(subject="alice", api_key_sha256="b" * 64)],
        )
    )
    public = json.dumps(config_to_public_dict(config))
    assert "a" * 64 not in public
    assert "b" * 64 not in public


def test_public_value_sanitizes_local_paths_without_changing_request_text() -> None:
    payload = public_value(
        {
            "request": r"读取 C:\engineering\case.inp 并比较 /tmp/reference.frd",
            "summary": {
                "work_dir": r"C:\Users\工程师\runs\RUN_001",
                "report_path": "/tmp/mechagent/RUN_001/report.md",
                "output_files": [r"C:\Users\工程师\runs\RUN_001\case.inp", "results/case.frd"],
                "artifacts": [{"path": r"\\server\share\results\case.odb"}],
                "values": {"field_json": "../private/case.fields.json"},
            },
            "event": {"path": "/api/v1/jobs/RUN_001"},
        },
        sanitize_paths=True,
    )

    assert payload["request"] == r"读取 C:\engineering\case.inp 并比较 /tmp/reference.frd"
    assert payload["summary"]["work_dir"] == "RUN_001"
    assert payload["summary"]["report_path"] == "report.md"
    assert payload["summary"]["output_files"] == ["case.inp", "results/case.frd"]
    assert payload["summary"]["artifacts"][0]["path"] == "case.odb"
    assert payload["summary"]["values"]["field_json"] == "case.fields.json"
    assert payload["event"]["path"] == "/api/v1/jobs/RUN_001"


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


def test_job_and_audit_cursor_pages_are_complete_and_deterministic(store: JobStore) -> None:
    for index in range(5):
        submit(store, project_id="page-project", idempotency_key=f"page-{index}")
        store.audit(
            subject="tester",
            action="read",
            project_id="page-project",
            outcome="allowed",
            details={"index": index},
        )

    first = store.list_jobs_page(limit=2, project_id="page-project")
    assert len(first["items"]) == 2
    assert first["has_more"] is True
    assert first["next_cursor"]
    second = store.list_jobs_page(limit=2, cursor=first["next_cursor"], project_id="page-project")
    third = store.list_jobs_page(limit=2, cursor=second["next_cursor"], project_id="page-project")
    job_ids = [item["job_id"] for page in (first, second, third) for item in page["items"]]
    assert len(job_ids) == len(set(job_ids)) == 5
    assert third["has_more"] is False
    assert third["next_cursor"] is None

    audit_first = store.list_audit_events_page(limit=2, project_id="page-project")
    audit_second = store.list_audit_events_page(
        limit=2, cursor=audit_first["next_cursor"], project_id="page-project"
    )
    audit_third = store.list_audit_events_page(
        limit=2, cursor=audit_second["next_cursor"], project_id="page-project"
    )
    sequences = [
        item["sequence"]
        for page in (audit_first, audit_second, audit_third)
        for item in page["items"]
    ]
    assert len(sequences) == len(set(sequences)) == 5
    assert audit_third["has_more"] is False

    with pytest.raises(ValueError, match="分页游标无效"):
        store.list_jobs_page(limit=2, cursor="not-a-cursor", project_id="page-project")
    with pytest.raises(ValueError, match="查询范围"):
        store.list_jobs_page(limit=2, cursor=first["next_cursor"], project_id="other-project")
    with pytest.raises(ValueError, match="不能同时"):
        store.list_jobs_page(limit=2, offset=0, cursor=first["next_cursor"])


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
    assert store.finish(
        job["job_id"],
        job["token"],
        "succeeded",
        result={"success": True},
        resources={"cpu_user_seconds": 1.25, "cpu_system_seconds": 0.5, "peak_rss_bytes": 4096},
    )
    payload = store.payload(store.get(job["job_id"]))
    assert len(payload["events"]) == 256
    assert payload["events"][0]["index"] == 4
    assert payload["result"]["success"]
    assert payload["result_bytes"] > 0
    assert payload["resources"] == {
        "cpu_user_seconds": 1.25,
        "cpu_system_seconds": 0.5,
        "peak_rss_bytes": 4096,
    }
    write_manifest(
        store.directory(job["job_id"]), status="succeeded", details={"job_id": job["job_id"]}
    )
    metrics = store.metrics()
    assert metrics["jobs"]["by_status"]["succeeded"] == 1
    assert metrics["results"]["object_count"] == 1
    assert metrics["results"]["bytes"] == payload["result_bytes"]
    assert metrics["storage"]["available"] is True
    assert metrics["storage"]["result_bytes"] == payload["result_bytes"]
    assert metrics["resources"] == {
        "measurement_scope": "worker_process_and_available_descendants",
        "measured_jobs": 1,
        "cpu_user_seconds": 1.25,
        "cpu_system_seconds": 0.5,
        "peak_rss_bytes": 4096,
    }
    assert metrics["evidence"] == {"checked": 1, "valid": 1, "invalid": 0, "missing": 0}
    (store.directory(job["job_id"]) / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="完整性"):
        store.payload(store.get(job["job_id"]))
    with pytest.raises(RuntimeError):
        store.heartbeat(job["job_id"], job["token"])


def test_finish_persists_worker_exit_code(store: JobStore) -> None:
    job = submit(store)
    claimed = store.claim(1)
    assert claimed and store.register(
        claimed["job_id"], claimed["token"], os.getpid(), psutil.Process().create_time()
    )
    assert store.finish(
        claimed["job_id"],
        claimed["token"],
        "interrupted",
        error="执行进程已退出，退出码 17。",
        error_code="worker_exited",
        worker_exit_code=17,
    )
    payload = store.payload(store.get(job["job_id"]), include_result=False)
    assert payload["worker_exit_code"] == 17
    invalid = submit(store)
    invalid_claimed = store.claim(1)
    assert invalid_claimed
    with pytest.raises(ValueError, match="worker_exit_code"):
        store.finish(
            invalid["job_id"],
            invalid_claimed["token"],
            "failed",
            worker_exit_code=2**32,
        )


def test_future_database_version_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "future.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="数据库版本"):
        JobStore(database)


def test_legacy_database_migrates_and_records_schema_versions(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY, request TEXT NOT NULL,
                use_llm_agents INTEGER NOT NULL, config_path TEXT NOT NULL,
                cwd TEXT NOT NULL, status TEXT NOT NULL,
                created_at REAL NOT NULL, started_at REAL, finished_at REAL,
                heartbeat REAL, token TEXT, pid INTEGER, process_created REAL,
                error TEXT, error_code TEXT, idempotency_key TEXT UNIQUE,
                parent_job_id TEXT REFERENCES jobs(job_id), result_hash TEXT
            );
            CREATE TABLE events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(job_id), payload TEXT NOT NULL
            );
            PRAGMA user_version=1;
            """
        )
        connection.execute(
            """INSERT INTO jobs(job_id,request,use_llm_agents,config_path,cwd,status,created_at)
            VALUES('legacy-job','请求',0,?,?, 'queued',?)""",
            (str(config), str(tmp_path), time.time()),
        )

    store = JobStore(database)
    with store.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert "organization" in {
            str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")
        }
        assert "worker_exit_code" in {
            str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")
        }
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='identities'"
        ).fetchone()
        assert [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    migrated = store.get("legacy-job")
    assert migrated["config_hash"]
    assert store.submit("新请求", False, config, max_queued=2)["status"] == "queued"


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


def test_manager_records_exit_code_for_crashed_worker(store: JobStore, tmp_path: Path) -> None:
    submit(store)
    claimed = store.claim(1)
    assert claimed
    ready = tmp_path / "ready.json"
    script = (
        "import json,os,sys,time,psutil; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(json.dumps([os.getpid(),psutil.Process().create_time()]))"
        "; time.sleep(0.1); os._exit(17)"
    )
    process = subprocess.Popen([sys.executable, "-c", script, str(ready)])
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        pid, created = json.loads(ready.read_text(encoding="utf-8"))
        assert store.register(claimed["job_id"], claimed["token"], pid, created)
        process.wait(timeout=10)
        manager = JobManager(store, StudioSettings())
        manager._children[claimed["job_id"]] = process
        manager.tick()
        finished = store.get(claimed["job_id"])
        assert finished["status"] == "interrupted"
        assert finished["error_code"] == "worker_exited"
        assert finished["worker_exit_code"] == 17
        manifest = json.loads(
            (store.directory(claimed["job_id"]) / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["details"]["worker_exit_code"] == 17
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


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
    assert (
        CliRunner().invoke(app, ["verify-evidence", "--require-provenance", str(path)]).exit_code
        == 0
    )
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


def test_manifest_detects_unlisted_files(tmp_path: Path) -> None:
    (tmp_path / "input.inp").write_text("*NODE", encoding="utf-8")
    path = write_manifest(tmp_path, status="succeeded", details={})
    (tmp_path / "unexpected.bin").write_bytes(b"unexpected")

    assert verify_manifest(path) == ["unlisted: unexpected.bin"]


def test_manifest_binds_source_runtime_config_and_tool_provenance(tmp_path: Path) -> None:
    config = tmp_path / "mechagent.yaml"
    config.write_text("solver: calculix\n", encoding="utf-8")
    artifact = tmp_path / "result.json"
    artifact.write_text("{}", encoding="utf-8")

    path = write_manifest(
        tmp_path,
        status="succeeded",
        details={"source": str(config)},
        config_paths={"config": config},
        tool_versions={"calculix": "CalculiX 2.23"},
    )

    manifest = json.loads(path.read_text(encoding="utf-8"))
    provenance = manifest["provenance"]
    assert provenance["schema"] == "mechagent.evidence-provenance.v1"
    assert provenance["source"]["git_dirty"] in (True, False, "unknown")
    assert provenance["configs"]["config"]["path"] == "mechagent.yaml"
    assert provenance["configs"]["config"]["sha256"]
    assert provenance["tools"]["calculix"] == {
        "executable": "unknown",
        "version": "CalculiX 2.23",
    }
    assert manifest["details"]["source"] == "mechagent.yaml"
    assert str(tmp_path) not in path.read_text(encoding="utf-8")
    assert verify_manifest(path) == []


def test_solver_version_probe_is_side_effect_free(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        status="succeeded",
        details={},
        tool_commands={"calculix": "ccx"},
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["provenance"]["tools"]["calculix"]["version"] == "unavailable"


def test_verify_manifest_rejects_invalid_provenance(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    path = write_manifest(tmp_path, status="succeeded", details={})
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["provenance"]["configs"]["leak"] = {
        "path": "C:/private/config.yaml",
        "sha256": "0" * 64,
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert "invalid_provenance: configs.leak.path" in verify_manifest(path)


def test_verify_manifest_can_require_provenance(tmp_path: Path) -> None:
    artifact = tmp_path / "result.json"
    artifact.write_text("{}", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "status": "succeeded",
        "details": {},
        "artifacts": [{"path": "result.json", "size": 2, "sha256": sha256(artifact)}],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert verify_manifest(path) == []
    assert verify_manifest(path, require_provenance=True) == ["missing_provenance"]


def test_artifact_records_hashes_nested_files_and_excludes_manifest(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "result.bin"
    nested.parent.mkdir()
    nested.write_bytes(b"result")
    (tmp_path / "jobs.sqlite3-wal").write_bytes(b"transient")
    (tmp_path / "jobs.sqlite3-shm").write_bytes(b"transient")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")

    records = artifact_records(tmp_path)

    assert records == [
        {
            "path": "nested/result.bin",
            "size": 6,
            "sha256": "f6a214f7a5fcda0c2cee9660b7fc29f5649e3c68aad48e20e950137c98913a68",
        }
    ]


def test_stable_artifact_records_waits_for_solver_lock_release(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    assert stable_artifact_records(tmp_path, attempts=2, interval_seconds=0.001)

    lock = tmp_path / "case.lck"
    lock.write_text("active", encoding="utf-8")
    with pytest.raises(RuntimeError, match="活动求解锁"):
        stable_artifact_records(tmp_path, attempts=2, interval_seconds=0.001)


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

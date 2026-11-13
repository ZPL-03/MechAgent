"""对象存储和 Studio 备份测试。"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from scripts import check_s3_storage, drill_studio_recovery

from mechagent.evidence import verify_manifest
from mechagent.runtime.artifacts import ArtifactStore, S3ArtifactStore
from mechagent.runtime.backup import backup_studio, restore_studio, verify_backup
from mechagent.runtime.store import JobStore, StorageQuotaError


def test_artifact_store_deduplicates_and_restores_result(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    job = store.submit("request", False, config, max_queued=2, idempotency_key="one")
    claimed = store.claim(1)
    assert claimed is not None
    assert store.register(job["job_id"], claimed["token"], 1, 1.0)
    assert store.finish(
        job["job_id"],
        claimed["token"],
        "succeeded",
        result={"success": True, "value": 3},
    )
    result_path = store.directory(job["job_id"]) / "result.json"
    object_path = store.artifacts.path_for(store.get(job["job_id"])["result_hash"])
    result_path.unlink()

    payload = store.payload(store.get(job["job_id"]))

    assert payload["result"] == {"success": True, "value": 3}
    assert object_path.is_file()


def test_artifact_store_put_bytes_is_safe_for_same_process_concurrency(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "objects")
    payloads = [f"payload-{index}".encode() for index in range(16)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        digests = list(executor.map(store.put_bytes, payloads))

    assert len(set(digests)) == len(payloads)
    assert [store.path_for(digest).read_bytes() for digest in digests] == payloads
    assert not list((tmp_path / "objects").rglob("*.tmp"))


def test_artifact_store_keeps_object_when_destination_is_object_path(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "objects")
    digest = artifacts.put_bytes(b"immutable")
    object_path = artifacts.path_for(digest)

    assert artifacts.get_file(digest, object_path) == object_path
    assert object_path.read_bytes() == b"immutable"
    assert artifacts.verify(digest)


def test_artifact_store_preserves_destination_when_restore_integrity_fails(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "objects")
    digest = artifacts.put_bytes(b"immutable")
    artifacts.path_for(digest).write_bytes(b"tampered")
    destination = tmp_path / "restored.bin"
    destination.write_bytes(b"keep")

    with pytest.raises(ValueError, match="完整性校验失败"):
        artifacts.get_file(digest, destination)

    assert destination.read_bytes() == b"keep"
    assert not list(tmp_path.glob(".restored.bin.*.tmp"))


def test_artifact_store_repairs_existing_corrupt_object(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "objects")
    source = tmp_path / "source.bin"
    source.write_bytes(b"expected")
    digest = artifacts.put_file(source)
    artifacts.path_for(digest).write_bytes(b"corrupt")

    assert artifacts.put_file(source) == digest
    assert artifacts.verify(digest)
    assert artifacts.path_for(digest).read_bytes() == b"expected"


def test_s3_artifact_store_uses_sha256_metadata(tmp_path: Path) -> None:
    class FakeS3:
        def __init__(self) -> None:
            self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}
            self.upload_count = 0

        def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
            try:
                content, metadata = self.objects[(Bucket, Key)]
            except KeyError as exc:
                error = type("NotFound", (Exception,), {})()
                error.response = {"Error": {"Code": "404"}}
                raise error from exc
            return {"ContentLength": len(content), "Metadata": metadata}

        def upload_file(
            self, source: str, bucket: str, key: str, *, ExtraArgs: dict[str, Any]
        ) -> None:
            self.upload_count += 1
            self.objects[(bucket, key)] = (
                Path(source).read_bytes(),
                dict(ExtraArgs["Metadata"]),
            )

        def upload_fileobj(
            self, stream: Any, bucket: str, key: str, *, ExtraArgs: dict[str, Any]
        ) -> None:
            self.upload_count += 1
            self.objects[(bucket, key)] = (stream.read(), dict(ExtraArgs["Metadata"]))

        def download_file(self, bucket: str, key: str, destination: str) -> None:
            Path(destination).write_bytes(self.objects[(bucket, key)][0])

    fake = FakeS3()
    store = S3ArtifactStore("results", client=fake)
    source = tmp_path / "result.json"
    source.write_text('{"ok":true}', encoding="utf-8")
    digest = store.put_file(source)
    bytes_digest = store.put_bytes(b"memory-result")
    assert store.put_bytes(b"memory-result") == bytes_digest
    assert fake.upload_count == 2
    destination = tmp_path / "restored.json"

    assert store.verify(digest)
    assert store.verify(bytes_digest)
    assert store.get_file(digest, destination).read_text(encoding="utf-8") == source.read_text(
        encoding="utf-8"
    )

    fake.objects[("results", store._key(digest))] = (b"tampered", {"sha256": digest})
    assert store.verify(digest) is False
    assert store.put_file(source) == digest
    assert store.verify(digest) is True
    fake.objects[("results", store._key(digest))] = (b"tampered", {"sha256": digest})
    destination.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="完整性校验失败"):
        store.get_file(digest, destination)
    assert destination.read_text(encoding="utf-8") == "keep"
    assert not list(tmp_path.glob(".restored.json.*.tmp"))


def test_s3_artifact_store_rejects_tampered_upload(tmp_path: Path) -> None:
    class TamperingS3:
        def __init__(self) -> None:
            self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}

        def upload_file(
            self, _source: str, bucket: str, key: str, *, ExtraArgs: dict[str, Any]
        ) -> None:
            self.objects[(bucket, key)] = (b"tampered", dict(ExtraArgs["Metadata"]))

        def upload_fileobj(
            self, _stream: Any, bucket: str, key: str, *, ExtraArgs: dict[str, Any]
        ) -> None:
            self.objects[(bucket, key)] = (b"tampered", dict(ExtraArgs["Metadata"]))

        def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
            try:
                content, metadata = self.objects[(Bucket, Key)]
            except KeyError as exc:
                error = type("NotFound", (Exception,), {})()
                error.response = {"Error": {"Code": "404"}}
                raise error from exc
            return {"ContentLength": len(content), "Metadata": metadata}

        def download_file(self, bucket: str, key: str, destination: str) -> None:
            Path(destination).write_bytes(self.objects[(bucket, key)][0])

    client = TamperingS3()
    store = S3ArtifactStore("results", client=client)
    source = tmp_path / "result.bin"
    source.write_bytes(b"expected")

    with pytest.raises(ValueError, match="内容校验失败"):
        store.put_file(source)
    with pytest.raises(ValueError, match="内容校验失败"):
        store.put_bytes(b"expected-bytes")


def test_s3_probe_writes_verifiable_evidence_without_retaining_object(tmp_path: Path) -> None:
    class FakeS3:
        def __init__(self) -> None:
            self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}

        def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
            try:
                content, metadata = self.objects[(Bucket, Key)]
            except KeyError as exc:
                error = type("NotFound", (Exception,), {})()
                error.response = {"Error": {"Code": "404"}}
                raise error from exc
            return {"ContentLength": len(content), "Metadata": metadata}

        def upload_fileobj(
            self, stream: Any, bucket: str, key: str, *, ExtraArgs: dict[str, Any]
        ) -> None:
            self.objects[(bucket, key)] = (stream.read(), dict(ExtraArgs["Metadata"]))

        def download_file(self, bucket: str, key: str, destination: str) -> None:
            Path(destination).write_bytes(self.objects[(bucket, key)][0])

        def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
            bucket = str(kwargs["Bucket"])
            prefix = str(kwargs["Prefix"])
            return {
                "IsTruncated": False,
                "Contents": [
                    {"Key": key}
                    for (item_bucket, key), _ in self.objects.items()
                    if item_bucket == bucket and key.startswith(prefix)
                ],
            }

        def delete_object(self, *, Bucket: str, Key: str) -> None:
            self.objects.pop((Bucket, Key), None)

    fake = FakeS3()
    store = S3ArtifactStore("results", "probe", client=fake)
    result = check_s3_storage.run_probe(
        fake,
        store,
        require_lifecycle_id=None,
        keep_object=False,
    )
    assert result["status"] == "passed"
    assert fake.objects == {}
    manifest = check_s3_storage.write_probe_evidence(result, tmp_path / "evidence")
    assert verify_manifest(manifest) == []
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "passed"


def test_s3_probe_reports_put_failure_without_raw_provider_diagnostics() -> None:
    class FailingS3:
        def upload_fileobj(
            self, _stream: Any, _bucket: str, _key: str, *, ExtraArgs: dict[str, Any]
        ) -> None:
            del ExtraArgs
            error = type("Denied", (Exception,), {})()
            error.response = {"Error": {"Code": "AccessDenied"}}
            raise error

    client = FailingS3()
    store = S3ArtifactStore("results", "probe", client=client)
    result = check_s3_storage.run_probe(
        client,
        store,
        require_lifecycle_id=None,
        keep_object=False,
    )

    assert result["status"] == "failed"
    assert result["checks"] == {"put": False}
    assert result["object_key"] is None
    assert result["errors"] == ["对象写入失败：Denied(AccessDenied)"]


def test_s3_probe_lists_paginated_prefix() -> None:
    class FakeS3:
        def __init__(self) -> None:
            self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}
            self.list_calls = 0

        def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
            content, metadata = self.objects[(Bucket, Key)]
            return {"ContentLength": len(content), "Metadata": metadata}

        def upload_fileobj(
            self, stream: Any, bucket: str, key: str, *, ExtraArgs: dict[str, Any]
        ) -> None:
            self.objects[(bucket, key)] = (stream.read(), dict(ExtraArgs["Metadata"]))

        def download_file(self, bucket: str, key: str, destination: str) -> None:
            Path(destination).write_bytes(self.objects[(bucket, key)][0])

        def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
            self.list_calls += 1
            prefix = str(kwargs["Prefix"])
            keys = [
                key
                for (bucket, key) in self.objects
                if bucket == str(kwargs["Bucket"]) and key.startswith(prefix)
            ]
            if self.list_calls == 1:
                return {
                    "IsTruncated": True,
                    "NextContinuationToken": "page-2",
                    "Contents": [{"Key": f"{prefix}unrelated"}],
                }
            assert kwargs["ContinuationToken"] == "page-2"
            return {"IsTruncated": False, "Contents": [{"Key": key} for key in keys]}

        def delete_object(self, *, Bucket: str, Key: str) -> None:
            self.objects.pop((Bucket, Key), None)

    fake = FakeS3()
    store = S3ArtifactStore("results", "probe", client=fake)
    result = check_s3_storage.run_probe(
        fake,
        store,
        require_lifecycle_id=None,
        keep_object=False,
    )

    assert result["status"] == "passed"
    assert fake.list_calls == 2


def test_local_artifact_pruning_keeps_referenced_objects(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database)
    job = store.submit("kept", False, config, max_queued=2)
    claimed = store.claim(1)
    assert claimed is not None
    assert store.register(job["job_id"], claimed["token"], 1, 1.0)
    assert store.finish(job["job_id"], claimed["token"], "succeeded", result={"ok": True})
    kept_digest = str(store.get(job["job_id"])["result_hash"])
    orphan_digest = store.artifacts.put_bytes(b"orphan")
    orphan_path = store.artifacts.path_for(orphan_digest)
    old = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(orphan_path, (old, old))

    candidates = store.prune_artifacts(older_than=time.time() - 86400)
    assert candidates == [orphan_digest]
    assert orphan_path.is_file()
    assert store.artifacts.path_for(kept_digest).is_file()

    assert store.prune_artifacts(older_than=time.time() - 86400, apply=True) == [orphan_digest]
    assert not orphan_path.exists()
    assert store.artifacts.path_for(kept_digest).is_file()


def test_artifact_pruning_rejects_active_jobs(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database)
    store.submit("active", False, config, max_queued=1)

    with pytest.raises(RuntimeError, match="未终态"):
        store.prune_artifacts(older_than=time.time() - 86400)


def test_s3_artifact_pruning_uses_age_and_reference_protection() -> None:
    digest_old = "a" * 64
    digest_recent = "b" * 64

    class FakeS3:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def list_objects_v2(self, **_kwargs: object) -> dict[str, object]:
            return {
                "IsTruncated": False,
                "Contents": [
                    {
                        "Key": f"mechagent/objects/aa/{digest_old[2:]}",
                        "LastModified": datetime.now(timezone.utc) - timedelta(days=10),
                    },
                    {
                        "Key": f"mechagent/objects/bb/{digest_recent[2:]}",
                        "LastModified": datetime.now(timezone.utc),
                    },
                ],
            }

        def delete_object(self, *, Bucket: str, Key: str) -> None:
            self.deleted.append(f"{Bucket}/{Key}")

    fake = FakeS3()
    store = S3ArtifactStore("results", client=fake)
    cutoff = datetime.now(timezone.utc).timestamp() - 86400

    assert store.prune_unreferenced({digest_recent}, older_than=cutoff) == [digest_old]
    assert fake.deleted == []
    assert store.prune_unreferenced({digest_recent}, older_than=cutoff, apply=True) == [digest_old]
    assert fake.deleted == [f"results/mechagent/objects/aa/{digest_old[2:]}"]


def test_studio_backup_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    store = JobStore(database)
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    job = store.submit("backup", False, config, max_queued=2)
    store.cancel(job["job_id"])
    backup = backup_studio(database, tmp_path / "backup")

    assert verify_backup(backup) == []
    assert not list(tmp_path.glob(".backup.*"))
    tampered = backup / "jobs.sqlite3"
    tampered.write_bytes(tampered.read_bytes() + b"tamper")
    assert verify_backup(backup)

    tampered.write_bytes((backup / "backup-manifest.json").read_bytes())
    with pytest.raises(ValueError, match="备份校验失败"):
        restore_studio(backup, tmp_path / "restored")

    clean_backup = tmp_path / "backup-clean"
    backup_studio(database, clean_backup)
    assert not list(tmp_path.glob(".backup-clean.*"))
    restored_database = restore_studio(clean_backup, tmp_path / "restored-clean")
    assert restored_database.is_file()
    assert JobStore(restored_database).get(job["job_id"])["request"] == "backup"


def test_studio_backup_stages_and_restores_referenced_external_objects(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    store = JobStore(database)
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    job = store.submit("remote backup", False, config, max_queued=2)
    claimed = store.claim(1)
    assert claimed is not None
    assert store.register(job["job_id"], claimed["token"], 1, 1.0)
    assert store.finish(job["job_id"], claimed["token"], "succeeded", result={"ok": True})
    digest = str(store.get(job["job_id"])["result_hash"])
    external = ArtifactStore(tmp_path / "external-objects")
    external.put_file(store.directory(job["job_id"]) / "result.json")

    backup = backup_studio(database, tmp_path / "external-backup", artifact_store=external)
    staged = backup / "objects" / digest[:2] / digest[2:]
    assert staged.is_file()
    target = ArtifactStore(tmp_path / "restored-objects")
    restored_database = restore_studio(
        backup,
        tmp_path / "external-restored",
        artifact_store=target,
    )

    assert target.verify(digest)
    restored_store = JobStore(restored_database, artifact_store=target)
    assert restored_store.payload(restored_store.get(job["job_id"]))["result"] == {"ok": True}


def test_studio_backup_round_trip_uses_s3_store_for_source_and_target(tmp_path: Path) -> None:
    class FakeS3:
        def __init__(self) -> None:
            self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}

        def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
            try:
                content, metadata = self.objects[(Bucket, Key)]
            except KeyError as exc:
                error = type("NotFound", (Exception,), {})()
                error.response = {"Error": {"Code": "404"}}
                raise error from exc
            return {"Metadata": metadata, "ContentLength": len(content)}

        def upload_file(
            self, source: str, bucket: str, key: str, *, ExtraArgs: dict[str, Any]
        ) -> None:
            self.objects[(bucket, key)] = (
                Path(source).read_bytes(),
                dict(ExtraArgs["Metadata"]),
            )

        def upload_fileobj(
            self, stream: Any, bucket: str, key: str, *, ExtraArgs: dict[str, Any]
        ) -> None:
            self.objects[(bucket, key)] = (stream.read(), dict(ExtraArgs["Metadata"]))

        def download_file(self, bucket: str, key: str, destination: str) -> None:
            Path(destination).write_bytes(self.objects[(bucket, key)][0])

    source_client = FakeS3()
    source_artifacts = S3ArtifactStore("source", "results", client=source_client)
    database = tmp_path / "studio" / "jobs.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database, artifact_store=source_artifacts)
    job = store.submit("s3 backup", False, config, max_queued=2)
    claimed = store.claim(1)
    assert claimed is not None
    assert store.register(job["job_id"], claimed["token"], 1, 1.0)
    assert store.finish(job["job_id"], claimed["token"], "succeeded", result={"ok": True})
    digest = str(store.get(job["job_id"])["result_hash"])

    backup = backup_studio(database, tmp_path / "s3-backup", artifact_store=source_artifacts)
    manifest = json.loads((backup / "backup-manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_backend"] == "s3"
    assert manifest["artifact_references"] == 1

    target_client = FakeS3()
    target_artifacts = S3ArtifactStore("target", "restored", client=target_client)
    restored_database = restore_studio(
        backup,
        tmp_path / "s3-restored",
        artifact_store=target_artifacts,
    )
    assert target_artifacts.verify(digest)
    restored_store = JobStore(restored_database, artifact_store=target_artifacts)
    assert restored_store.payload(restored_store.get(job["job_id"]))["result"] == {"ok": True}


def test_studio_backup_rejects_active_jobs_and_unlisted_files(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    store = JobStore(database)
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store.submit("active", False, config, max_queued=2)
    with pytest.raises(RuntimeError, match="未终态"):
        backup_studio(database, tmp_path / "active-backup")

    store.cancel(store.list_jobs()[0]["job_id"])
    backup = backup_studio(database, tmp_path / "backup-extra")
    (backup / "unexpected.bin").write_bytes(b"unexpected")
    assert any("未登记文件" in error for error in verify_backup(backup))


def test_job_store_enforces_project_active_quota(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database, max_active_jobs_per_project=1)
    store.submit("first", False, config, max_queued=10, project_id="project-a")

    with pytest.raises(ValueError, match="项目作业配额已满"):
        store.submit("second", False, config, max_queued=10, project_id="project-a")

    store.submit("other-project", False, config, max_queued=10, project_id="project-b")


def test_job_store_marks_oversized_result_failed(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database, max_result_bytes=1024)
    job = store.submit("large", False, config, max_queued=2)
    claimed = store.claim(1)
    assert claimed is not None
    assert store.register(job["job_id"], claimed["token"], 1, 1.0)
    assert store.finish(
        job["job_id"],
        claimed["token"],
        "succeeded",
        result={"payload": "x" * 2000},
    )

    finished = store.get(job["job_id"])
    assert finished["status"] == "failed"
    assert finished["error_code"] == "result_too_large"
    assert store.payload(finished)["result"] is None


def test_job_store_rejects_submission_over_storage_quota(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database, max_storage_bytes=1024)

    with pytest.raises(StorageQuotaError, match="存储配额"):
        store.submit("quota", False, config, max_queued=1)


def test_job_store_marks_success_failed_when_storage_quota_is_exceeded(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jobs.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database, max_storage_bytes=10 * 1024 * 1024)
    job = store.submit("quota-finish", False, config, max_queued=1)
    claimed = store.claim(1)
    assert claimed is not None
    assert store.register(job["job_id"], claimed["token"], 1, 1.0)
    store.max_storage_bytes = store.storage_usage_bytes() + 10
    run_dir = store.directory(job["job_id"]) / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "oversized.bin").write_bytes(b"x" * 100)

    assert store.finish(job["job_id"], claimed["token"], "succeeded", result={"ok": True})
    finished = store.get(job["job_id"])
    assert finished["status"] == "failed"
    assert finished["error_code"] == "storage_quota_exceeded"
    assert store.metrics()["storage"]["over_quota"] is True


def test_job_store_checks_storage_quota_after_result_write(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database, max_storage_bytes=10 * 1024 * 1024)
    job = store.submit("quota-result", False, config, max_queued=1)
    claimed = store.claim(1)
    assert claimed is not None
    assert store.register(job["job_id"], claimed["token"], 1, 1.0)
    store.max_storage_bytes = store.storage_usage_bytes() + 50

    assert store.finish(job["job_id"], claimed["token"], "succeeded", result={"value": "x" * 200})
    finished = store.get(job["job_id"])
    assert finished["status"] == "failed"
    assert finished["error_code"] == "storage_quota_exceeded"
    assert finished["result_hash"] is None
    assert not (store.directory(job["job_id"]) / "result.json").exists()


def test_job_store_counts_local_artifacts_outside_database_parent(tmp_path: Path) -> None:
    database = tmp_path / "studio" / "jobs.sqlite3"
    artifact_root = tmp_path / "objects"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database, artifact_root=artifact_root)
    (artifact_root / "objects" / "aa").mkdir(parents=True)
    (artifact_root / "objects" / "aa" / "payload").write_bytes(b"x" * 17)

    assert store.storage_usage_bytes() >= 17


def test_recovery_drill_records_rto_rpo_and_restores_jobs(tmp_path: Path) -> None:
    database = tmp_path / "studio" / "jobs.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database)
    job = store.submit("recovery", False, config, max_queued=2)
    store.cancel(job["job_id"])

    report = drill_studio_recovery.run_recovery_drill(
        database,
        tmp_path / "drill",
        rto_target_seconds=30,
        rpo_max_lost_jobs=0,
    )

    assert report["status"] == "passed"
    assert report["rpo"]["lost_jobs"] == 0
    assert report["source"]["job_count"] == report["restore"]["job_count"] == 1
    assert report["checks"] == {
        "source_integrity": True,
        "backup_manifest": True,
        "restored_integrity": True,
        "job_ids_preserved": True,
        "rto_within_target": True,
    }
    assert Path(report["report"]).is_file()
    assert not list((tmp_path / "drill").rglob("*.sqlite3-wal"))
    assert not list((tmp_path / "drill").rglob("*.sqlite3-shm"))


def test_recovery_drill_reports_failed_rto_without_hiding_evidence(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(database)
    job = store.submit("recovery", False, config, max_queued=2)
    store.cancel(job["job_id"])

    report = drill_studio_recovery.run_recovery_drill(
        database,
        tmp_path / "drill",
        rto_target_seconds=0,
        rpo_max_lost_jobs=0,
    )

    assert report["status"] == "failed"
    assert report["checks"]["rto_within_target"] is False
    assert report["rpo"]["lost_jobs"] == 0
    assert (tmp_path / "drill" / "recovery-drill.json").is_file()

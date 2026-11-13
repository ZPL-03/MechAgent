"""Studio SQLite 队列及其对象的可验证备份与恢复。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from mechagent.evidence import atomic_json, sha256
from mechagent.runtime.artifacts import ArtifactStore, S3ArtifactStore

BACKUP_SCHEMA_VERSION = 1


def backup_studio(
    database: Path,
    destination: Path,
    *,
    artifact_store: ArtifactStore | S3ArtifactStore | None = None,
) -> Path:
    """创建包含数据库、作业目录和结果对象的冷备份。

    ``artifact_store`` 为空时复制数据库同目录的本地对象；传入对象存储时，
    只下载数据库引用的 SHA-256 对象。恢复后的备份可以在另一台主机上传到
    目标对象存储，从而保留结果数据库引用和内容完整性。
    """

    database = database.resolve()
    if database.is_symlink() or not database.is_file():
        raise FileNotFoundError(database)
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(database)
    references: set[str] = set()
    try:
        active = source.execute(
            "SELECT job_id FROM jobs WHERE status IN "
            "('queued','starting','running','cancelling') LIMIT 1"
        ).fetchone()
        if active is not None:
            raise RuntimeError("存在未终态 Studio 作业，备份必须在调度器停止后执行。")
        references = {
            str(row[0]).strip().lower()
            for row in source.execute(
                "SELECT DISTINCT result_hash FROM jobs WHERE result_hash IS NOT NULL"
            ).fetchall()
        }
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        source.close()
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        backup_db = temporary / "jobs.sqlite3"
        source = sqlite3.connect(database)
        target_connection = sqlite3.connect(backup_db)
        try:
            source.backup(target_connection)
        finally:
            target_connection.close()
            source.close()
        root = database.parent
        for name in ("jobs",):
            source_dir = root / name
            if source_dir.is_dir():
                _reject_symlinks(source_dir)
                shutil.copytree(source_dir, temporary / name)
        if artifact_store is None:
            # JobStore passes ``<database-parent>/objects`` as the ArtifactStore
            # root; ArtifactStore stores content under its ``objects`` child.
            # Copy the content directory itself so the backup layout remains
            # ``objects/<prefix>/<digest>`` and matches explicit-store backups.
            source_dir = root / "objects" / "objects"
            if source_dir.is_dir():
                _reject_symlinks(source_dir)
                shutil.copytree(source_dir, temporary / "objects")
        else:
            for digest in sorted(references):
                target_path = temporary / "objects" / digest[:2] / digest[2:]
                artifact_store.get_file(digest, target_path)
        files = {
            path.relative_to(temporary).as_posix(): sha256(path)
            for path in temporary.rglob("*")
            if path.is_file()
        }
        atomic_json(
            temporary / "backup-manifest.json",
            {
                "schema_version": BACKUP_SCHEMA_VERSION,
                "artifact_backend": (
                    "s3" if isinstance(artifact_store, S3ArtifactStore) else "filesystem"
                ),
                "artifact_references": len(references),
                "files": files,
            },
        )
        shutil.copytree(temporary, destination)
    finally:
        # 连接已显式关闭；清理失败必须暴露，不能把一次性数据库留在证据目录旁。
        shutil.rmtree(temporary)
    return destination


def verify_backup(backup: Path) -> list[str]:
    """返回备份清单中的缺失或内容变化。"""

    if backup.is_symlink():
        return ["备份根目录不能是符号链接"]
    backup = backup.resolve()
    manifest_path = backup / "backup-manifest.json"
    if not manifest_path.is_file():
        return ["backup-manifest.json 缺失"]
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["backup-manifest.json 无法解析"]
    if payload.get("schema_version") != BACKUP_SCHEMA_VERSION:
        return ["不支持的备份版本"]
    errors: list[str] = []
    database = backup / "jobs.sqlite3"
    errors.extend(_verify_database(database, backup / "objects"))
    files = payload.get("files", {})
    if not isinstance(files, dict):
        return ["备份清单 files 必须是对象"]
    listed: set[str] = set()
    for relative, digest in files.items():
        if not isinstance(relative, str) or not isinstance(digest, str):
            errors.append("备份清单包含无效文件记录")
            continue
        path, path_error = _member_path(backup, relative)
        if path_error:
            errors.append(path_error)
            listed.add(relative)
            continue
        try:
            path.relative_to(backup)
        except ValueError:  # `_member_path` 已验证路径位于备份目录内。
            errors.append(f"非法备份路径：{relative}")
            listed.add(relative)
            continue
        if path.is_symlink():
            errors.append(f"备份文件不能是符号链接：{relative}")
            listed.add(relative)
            continue
        if not path.is_file():
            errors.append(f"文件缺失：{relative}")
        elif sha256(path) != digest:
            errors.append(f"文件摘要不匹配：{relative}")
        listed.add(relative)
    for path in backup.rglob("*"):
        if path.is_symlink():
            errors.append(f"备份包含符号链接：{path.relative_to(backup).as_posix()}")
            continue
        if not path.is_file() or path.name == "backup-manifest.json":
            continue
        relative = path.relative_to(backup).as_posix()
        if relative not in listed:
            errors.append(f"备份包含未登记文件：{relative}")
    return errors


def restore_studio(
    backup: Path,
    destination_root: Path,
    *,
    artifact_store: ArtifactStore | S3ArtifactStore | None = None,
) -> Path:
    """将已验证备份恢复到空的 Studio 根目录并可上传结果对象。"""

    errors = verify_backup(backup)
    if errors:
        raise ValueError("备份校验失败：" + "；".join(errors))
    destination_root = destination_root.resolve()
    if destination_root.is_symlink():
        raise FileExistsError("恢复目标不能是符号链接。")
    if destination_root.exists() and any(destination_root.iterdir()):
        raise FileExistsError("恢复目标必须为空目录。")
    destination_root.mkdir(parents=True, exist_ok=True)
    for name in ("jobs.sqlite3", "jobs"):
        source = backup / name
        if source.is_dir():
            shutil.copytree(source, destination_root / name)
        elif source.is_file():
            shutil.copy2(source, destination_root / name)
    source_objects = backup / "objects"
    if source_objects.is_dir():
        if artifact_store is None:
            # Match JobStore's default ArtifactStore(root=<database>/objects),
            # whose content directory is <database>/objects/objects.
            local_objects = destination_root / "objects" / "objects"
            local_objects.parent.mkdir(parents=True, exist_ok=True)
        else:
            local_objects = destination_root / "objects"
        shutil.copytree(source_objects, local_objects)
    else:
        local_objects = destination_root / "objects"
    restore_errors = _verify_database(destination_root / "jobs.sqlite3", local_objects)
    if restore_errors:
        raise ValueError("恢复数据库校验失败：" + "；".join(restore_errors))
    if artifact_store is not None:
        objects = destination_root / "objects"
        if objects.is_dir():
            for path in objects.rglob("*"):
                if not path.is_file() or len(path.relative_to(objects).parts) != 2:
                    continue
                digest = "".join(path.relative_to(objects).parts)
                if digest != sha256(path):
                    raise ValueError(f"恢复对象摘要不匹配：{digest}")
                uploaded = artifact_store.put_file(path)
                if uploaded != digest:
                    raise ValueError(f"恢复对象上传摘要不匹配：{digest}")
    return destination_root / "jobs.sqlite3"


def _member_path(backup: Path, relative: str) -> tuple[Path, str | None]:
    """解析清单成员并拒绝绝对路径、父目录跳转和符号链接。"""

    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts:
        return backup / candidate, f"非法备份路径：{relative}"
    path = backup.joinpath(candidate)
    try:
        path.resolve().relative_to(backup)
    except ValueError:
        return path, f"非法备份路径：{relative}"
    current = backup
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            return path, f"备份路径包含符号链接：{relative}"
    return path, None


def _reject_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"Studio 数据目录包含符号链接，拒绝备份: {path}")


def _verify_database(database: Path, objects: Path) -> list[str]:
    """校验 SQLite 完整性并确认数据库引用的对象已经随备份保存。"""

    if not database.is_file():
        return ["jobs.sqlite3 缺失"]
    errors: list[str] = []
    try:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                errors.append("jobs.sqlite3 完整性检查失败")
            rows = connection.execute(
                "SELECT DISTINCT result_hash FROM jobs WHERE result_hash IS NOT NULL"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return [f"jobs.sqlite3 无法读取：{exc}"]
    for row in rows:
        digest = str(row[0]).strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            errors.append("jobs.sqlite3 包含无效结果对象摘要")
            continue
        object_path = objects / digest[:2] / digest[2:]
        if not object_path.is_file() or sha256(object_path) != digest:
            errors.append(f"结果对象缺失或摘要不匹配：{digest}")
    return errors

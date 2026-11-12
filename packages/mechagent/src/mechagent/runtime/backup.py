"""Studio SQLite 队列及其对象的可验证备份与恢复。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from mechagent.evidence import atomic_json, sha256

BACKUP_SCHEMA_VERSION = 1


def backup_studio(database: Path, destination: Path) -> Path:
    """创建包含数据库、作业目录和内容寻址对象的冷备份。"""

    database = database.resolve()
    if database.is_symlink() or not database.is_file():
        raise FileNotFoundError(database)
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(database)
    try:
        active = source.execute(
            "SELECT job_id FROM jobs WHERE status IN "
            "('queued','starting','running','cancelling') LIMIT 1"
        ).fetchone()
        if active is not None:
            raise RuntimeError("存在未终态 Studio 作业，备份必须在调度器停止后执行。")
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        source.close()
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        backup_db = temporary / "jobs.sqlite3"
        source = sqlite3.connect(database)
        target = sqlite3.connect(backup_db)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        root = database.parent
        for name in ("jobs", "objects"):
            source_dir = root / name
            if source_dir.is_dir():
                _reject_symlinks(source_dir)
                shutil.copytree(source_dir, temporary / name)
        files = {
            path.relative_to(temporary).as_posix(): sha256(path)
            for path in temporary.rglob("*")
            if path.is_file()
        }
        atomic_json(
            temporary / "backup-manifest.json",
            {"schema_version": BACKUP_SCHEMA_VERSION, "files": files},
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
        except ValueError:  # 防御性检查，_member_path 已覆盖该分支。
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


def restore_studio(backup: Path, destination_root: Path) -> Path:
    """将已验证备份恢复到空的 Studio 根目录。"""

    errors = verify_backup(backup)
    if errors:
        raise ValueError("备份校验失败：" + "；".join(errors))
    destination_root = destination_root.resolve()
    if destination_root.is_symlink():
        raise FileExistsError("恢复目标不能是符号链接。")
    if destination_root.exists() and any(destination_root.iterdir()):
        raise FileExistsError("恢复目标必须为空目录。")
    destination_root.mkdir(parents=True, exist_ok=True)
    for name in ("jobs.sqlite3", "jobs", "objects"):
        source = backup / name
        if source.is_dir():
            shutil.copytree(source, destination_root / name)
        elif source.is_file():
            shutil.copy2(source, destination_root / name)
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

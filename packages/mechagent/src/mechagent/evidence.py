"""运行证据清单与完整性校验。哈希证明文件完整性，不证明物理正确性。"""

from __future__ import annotations

import hashlib
import json
import math
import ntpath
import os
import platform
import posixpath
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from uuid import uuid4

from mechagent.redaction import redact_sensitive_text


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_records(
    directory: Path, *, manifest_name: str = "manifest.json"
) -> list[dict[str, Any]]:
    """列出目录内可复核文件的相对路径、大小和 SHA-256。"""

    if directory.is_symlink():
        raise ValueError(f"证据目录不能是符号链接: {directory}")
    root = directory.resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.name == manifest_name
            or _is_sqlite_journal(path)
        ):
            continue
        if not path.resolve().is_relative_to(root):
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return records


def stable_artifact_records(
    directory: Path,
    *,
    attempts: int = 20,
    interval_seconds: float = 0.25,
) -> list[dict[str, Any]]:
    """等待证据目录稳定且没有活动求解锁后返回文件清单。"""

    if attempts < 2:
        raise ValueError("证据稳定性检查至少需要两次快照。")
    if interval_seconds <= 0.0 or not math.isfinite(interval_seconds):
        raise ValueError("证据稳定性检查间隔必须为正数。")
    root = directory.resolve()
    previous: list[dict[str, Any]] | None = None
    current: list[dict[str, Any]] = []
    for index in range(attempts):
        current = artifact_records(root)
        locks = [path for path in root.rglob("*.lck") if path.is_file()]
        if not locks and previous == current:
            return current
        previous = current
        if index + 1 < attempts:
            time.sleep(interval_seconds)
    if locks:
        raise RuntimeError("证据目录仍存在活动求解锁，无法生成稳定清单。")
    raise RuntimeError("证据目录在限定时间内未稳定，无法生成清单。")


def _is_sqlite_journal(path: Path) -> bool:
    """SQLite WAL and shared-memory files are transient and not backup objects."""

    return path.name.endswith(("-wal", "-shm"))


_PUBLIC_PATH_KEYS = frozenset(
    {
        "artifact_root",
        "config",
        "config_path",
        "database",
        "field_json",
        "input_file",
        "license_queue_path",
        "manifest_path",
        "mesh_file",
        "odb",
        "output_dir",
        "python_executable",
        "report_path",
        "solver_path",
        "source_path",
        "work_dir",
    }
)


def public_value(
    value: Any,
    secrets: tuple[str, ...] = (),
    *,
    sanitize_paths: bool = False,
    _path_context: bool = False,
) -> Any:
    """递归脱敏公开结构，并按需移除本机文件路径。"""
    if isinstance(value, str):
        if sanitize_paths and _path_context:
            return redact_sensitive_text(portable_public_path(value), extra_secrets=secrets)
        return redact_sensitive_text(value, extra_secrets=secrets)
    if isinstance(value, Path):
        return portable_public_path(value) if sanitize_paths else str(value)
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            key_name = str(key)
            is_path = sanitize_paths and (
                key_name in _PUBLIC_PATH_KEYS or (key_name == "path" and _path_context)
            )
            child_path_context = sanitize_paths and key_name in {
                "artifacts",
                "output_files",
            }
            result[key] = (
                public_value(
                    portable_public_path(item),
                    secrets,
                    sanitize_paths=sanitize_paths,
                    _path_context=True,
                )
                if is_path
                else public_value(
                    item,
                    secrets,
                    sanitize_paths=sanitize_paths,
                    _path_context=child_path_context,
                )
            )
        return result
    if isinstance(value, (list, tuple)):
        return [
            public_value(
                item,
                secrets,
                sanitize_paths=sanitize_paths,
                _path_context=_path_context,
            )
            for item in value
        ]
    return value


def portable_public_path(value: Any) -> Any:
    """将绝对路径或父目录跳转转换为文件名，保留安全的相对 POSIX 路径。"""

    if isinstance(value, (list, tuple)):
        return [portable_public_path(item) for item in value]
    if isinstance(value, Path):
        raw = value.as_posix()
    elif isinstance(value, str):
        raw = value
    else:
        return value
    normalized = raw.replace("\\", "/")
    if _is_absolute_path(raw, normalized) or ".." in Path(normalized).parts:
        return ntpath.basename(raw) or posixpath.basename(normalized) or normalized
    return normalized


def _is_absolute_path(raw: str, normalized: str) -> bool:
    return (
        ntpath.isabs(raw)
        or posixpath.isabs(normalized)
        or bool(ntpath.splitdrive(raw)[0])
        or normalized.startswith("//")
    )


def write_manifest(directory: Path, *, status: str, details: dict[str, Any]) -> Path:
    root = directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    # 不跟随目录外的符号链接，也不纳入原始日志和 LLM trace 内容。
    artifacts = [
        item for item in artifact_records(root) if not str(item["path"]).endswith((".tmp", ".log"))
    ]
    packages = {}
    for name in ("mechagent", "mechagent-core", "gmsh", "pydantic", "langgraph"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "unknown"
    path = root / "manifest.json"
    atomic_json(
        path,
        {
            "schema_version": 1,
            "status": status,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": packages,
            "details": public_value(details),
            "artifacts": artifacts,
        },
    )
    return path


def verify_manifest(path: Path) -> list[str]:
    """返回缺失、越界或哈希不匹配的证据项；无错误时返回空列表。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("不支持的证据清单版本。")
    root = path.parent.resolve()
    errors = []
    seen = set()
    for item in payload["artifacts"]:
        relative = item["path"]
        candidate = root / relative
        if (
            relative in seen
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or candidate.is_symlink()
            or not candidate.resolve().is_relative_to(root)
        ):
            errors.append(f"invalid_path: {relative}")
        elif not candidate.is_file():
            errors.append(f"missing: {relative}")
        elif candidate.stat().st_size != item["size"] or sha256(candidate) != item["sha256"]:
            errors.append(f"hash_mismatch: {relative}")
        seen.add(relative)
    for candidate in root.rglob("*"):
        if (
            candidate.is_symlink()
            or not candidate.is_file()
            or candidate.name == path.name
            or candidate.name.endswith((".tmp", ".log"))
            or _is_sqlite_journal(candidate)
        ):
            continue
        relative = candidate.relative_to(root).as_posix()
        if relative not in seen:
            errors.append(f"unlisted: {relative}")
    return errors

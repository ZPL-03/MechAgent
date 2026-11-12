"""运行证据清单与完整性校验。哈希证明文件完整性，不证明物理正确性。"""

from __future__ import annotations

import hashlib
import json
import os
import platform
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
        if path.is_symlink() or not path.is_file() or path.name == manifest_name:
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


def public_value(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    """对公开结构中的文本递归脱敏。"""
    if isinstance(value, str):
        return redact_sensitive_text(value, extra_secrets=secrets)
    if isinstance(value, dict):
        return {key: public_value(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_value(item, secrets) for item in value]
    return value


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
        ):
            continue
        relative = candidate.relative_to(root).as_posix()
        if relative not in seen:
            errors.append(f"unlisted: {relative}")
    return errors

"""运行证据清单与完整性校验。哈希证明文件完整性，不证明物理正确性。"""

from __future__ import annotations

import hashlib
import json
import math
import ntpath
import os
import platform
import posixpath
import re
import shutil
import subprocess
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from uuid import uuid4

from mechagent.redaction import redact_sensitive_text

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_PROVENANCE_SCHEMA = "mechagent.evidence-provenance.v1"


def runtime_provenance(
    *,
    root: Path | None = None,
    config_paths: dict[str, Path] | None = None,
    tool_commands: dict[str, str | Path | tuple[str, ...]] | None = None,
    tool_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构建不包含本机路径或凭据的运行 provenance。

    `config_paths` 只记录文件相对仓库根目录的安全路径、大小和摘要；
    `tool_commands` 仅使用 `--version` 读取首行版本文本，并把可执行文件
    归一为文件名。调用方可以用 `tool_versions` 提供已由适配器确认的版本。

    provenance 绑定源提交、脏状态、运行时、配置摘要和工具版本。它不证明
    结果的物理正确性、作者身份或签名有效性。
    """

    repository = _find_repository_root(root)
    source = {
        "git_commit": _git_value(repository, "rev-parse", "HEAD"),
        "git_dirty": _git_dirty(repository),
    }
    configs = _config_records(repository, config_paths or {})
    tools = _tool_records(tool_commands or {}, tool_versions or {})
    return {
        "schema": _PROVENANCE_SCHEMA,
        "source": source,
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "packages": _package_versions(),
        "configs": configs,
        "tools": tools,
    }


def _find_repository_root(start: Path | None) -> Path | None:
    candidates: list[Path] = []
    if start is not None:
        candidates.append(start)
    candidates.extend((Path.cwd(), Path(__file__).resolve()))
    for candidate in candidates:
        resolved = candidate.resolve()
        for directory in (resolved, *resolved.parents):
            marker = directory / ".git"
            if marker.is_dir() or marker.is_file():
                return directory
    return None


def _git_value(root: Path | None, *arguments: str) -> str:
    if root is None:
        return "unknown"
    executable = shutil.which("git")
    if executable is None:
        return "unknown"
    try:
        completed = subprocess.run(
            [executable, "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unknown"
    value = completed.stdout.strip()
    if arguments == ("rev-parse", "HEAD") and not _GIT_COMMIT.fullmatch(value):
        return "unknown"
    return value or "unknown"


def _git_dirty(root: Path | None) -> bool | str:
    if root is None:
        return "unknown"
    executable = shutil.which("git")
    if executable is None:
        return "unknown"
    try:
        completed = subprocess.run(
            [executable, "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unknown"
    return bool(completed.stdout.strip())


def _package_versions() -> dict[str, str]:
    packages: dict[str, str] = {}
    for name in ("mechagent", "mechagent-core", "gmsh", "pydantic", "langgraph"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "unknown"
    return packages


def _config_records(root: Path | None, paths: dict[str, Path]) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for name, raw_path in sorted(paths.items()):
        path = Path(raw_path)
        if path.is_symlink() or not path.is_file():
            records[name] = {"path": _safe_path(root, path), "status": "missing"}
            continue
        records[name] = {
            "path": _safe_path(root, path),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
    return records


def _safe_path(root: Path | None, path: Path) -> str:
    if root is not None:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return path.name or "unknown"


def _tool_records(
    commands: dict[str, str | Path | tuple[str, ...]], versions: dict[str, str]
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for name in sorted(set(commands) | set(versions)):
        command = commands.get(name)
        if name in versions:
            value = versions[name]
            executable = _command_name(command)
        elif command is not None:
            value = _command_version(command)
            executable = _command_name(command)
        else:
            value = "unknown"
            executable = "unknown"
        records[name] = {"executable": executable, "version": value}
    return records


def _command_name(command: str | Path | tuple[str, ...] | None) -> str:
    if command is None:
        return "unknown"
    if isinstance(command, tuple):
        first = command[0]
    else:
        raw = str(command)
        first = raw if Path(raw).is_file() else raw.split()[0]
    return ntpath.basename(first) or posixpath.basename(first) or "unknown"


def _command_version(command: str | Path | tuple[str, ...]) -> str:
    parts = list(command) if isinstance(command, tuple) else [str(command)]
    if _command_name(command).lower() not in {
        "git",
        "git.exe",
        "node",
        "node.exe",
        "python",
        "python.exe",
    }:
        return "unavailable"
    executable = shutil.which(parts[0]) or (
        str(Path(parts[0])) if Path(parts[0]).is_file() else None
    )
    if executable is None:
        return "unavailable"
    try:
        completed = subprocess.run(
            [executable, *parts[1:], "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "unavailable"
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return redact_sensitive_text(output[0]) if output else "unknown"


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
        "abaqus",
        "calculix",
        "config",
        "config_path",
        "database",
        "field_json",
        "file",
        "input_file",
        "launcher",
        "license_queue_path",
        "manifest_path",
        "mesh_file",
        "odb",
        "output_dir",
        "python_executable",
        "report_path",
        "source",
        "executable",
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


def write_manifest(
    directory: Path,
    *,
    status: str,
    details: dict[str, Any],
    provenance: dict[str, Any] | None = None,
    config_paths: dict[str, Path] | None = None,
    tool_commands: dict[str, str | Path | tuple[str, ...]] | None = None,
    tool_versions: dict[str, str] | None = None,
) -> Path:
    root = directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    # 不跟随目录外的符号链接，也不纳入原始日志和 LLM trace 内容。
    artifacts = [
        item for item in artifact_records(root) if not str(item["path"]).endswith((".tmp", ".log"))
    ]
    runtime = provenance or runtime_provenance(
        config_paths=config_paths,
        tool_commands=tool_commands,
        tool_versions=tool_versions,
    )
    packages = runtime["packages"]
    path = root / "manifest.json"
    atomic_json(
        path,
        {
            "schema_version": 1,
            "status": status,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": packages,
            "provenance": runtime,
            "details": public_value(details, sanitize_paths=True),
            "artifacts": artifacts,
        },
    )
    return path


def verify_manifest(path: Path, *, require_provenance: bool = False) -> list[str]:
    """返回缺失、越界或哈希不匹配的证据项；无错误时返回空列表。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("不支持的证据清单版本。")
    root = path.parent.resolve()
    errors = []
    if "provenance" in payload:
        errors.extend(_validate_provenance(payload["provenance"]))
    elif require_provenance:
        errors.append("missing_provenance")
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


def _validate_provenance(value: object) -> list[str]:
    if not isinstance(value, dict) or value.get("schema") != _PROVENANCE_SCHEMA:
        return ["invalid_provenance: schema"]
    errors: list[str] = []
    source = value.get("source")
    if not isinstance(source, dict):
        errors.append("invalid_provenance: source")
    else:
        commit = source.get("git_commit")
        if commit != "unknown" and (
            not isinstance(commit, str) or not _GIT_COMMIT.fullmatch(commit)
        ):
            errors.append("invalid_provenance: source.git_commit")
        if source.get("git_dirty") not in (True, False, "unknown"):
            errors.append("invalid_provenance: source.git_dirty")
    runtime = value.get("runtime")
    if not isinstance(runtime, dict) or not all(
        isinstance(runtime.get(key), str) and runtime[key]
        for key in ("python", "implementation", "platform")
    ):
        errors.append("invalid_provenance: runtime")
    packages = value.get("packages")
    if not isinstance(packages, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in packages.items()
    ):
        errors.append("invalid_provenance: packages")
    configs = value.get("configs")
    if not isinstance(configs, dict):
        errors.append("invalid_provenance: configs")
    else:
        for name, record in configs.items():
            if not isinstance(name, str) or not isinstance(record, dict):
                errors.append(f"invalid_provenance: configs.{name}")
                continue
            path = record.get("path")
            if not isinstance(path, str) or _unsafe_provenance_path(path):
                errors.append(f"invalid_provenance: configs.{name}.path")
            digest = record.get("sha256")
            if digest is not None and (
                not isinstance(digest, str) or not _SHA256.fullmatch(digest)
            ):
                errors.append(f"invalid_provenance: configs.{name}.sha256")
    tools = value.get("tools")
    if not isinstance(tools, dict):
        errors.append("invalid_provenance: tools")
    else:
        for name, record in tools.items():
            if not isinstance(name, str) or not isinstance(record, dict):
                errors.append(f"invalid_provenance: tools.{name}")
                continue
            if not isinstance(record.get("executable"), str) or not isinstance(
                record.get("version"), str
            ):
                errors.append(f"invalid_provenance: tools.{name}")
    return errors


def _unsafe_provenance_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return _is_absolute_path(value, normalized) or ".." in Path(normalized).parts or not normalized

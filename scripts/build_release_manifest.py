"""生成发布构建产物的版本、大小和 SHA-256 清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_VERSION_PATTERN = re.compile(r"^version\s*=\s*[\"']([^\"']+)[\"']\s*$", re.MULTILINE)


def build_document(root: Path) -> dict[str, Any]:
    """校验并记录当前构建输出。"""

    versions = {
        "mechagent-core": _project_version(root / "packages" / "mechagent-core" / "pyproject.toml"),
        "mechagent": _project_version(root / "packages" / "mechagent" / "pyproject.toml"),
    }
    if versions["mechagent"] != versions["mechagent-core"]:
        raise ValueError("mechagent 与 mechagent-core 的版本必须一致。")

    artifact_paths = [
        *_package_artifacts(root, "mechagent-core", versions["mechagent-core"]),
        *_package_artifacts(root, "mechagent", versions["mechagent"]),
    ]
    sbom = root / "dist" / "mechagent-sbom.spdx.json"
    if not sbom.is_file():
        raise FileNotFoundError(f"缺少 SBOM：{sbom}")
    artifact_paths.append(sbom)
    audit_report = root / "dist" / "mechagent-python-runtime-audit.json"
    if audit_report.is_file():
        artifact_paths.append(audit_report)

    artifacts = [_artifact_record(root, path) for path in artifact_paths]
    return {
        "schemaVersion": "mechagent.release-manifest.v1",
        "project": "MechAgent",
        "version": versions["mechagent"],
        "gitCommit": _git_commit(root),
        "created": _created_at(),
        "provenance": _provenance(root),
        "artifacts": artifacts,
    }


def _project_version(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"缺少包配置：{path}")
    match = _VERSION_PATTERN.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"无法读取包版本：{path}")
    return match.group(1)


def _package_artifacts(root: Path, distribution: str, version: str) -> list[Path]:
    dist_dir = root / "packages" / distribution / "dist"
    normalized = distribution.replace("-", "_")
    wheel_matches = sorted(dist_dir.glob(f"{normalized}-{version}-*.whl"))
    sdist_matches = sorted(dist_dir.glob(f"{normalized}-{version}.tar.gz"))
    if len(wheel_matches) != 1:
        raise FileNotFoundError(
            f"{dist_dir} 下 {distribution} wheel 数量必须为 1，当前为 {len(wheel_matches)}。"
        )
    if len(sdist_matches) != 1:
        raise FileNotFoundError(
            f"{dist_dir} 下 {distribution} sdist 数量必须为 1，当前为 {len(sdist_matches)}。"
        )
    return [wheel_matches[0], sdist_matches[0]]


def _artifact_record(root: Path, path: Path) -> dict[str, Any]:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"构建产物不在仓库内：{resolved_path}")
    return {
        "path": resolved_path.relative_to(resolved_root).as_posix(),
        "size": resolved_path.stat().st_size,
        "sha256": _sha256(resolved_path),
        "mediaType": _media_type(resolved_path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_type(path: Path) -> str:
    if path.name.endswith(".tar.gz"):
        return "application/gzip"
    if path.suffix == ".whl":
        return "application/zip"
    if path.suffix == ".json":
        return "application/json"
    return "application/octet-stream"


def _git_commit(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _git_dirty(root: Path) -> bool | str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return bool(completed.stdout.strip())


def _command_version(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            [*command, "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return output[0] if output else "unknown"


def _provenance(root: Path) -> dict[str, Any]:
    """记录可复核的构建上下文，不宣称签名或可信构建者身份。"""

    return {
        "schemaVersion": "mechagent.build-provenance.v1",
        "source": {
            "gitCommit": _git_commit(root),
            "gitDirty": _git_dirty(root),
        },
        "builder": {
            "pythonVersion": platform.python_version(),
            "pythonImplementation": platform.python_implementation(),
            "platform": platform.platform(),
            "nodeVersion": _command_version(["node"]),
        },
        "reproducibility": {
            "sourceDateEpoch": os.environ.get("SOURCE_DATE_EPOCH") or None,
        },
    }


def _created_at() -> str:
    raw_epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if raw_epoch:
        try:
            created = datetime.fromtimestamp(int(raw_epoch), timezone.utc)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("SOURCE_DATE_EPOCH 必须是有效的 Unix 时间戳。") from exc
    else:
        created = datetime.now(timezone.utc)
    return created.isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=ROOT, help="项目根目录，默认使用脚本所在仓库。"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/mechagent-release-manifest.json"),
        help="清单路径。",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_document(root), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

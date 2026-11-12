"""清理仓库内可再生成产物，保护跟踪文件与求解锁。"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from argparse import ArgumentParser
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--include-runs", action="store_true", help="同时删除运行证据与 FEM 产物")
    args = parser.parse_args(argv)
    tracked = _tracked_paths()
    patterns = [
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".backup.*",
        ".restore.*",
        "*.egg-info",
        "build",
        "dist",
    ]
    targets = [path for pattern in patterns for path in _iter_repo_paths(pattern) if path.is_dir()]
    targets.extend(
        REPO_ROOT / name
        for name in (
            ".tmp",
            ".playwright-cli",
            ".playwright-mcp",
            "output/playwright",
            "apps/mechagent-studio/node_modules",
            "knowledge/external",
            "knowledge/index.jsonl",
            "site",
        )
    )
    if args.include_runs:
        for database in _iter_repo_paths("*.sqlite3"):
            with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
                has_jobs = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
                ).fetchone()
                if (
                    has_jobs
                    and connection.execute(
                        "SELECT 1 FROM jobs WHERE status IN "
                        "('queued','starting','running','cancelling') LIMIT 1"
                    ).fetchone()
                ):
                    raise RuntimeError(f"作业数据库存在非终态任务，拒绝删除运行证据: {database}")
        locks = list(_iter_repo_paths("*.lck"))
        if locks:
            raise RuntimeError(f"存在求解锁，请核实作业状态后处理锁文件: {locks[0]}")
        targets.append(REPO_ROOT / "mechagent_output")
        targets.extend(
            path
            for pattern in ("*.frd", "*.dat", "*.sta", "*.msg")
            for path in _iter_repo_paths(pattern)
            if path.is_file()
        )
    # 在任何删除发生前验证全部目标，避免部分清理后才发现越界。
    removable = []
    for path in targets:
        _ensure_inside_repo(path)
        if any(item == path or path in item.parents for item in tracked):
            continue
        if path.is_dir() and next(path.rglob("*.lck"), None) is not None:
            raise RuntimeError(f"清理目标内存在求解锁: {path}")
        removable.append(path)
    for path in sorted(set(removable), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    for name in ("knowledge/raw", "knowledge/external", "knowledge", "output"):
        path = REPO_ROOT / name
        if path.is_dir() and not any(path.iterdir()) and path not in tracked:
            _ensure_inside_repo(path)
            path.rmdir()
    return 0


def _tracked_paths() -> set[Path]:
    if not (REPO_ROOT / ".git").exists():
        return set()
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"], capture_output=True, check=True
    )
    return {REPO_ROOT / name for name in result.stdout.decode("utf-8").split("\0") if name}


def _iter_repo_paths(pattern: str) -> Iterator[Path]:
    paths = REPO_ROOT.rglob(pattern)
    while True:
        try:
            yield next(paths)
        except (StopIteration, FileNotFoundError):
            return


def _ensure_inside_repo(path: Path) -> None:
    resolved_root = REPO_ROOT.resolve()
    resolved_path = path.resolve()
    if resolved_path == resolved_root or not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"清理路径不在仓库子目录内: {resolved_path}")


if __name__ == "__main__":
    raise SystemExit(main())

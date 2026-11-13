"""清理仓库内可再生成产物，保护跟踪文件与求解锁。

默认只处理能够由项目工具重新生成的缓存和构建产物。正式运行证据、FEM
文件和 Studio 正式证据目录需要显式选择对应选项；``--dry-run`` 可在删除
前列出精确目标。删除失败时返回非零状态，并报告失败路径、已删除目标数量
和可直接执行的 PowerShell 命令。
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from argparse import ArgumentParser
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--include-runs", action="store_true", help="同时删除运行证据与 FEM 产物")
    parser.add_argument(
        "--include-studio-runtime",
        action="store_true",
        help="删除 mechagent_output/.studio 运行时数据库和作业目录",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出待删除路径，不修改文件系统",
    )
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
        ".cache",
        ".tox",
        ".nox",
        "htmlcov",
        "coverage",
    ]
    targets = [path for pattern in patterns for path in _iter_repo_paths(pattern) if path.is_dir()]
    file_patterns = [
        ".coverage",
        ".coverage.*",
        "coverage.xml",
        ".eslintcache",
        ".stylelintcache",
        "*.tsbuildinfo",
        "*.pyc",
        "*.pyo",
        ".DS_Store",
        "Thumbs.db",
        "npm-debug.log*",
        "yarn-debug.log*",
        "yarn-error.log*",
        "pnpm-debug.log*",
        ".upload.*.tmp",
        ".tmp.*",
        "*.swp",
        "*.swo",
    ]
    targets.extend(
        path for pattern in file_patterns for path in _iter_repo_paths(pattern) if path.is_file()
    )
    targets.extend(
        REPO_ROOT / name
        for name in (
            ".tmp",
            ".playwright-cli",
            ".playwright-mcp",
            "output/playwright",
            "apps/mechagent-studio/node_modules",
            "apps/mechagent-studio/.vite",
            "apps/mechagent-studio/coverage",
            "knowledge/external",
            "knowledge/index.jsonl",
            "site",
            ".coverage",
            "coverage.xml",
        )
    )
    if args.include_runs or args.include_studio_runtime:
        for database in _iter_repo_paths("*.sqlite3"):
            try:
                with closing(
                    sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
                ) as connection:
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
                        raise RuntimeError(
                            f"作业数据库存在非终态任务，拒绝删除运行证据: {database}"
                        )
            except sqlite3.DatabaseError as exc:
                raise RuntimeError(f"无法读取作业数据库，拒绝删除相关运行目录: {database}") from exc
        locks = list(_iter_repo_paths("*.lck"))
        if locks:
            raise RuntimeError(f"存在求解锁，请核实作业状态后处理锁文件: {locks[0]}")
    if args.include_studio_runtime:
        targets.append(REPO_ROOT / "mechagent_output" / ".studio")
    if args.include_runs:
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
        if not path.exists():
            continue
        if any(item == path or path in item.parents for item in tracked):
            continue
        if path.is_dir() and next(path.rglob("*.lck"), None) is not None:
            raise RuntimeError(f"清理目标内存在求解锁: {path}")
        removable.append(path)
    ordered = sorted(set(removable), key=lambda item: len(item.parts), reverse=True)
    if args.dry_run:
        for path in ordered:
            print(path)
    else:
        deleted_count = 0
        for path in ordered:
            try:
                _remove_path(path)
            except OSError as exc:
                print(
                    f"清理失败：{path}\n"
                    f"已删除目标数量：{deleted_count}\n"
                    f"错误：{exc}\n"
                    f"可执行命令：{_powershell_remove_command(path)}",
                    file=sys.stderr,
                )
                return 1
            deleted_count += 1
        for name in ("knowledge/raw", "knowledge/external", "knowledge", "output"):
            path = REPO_ROOT / name
            if path.is_dir() and not any(path.iterdir()) and path not in tracked:
                _ensure_inside_repo(path)
                try:
                    path.rmdir()
                except OSError as exc:
                    print(
                        f"清理失败：{path}\n"
                        f"已删除目标数量：{deleted_count}\n"
                        f"错误：{exc}\n"
                        f"可执行命令：{_powershell_remove_command(path)}",
                        file=sys.stderr,
                    )
                    return 1
                deleted_count += 1
    return 0


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _powershell_remove_command(path: Path) -> str:
    literal = str(path).replace("'", "''")
    suffix = " -Recurse" if path.is_dir() else ""
    return f"Remove-Item -LiteralPath '{literal}'{suffix} -Force"


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

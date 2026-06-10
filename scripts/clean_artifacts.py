"""清理项目缓存和 FEM 临时产物。"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """清理可再生成文件。

    Args:
        无。

    Returns:
        int: 清理完成返回 0。

    Raises:
        OSError: 当文件系统操作失败时抛出。

    Example:
        >>> isinstance(main(), int)
        True
    """

    directory_patterns = [
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "*.egg-info",
        "build",
        "dist",
    ]
    file_patterns = [
        "*.frd",
        "*.dat",
        "*.sta",
        "*.lck",
        "*.msg",
    ]
    fixed_paths = [
        REPO_ROOT / ".playwright-cli",
        REPO_ROOT / ".playwright-mcp",
        REPO_ROOT / "mechagent_output",
        REPO_ROOT / "output/playwright",
        REPO_ROOT / "apps/mechagent-studio/node_modules",
        REPO_ROOT / "knowledge/external",
        REPO_ROOT / "knowledge/index.jsonl",
        REPO_ROOT / "site",
    ]
    empty_directories = [
        REPO_ROOT / "knowledge/raw",
        REPO_ROOT / "knowledge/external",
        REPO_ROOT / "knowledge",
        REPO_ROOT / "output",
    ]
    for pattern in directory_patterns:
        for path in _iter_repo_paths(pattern):
            if path.is_dir():
                _remove_dir(path)
    for pattern in file_patterns:
        for path in _iter_repo_paths(pattern):
            if path.is_file():
                _remove_file(path)
    for path in fixed_paths:
        if path.is_dir():
            _remove_dir(path)
        elif path.is_file():
            _remove_file(path)
    for path in empty_directories:
        _remove_dir_if_empty(path)
    return 0


def _iter_repo_paths(pattern: str) -> Iterator[Path]:
    paths = REPO_ROOT.rglob(pattern)
    while True:
        try:
            yield next(paths)
        except StopIteration:
            return
        except FileNotFoundError:
            return


def _remove_dir(path: Path) -> None:
    _ensure_inside_repo(path)
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return


def _remove_file(path: Path) -> None:
    _ensure_inside_repo(path)
    path.unlink(missing_ok=True)


def _remove_dir_if_empty(path: Path) -> None:
    try:
        if path.is_dir() and not any(path.iterdir()):
            _ensure_inside_repo(path)
            path.rmdir()
    except FileNotFoundError:
        return


def _ensure_inside_repo(path: Path) -> None:
    resolved_root = REPO_ROOT.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        msg = f"清理路径不在仓库目录内: {resolved_path}"
        raise ValueError(msg)


if __name__ == "__main__":
    raise SystemExit(main())

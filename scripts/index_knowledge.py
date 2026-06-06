"""构建本地知识库 JSONL 索引。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "packages" / "mechagent-core" / "src"
APP_SRC = ROOT / "packages" / "mechagent" / "src"
for src in (str(CORE_SRC), str(APP_SRC)):
    if src not in sys.path:
        sys.path.insert(0, src)

from mechagent import MechAgent  # noqa: E402
from mechagent.knowledge import build_index  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """创建本地 JSONL 检索索引。

    Args:
        argv: 命令行参数。

    Returns:
        int: 目录存在后返回 0。

    Raises:
        OSError: 当目录无法创建时抛出。

    Example:
        >>> isinstance(main([]), int)
        True
    """

    parser = argparse.ArgumentParser(description="构建 MechAgent 本地知识库索引。")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/mechagent.yaml"),
        help="配置文件路径。",
    )
    parser.add_argument("--source", type=Path, default=None, help="标准化知识文件目录。")
    parser.add_argument("--index", type=Path, default=None, help="JSONL 索引路径。")
    parser.add_argument("--chunk-size", type=int, default=None, help="文本块最大字符数。")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="相邻文本块重叠字符数。")
    args = parser.parse_args(argv)

    knowledge = MechAgent.from_config(args.config).config.knowledge
    source = args.source or knowledge.external_dir
    index_path = args.index or knowledge.index_path
    chunk_size = args.chunk_size or knowledge.chunk_size
    chunk_overlap = (
        args.chunk_overlap if args.chunk_overlap is not None else knowledge.chunk_overlap
    )
    count = build_index(
        source,
        index_path,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    print(json.dumps({"chunks": count, "index": str(index_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

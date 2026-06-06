"""将知识源文件标准化为 Markdown 与 JSON。"""

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
from mechagent.knowledge import standardize_documents  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """按配置标准化知识源目录中的文件。

    Args:
        argv: 命令行参数。

    Returns:
        int: 成功返回 0。

    Raises:
        OSError: 当目录读取或文件写入失败时抛出。

    Example:
        >>> isinstance(main([]), int)
        True
    """

    parser = argparse.ArgumentParser(description="构建 MechAgent 外部知识库标准化产物。")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/mechagent.yaml"),
        help="配置文件路径。",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="知识源目录；默认使用配置中的 knowledge.raw_dir。",
    )
    parser.add_argument("--output", type=Path, default=None, help="标准化产物目录。")
    args = parser.parse_args(argv)

    knowledge = MechAgent.from_config(args.config).config.knowledge
    source = args.source or knowledge.raw_dir
    output = args.output or knowledge.external_dir
    count = standardize_documents(source, output)
    print(json.dumps({"documents": count, "output": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

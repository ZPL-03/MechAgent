"""知识库文档标准化。"""

from __future__ import annotations

import json
from pathlib import Path

from mechagent.core.paths import safe_file_stem


def standardize_documents(source_dir: Path, output_dir: Path) -> int:
    """将 Markdown、TXT、JSON 文件标准化到输出目录。

    Args:
        source_dir: 知识源文件目录。
        output_dir: 标准化产物目录。

    Returns:
        int: 标准化文档数量。

    Raises:
        FileNotFoundError: 当知识源目录不存在时抛出。
        ValueError: 当知识源目录不包含可索引文档时抛出。
        OSError: 当文件读写失败时抛出。
        json.JSONDecodeError: 当 JSON 文档无法解析时抛出。

    Example:
        >>> standardize_documents(Path("knowledge/sources"), Path("knowledge/external"))
        2
    """

    if not source_dir.exists():
        raise FileNotFoundError(source_dir)
    documents = sorted(_iter_documents(source_dir))
    if not documents:
        msg = f"知识源目录不包含可标准化文档: {source_dir}"
        raise ValueError(msg)
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    used_stems: set[str] = set()
    for path in documents:
        stem = _unique_stem(_safe_stem(path.relative_to(source_dir)), used_stems)
        suffix = path.suffix.lower()
        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            json_path = output_dir / f"{stem}.json"
            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            markdown = (
                f"# {stem}\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n"
            )
        else:
            text = path.read_text(encoding="utf-8")
            markdown = text if suffix == ".md" else f"# {stem}\n\n{text.strip()}\n"
        (output_dir / f"{stem}.md").write_text(markdown, encoding="utf-8")
        count += 1
    return count


def _iter_documents(source_dir: Path) -> list[Path]:
    suffixes = {".md", ".txt", ".json"}
    return [
        path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() in suffixes
    ]


def _safe_stem(path: Path) -> str:
    raw = "_".join(part for part in path.with_suffix("").parts if part not in {".", ".."})
    return safe_file_stem(raw, "document")


def _unique_stem(stem: str, used_stems: set[str]) -> str:
    if stem not in used_stems:
        used_stems.add(stem)
        return stem
    index = 2
    while f"{stem}_{index}" in used_stems:
        index += 1
    unique = f"{stem}_{index}"
    used_stems.add(unique)
    return unique

"""文件路径辅助函数。"""

from __future__ import annotations

import re

_SAFE_STEM_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_file_stem(value: str, fallback: str) -> str:
    """生成安全的文件名主干。

    Args:
        value: 原始名称。
        fallback: 原始名称为空或不可用时的名称。

    Returns:
        str: 不包含路径分隔符的文件名主干。

    Raises:
        ValueError: 当 fallback 为空时抛出。

    Example:
        >>> safe_file_stem("../STATIC CASE", "run")
        'STATIC_CASE'
    """

    if not fallback.strip():
        msg = "fallback 不能为空。"
        raise ValueError(msg)
    normalized = value.strip().replace("\\", "_").replace("/", "_")
    stem = _SAFE_STEM_PATTERN.sub("_", normalized).strip("._-")
    if not stem:
        return _fallback_stem(fallback)
    return stem[:120]


def _fallback_stem(fallback: str) -> str:
    normalized = fallback.strip().replace("\\", "_").replace("/", "_")
    stem = _SAFE_STEM_PATTERN.sub("_", normalized).strip("._-")
    if not stem:
        msg = "fallback 必须包含可用于文件名的字符。"
        raise ValueError(msg)
    return stem[:120]

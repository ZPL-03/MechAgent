"""LLM JSON 响应解析工具。"""

from __future__ import annotations

import json
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    """从 LLM 响应中解析 JSON 对象。

    Args:
        text: LLM 响应文本。

    Returns:
        dict[str, Any]: JSON 对象。

    Raises:
        ValueError: 当响应中不存在 JSON 对象或对象无法解析时抛出。

    Example:
        >>> parse_json_object('```json\\n{"ok": true}\\n```')["ok"]
        True
    """

    content = text.strip()
    if not content:
        msg = "LLM 响应为空。"
        raise ValueError(msg)
    for candidate in _json_candidates(content):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    msg = "LLM 响应中未找到可解析的 JSON 对象。"
    raise ValueError(msg)


def _json_candidates(text: str) -> list[str]:
    candidates = [_strip_fence(text), text]
    balanced = _first_balanced_object(text)
    if balanced is not None:
        candidates.insert(0, balanced)
    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def _strip_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if len(lines) >= 3 and lines[0].lstrip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text.strip()


def _first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None

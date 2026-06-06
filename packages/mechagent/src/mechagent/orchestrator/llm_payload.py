"""Agent advisory payload 清洗工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mechagent.redaction import redact_sensitive_text

_TRACE_KEYS = {"agent", "used", "prompt", "response", "error"}


def advisory_payload(value: Any) -> str:
    """生成可发送给 LLM advisory 的公开上下文文本。"""

    return json.dumps(_scrub(value), ensure_ascii=False, sort_keys=True, default=str)


def _scrub(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _scrub(value.model_dump(mode="json"))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        if _looks_like_trace(value):
            return _public_trace(value)
        return {str(key): _scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    return value


def _looks_like_trace(value: dict[Any, Any]) -> bool:
    keys = {str(key) for key in value}
    return {"agent", "used"}.issubset(keys) and bool({"prompt", "response"} & keys)


def _public_trace(value: dict[Any, Any]) -> dict[str, Any]:
    prompt = str(value.get("prompt", ""))
    response = str(value.get("response", ""))
    error = value.get("error")
    return {
        "agent": value.get("agent", ""),
        "used": _trace_bool(value.get("used")),
        "error": redact_sensitive_text(str(error)) if error is not None else None,
        "prompt_chars": len(prompt),
        "response_chars": len(response),
    }


def _trace_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    return False

"""LLM 响应解析测试。"""

from __future__ import annotations

import pytest

from mechagent.llm.backends import _extract_message_content
from mechagent.orchestrator.llm_json import parse_json_object


def test_extract_message_content_prefers_content() -> None:
    response = {"choices": [{"message": {"content": "OK", "reasoning_content": "reasoning"}}]}

    assert _extract_message_content(response) == "OK"


def test_extract_message_content_accepts_reasoning_content() -> None:
    response = {"choices": [{"message": {"content": "", "reasoning_content": "reasoning"}}]}

    assert _extract_message_content(response) == "reasoning"


def test_extract_message_content_rejects_missing_message() -> None:
    with pytest.raises(RuntimeError):
        _extract_message_content({"choices": []})


def test_parse_json_object_accepts_fenced_llm_output() -> None:
    payload = parse_json_object('```json\n{"capability_id": "structural_static"}\n```')

    assert payload["capability_id"] == "structural_static"

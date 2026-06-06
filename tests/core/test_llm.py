"""LLM 后端测试。"""

from __future__ import annotations

import sys
import warnings
from typing import Any

import httpx
import pytest
from pytest import MonkeyPatch

import mechagent.llm.backends as backends
from mechagent.llm.backends import LLMConfig, check_connection, completion


def test_llm_health_reports_success(monkeypatch: MonkeyPatch) -> None:
    def fake_completion(prompt: str, config: LLMConfig) -> str:
        assert "ok" in prompt
        assert config.api_key == "key"
        return "ok"

    monkeypatch.setattr(backends, "completion", fake_completion)

    health = check_connection(
        LLMConfig(base_url="https://example.com/v1", api_key="key", model="m")
    )

    assert health.ok is True


def test_llm_health_reports_completion_error(monkeypatch: MonkeyPatch) -> None:
    def fake_completion(prompt: str, config: LLMConfig) -> str:
        _ = (prompt, config)
        raise RuntimeError("HTTP 401")

    monkeypatch.setattr(backends, "completion", fake_completion)

    health = check_connection(
        LLMConfig(base_url="https://example.com/v1", api_key="key", model="m")
    )

    assert health.ok is False
    assert "HTTP 401" in health.message


def test_llm_health_reports_missing_config() -> None:
    health = check_connection(LLMConfig(base_url="", api_key="", model=""))

    assert health.ok is False


def test_llm_health_rejects_empty_completion(monkeypatch: MonkeyPatch) -> None:
    def fake_completion(prompt: str, config: LLMConfig) -> str:
        _ = (prompt, config)
        return ""

    monkeypatch.setattr(backends, "completion", fake_completion)

    health = check_connection(
        LLMConfig(base_url="https://example.com/v1", api_key="key", model="m")
    )

    assert health.ok is False
    assert "空响应" in health.message


def test_completion_rejects_empty_prompt_before_provider() -> None:
    with pytest.raises(RuntimeError, match="prompt"):
        completion(
            "   ",
            LLMConfig(base_url="https://example.com/v1", api_key="key", model="model"),
        )


def test_completion_rejects_missing_config_before_provider() -> None:
    with pytest.raises(RuntimeError, match="LLM 配置缺少"):
        completion("prompt", LLMConfig(base_url="", api_key="", model=""))


class _FakeHTTPResponse:
    def __init__(
        self,
        status_code: int,
        payload: object | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("invalid json")
        return self._payload


def test_http_completion_sends_json_mode_payload_and_returns_content(
    monkeypatch: MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> _FakeHTTPResponse:
        requests.append({"url": url, **kwargs})
        print("provider stdout noise")
        print("provider stderr noise", file=sys.stderr)
        return _FakeHTTPResponse(
            200,
            {"choices": [{"message": {"content": "ok"}}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    content = backends._http_chat_completion(
        "prompt",
        LLMConfig(base_url="https://example.com/v1", api_key="key", model="model"),
    )

    assert content == "ok"
    assert requests[0]["url"] == "https://example.com/v1/chat/completions"
    assert requests[0]["headers"] == {
        "Authorization": "Bearer key",
        "Content-Type": "application/json",
    }
    payload = requests[0]["json"]
    assert isinstance(payload, dict)
    assert payload["response_format"] == {"type": "json_object"}


def test_http_completion_falls_back_when_json_mode_is_not_supported(
    monkeypatch: MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> _FakeHTTPResponse:
        requests.append({"url": url, **kwargs})
        if len(requests) == 1:
            return _FakeHTTPResponse(400, {"error": "bad"}, "response_format unsupported")
        return _FakeHTTPResponse(
            200,
            {"choices": [{"message": {"content": "ok"}}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    content = backends._http_chat_completion(
        "prompt",
        LLMConfig(base_url="https://example.com/v1", api_key="key", model="model"),
    )

    assert content == "ok"
    first_payload = requests[0]["json"]
    second_payload = requests[1]["json"]
    assert isinstance(first_payload, dict)
    assert isinstance(second_payload, dict)
    assert "response_format" in first_payload
    assert "response_format" not in second_payload


def test_http_completion_does_not_mutate_global_warning_filters(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_post(url: str, **kwargs: Any) -> _FakeHTTPResponse:
        _ = (url, kwargs)
        return _FakeHTTPResponse(
            200,
            {"choices": [{"message": {"content": "ok"}}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    before = list(warnings.filters)

    content = backends._http_chat_completion(
        "prompt",
        LLMConfig(base_url="https://example.com/v1", api_key="key", model="model"),
    )

    assert content == "ok"
    assert warnings.filters == before


def test_http_completion_redacts_api_key_in_provider_errors(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_post(url: str, **kwargs: Any) -> _FakeHTTPResponse:
        _ = (url, kwargs)
        return _FakeHTTPResponse(
            401,
            {"error": "bad"},
            (
                "request failed with key sk-test-secret, "
                "tp-provider-secret-123456, Bearer provider.token and "
                "https://example.com?api_key=query-secret"
            ),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(RuntimeError) as exc_info:
        backends._http_chat_completion(
            "prompt",
            LLMConfig(
                base_url="https://example.com/v1",
                api_key="sk-test-secret",
                model="model",
            ),
        )

    assert "sk-test-secret" not in str(exc_info.value)
    assert "tp-provider-secret-123456" not in str(exc_info.value)
    assert "provider.token" not in str(exc_info.value)
    assert "query-secret" not in str(exc_info.value)
    assert "key ***" in str(exc_info.value)
    assert "tp-***" in str(exc_info.value)
    assert "Bearer ***" in str(exc_info.value)
    assert "api_key=***" in str(exc_info.value)


def test_llm_health_redacts_secrets_from_completion_errors(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_KEY", "sk-env-health-secret")

    def fake_completion(prompt: str, config: LLMConfig) -> str:
        _ = (prompt, config)
        raise RuntimeError("provider failed with sk-env-health-secret and Bearer health.token")

    monkeypatch.setattr(backends, "completion", fake_completion)

    health = check_connection(
        LLMConfig(base_url="https://example.com/v1", api_key="key", model="m")
    )

    assert health.ok is False
    assert "sk-env-health-secret" not in health.message
    assert "health.token" not in health.message
    assert "Bearer ***" in health.message

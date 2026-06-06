"""OpenAI 兼容 Chat Completions 后端封装。"""

from __future__ import annotations

import math
import os
from typing import Any, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mechagent.redaction import redact_sensitive_text


class LLMConfig(BaseModel):
    """LLM 调用配置。

    Args:
        base_url: OpenAI 兼容接口地址。
        api_key: 接口密钥。
        model: 模型名称。
        temperature: 采样温度。

    Returns:
        LLMConfig: 经过校验的 LLM 配置。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> LLMConfig(base_url="https://example.com/v1", api_key="x", model="demo")
        LLMConfig(...)
    """

    model_config = ConfigDict(extra="forbid")

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = Field(default=0.1, ge=0, le=2)

    @field_validator("temperature")
    @classmethod
    def _temperature_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "llm.temperature 必须是有限数值。"
            raise ValueError(msg)
        return value

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """从环境变量读取 LLM 配置。

        Args:
            无。

        Returns:
            LLMConfig: LLM 配置。

        Raises:
            pydantic.ValidationError: 当环境变量缺失时抛出。

        Example:
            >>> isinstance(LLMConfig.from_env(), LLMConfig)
            True
        """

        return cls(
            base_url=os.environ.get("URL", ""),
            api_key=os.environ.get("API_KEY", ""),
            model=os.environ.get("MODEL_NAME", ""),
        )


class LLMHealth(BaseModel):
    """LLM 连接健康状态。

    Args:
        ok: 连接是否成功。
        status_code: HTTP 状态码。
        message: 诊断信息。

    Returns:
        LLMHealth: LLM 健康检查结果。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> LLMHealth(ok=True, status_code=200, message="ok")
        LLMHealth(ok=True, status_code=200, message='ok')
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    status_code: int = 0
    message: str


def completion(prompt: str, config: Optional[LLMConfig] = None) -> str:
    """调用 OpenAI 兼容 Chat Completions 接口。

    Args:
        prompt: 用户提示词。
        config: LLM 配置，缺省时读取环境变量。

    Returns:
        str: 模型输出文本。

    Raises:
        RuntimeError: 当 HTTP 调用失败或响应格式异常时抛出。

    Example:
        >>> config = LLMConfig(base_url="https://example.com/v1", api_key="x", model="demo")
        >>> completion("返回 ok", config)
        'ok'
    """

    if not prompt.strip():
        msg = "prompt 不能为空。"
        raise RuntimeError(msg)
    active_config = config or LLMConfig.from_env()
    if not active_config.base_url or not active_config.api_key or not active_config.model:
        msg = "LLM 配置缺少 base_url、api_key 或 model。"
        raise RuntimeError(msg)
    return _http_chat_completion(prompt, active_config)


def check_connection(config: Optional[LLMConfig] = None) -> LLMHealth:
    """检查 OpenAI 兼容 Chat Completions 接口是否可访问。

    Args:
        config: LLM 配置，缺省时读取环境变量。

    Returns:
        LLMHealth: 连接健康状态。

    Raises:
        无。

    Example:
        >>> check_connection(LLMConfig(base_url="https://example.com/v1", api_key="x", model="m"))
        LLMHealth(...)
    """

    active_config = config or LLMConfig.from_env()
    if not active_config.base_url or not active_config.api_key or not active_config.model:
        return LLMHealth(ok=False, message="LLM 配置缺少 base_url、api_key 或 model。")
    try:
        content = completion("请只输出 ok。", active_config)
    except RuntimeError as exc:
        return LLMHealth(
            ok=False, message=f"LLM 连接失败: {_redact_secret(str(exc), active_config)}"
        )
    if not content.strip():
        return LLMHealth(ok=False, message="LLM 返回空响应。")
    return LLMHealth(ok=True, status_code=200, message="LLM Chat Completions 调用正常。")


class _LLMHTTPError(RuntimeError):
    def __init__(self, message: str, status_code: int, body: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _http_chat_completion(prompt: str, config: LLMConfig) -> str:
    try:
        response = _completion_with_json_mode(prompt, config)
    except Exception as exc:
        msg = f"LLM 调用失败: {_redact_secret(str(exc), config)}"
        raise RuntimeError(msg) from exc
    return _extract_message_content(response)


def _completion_with_json_mode(prompt: str, config: LLMConfig) -> dict[str, Any]:
    try:
        return _post_chat_completion(prompt, config, use_json_mode=True)
    except _LLMHTTPError as exc:
        if "response_format" not in exc.body.lower():
            raise
        return _post_chat_completion(prompt, config, use_json_mode=False)


def _post_chat_completion(prompt: str, config: LLMConfig, *, use_json_mode: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": config.temperature,
        "max_tokens": 4096,
    }
    if use_json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = httpx.post(
            _chat_completions_url(config.base_url),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60.0,
        )
    except httpx.RequestError as exc:
        msg = f"LLM 网络请求失败: {exc}"
        raise RuntimeError(msg) from exc

    if response.status_code >= 400:
        body = _redact_secret(response.text, config)
        msg = f"HTTP {response.status_code}: {body}"
        raise _LLMHTTPError(msg, response.status_code, body)
    try:
        data = response.json()
    except ValueError as exc:
        msg = "LLM 响应不是 JSON。"
        raise RuntimeError(msg) from exc
    if not isinstance(data, dict):
        msg = "LLM 响应 JSON 必须是对象。"
        raise RuntimeError(msg)
    return data


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _redact_secret(message: str, config: LLMConfig) -> str:
    return redact_sensitive_text(message, extra_secrets=(config.api_key,))


def _extract_message_content(response: Any) -> str:
    try:
        choices = _message_get(response, "choices")
        message = _message_get(choices[0], "message")
    except (KeyError, IndexError, TypeError) as exc:
        msg = "LLM 响应缺少 choices[0].message。"
        raise RuntimeError(msg) from exc
    if message is None:
        msg = "LLM 响应缺少 choices[0].message。"
        raise RuntimeError(msg)

    content = _message_get(message, "content")
    if content:
        return str(content)
    reasoning_content = _message_get(message, "reasoning_content")
    if reasoning_content:
        return str(reasoning_content)
    msg = "LLM 响应缺少 content 和 reasoning_content。"
    raise RuntimeError(msg)


def _message_get(message: Any, key: str) -> Any:
    if isinstance(message, dict):
        return message.get(key)
    return getattr(message, key, None)

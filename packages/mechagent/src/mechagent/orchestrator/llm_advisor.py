"""Agent 级 LLM 辅助与审计 trace。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from mechagent.config import MechAgentConfig
from mechagent.llm import LLMConfig, completion
from mechagent.redaction import redact_sensitive_text

_ADVISORY_TIMEOUT_SECONDS = 8.0
_ADVISORY_MAX_ATTEMPTS = 1


class AgentLLMTrace(BaseModel):
    """Agent 调用 LLM 的审计记录。

    Args:
        agent: Agent 名称。
        used: 是否发起 LLM 调用。
        prompt: 发送给 LLM 的提示词。
        response: LLM 响应文本。
        error: 调用错误。

    Returns:
        AgentLLMTrace: LLM 调用审计记录。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> AgentLLMTrace(agent="Planner", used=False)
        AgentLLMTrace(...)
    """

    model_config = ConfigDict(extra="forbid")

    agent: str
    used: bool
    prompt: str = ""
    response: str = ""
    error: Optional[str] = None


class AgentLLMAdvisor:
    """面向 Agent 的 LLM 辅助接口。

    Args:
        config: 全局配置。

    Returns:
        AgentLLMAdvisor: LLM 辅助器。

    Raises:
        无。

    Example:
        >>> AgentLLMAdvisor(MechAgentConfig()).advise("Planner", "request").used
        False
    """

    def __init__(self, config: Optional[MechAgentConfig]) -> None:
        self.config = config

    def advise(self, agent: str, task: str, payload: str) -> AgentLLMTrace:
        """调用 LLM 生成 Agent 工程审阅输出。

        Args:
            agent: Agent 名称。
            task: Agent 任务说明。
            payload: 结构化或自然语言上下文。

        Returns:
            AgentLLMTrace: 调用审计记录。

        Raises:
            无。

        Example:
            >>> AgentLLMAdvisor(None).advise("Planner", "x", "y").used
            False
        """

        return self.complete(
            agent,
            task,
            payload,
            "只输出 JSON 对象，字段包括 assessment、missing_fields、risks、recommended_action。",
            timeout_seconds=_ADVISORY_TIMEOUT_SECONDS,
            max_attempts=_ADVISORY_MAX_ATTEMPTS,
        )

    def complete(
        self,
        agent: str,
        task: str,
        payload: str,
        output_contract: str,
        *,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
    ) -> AgentLLMTrace:
        """调用 LLM 并按指定输出契约记录 trace。

        Args:
            agent: Agent 名称。
            task: Agent 任务说明。
            payload: 结构化或自然语言上下文。
            output_contract: 输出 JSON 契约说明。

        Returns:
            AgentLLMTrace: 调用审计记录。

        Raises:
            无。

        Example:
            >>> AgentLLMAdvisor(None).complete("Planner", "x", "y", "{}").used
            False
        """

        if self.config is None or not self.config.orchestrator.use_llm_agents:
            return AgentLLMTrace(agent=agent, used=False)
        settings = self.config.llm
        if not settings.base_url or not settings.api_key or not settings.model:
            return AgentLLMTrace(agent=agent, used=False)

        prompt = _build_prompt(agent, task, payload, output_contract)
        llm_config = LLMConfig(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            temperature=settings.temperature,
        )
        llm_config = LLMConfig(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            temperature=settings.temperature,
            timeout_seconds=timeout_seconds
            if timeout_seconds is not None
            else llm_config.timeout_seconds,
            max_attempts=max_attempts if max_attempts is not None else llm_config.max_attempts,
        )
        try:
            response = completion(
                prompt,
                llm_config,
            )
        except Exception as exc:
            return AgentLLMTrace(
                agent=agent,
                used=True,
                prompt=prompt,
                error=_redact_trace_error(str(exc), settings.api_key),
            )
        return AgentLLMTrace(agent=agent, used=True, prompt=prompt, response=response)


def _build_prompt(agent: str, task: str, payload: str, output_contract: str) -> str:
    return (
        "你是 MechAgent 多智能体框架中的一个工程 Agent。"
        "只输出简洁 JSON，不输出 Markdown。"
        f"输出契约: {output_contract}"
        f"\nAgent: {agent}\n任务: {task}\n上下文:\n{payload}"
    )


def _redact_trace_error(message: str, api_key: str) -> str:
    return redact_sensitive_text(message, extra_secrets=(api_key,))

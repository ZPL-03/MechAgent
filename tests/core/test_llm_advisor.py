"""Agent LLM 辅助器测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mechagent.config import LLMSettings, MechAgentConfig, OrchestratorSettings
from mechagent.llm.backends import LLMConfig
from mechagent.orchestrator.agents import AnalystAgent, PostProcAgent, ReporterAgent
from mechagent.orchestrator.llm_advisor import AgentLLMAdvisor, AgentLLMTrace
from mechagent.orchestrator.llm_payload import advisory_payload
from mechagent.orchestrator.models import (
    PostProcessingSummary,
    SolverRunSummary,
    TaskItem,
    TaskRunRecord,
)


def _llm_enabled_config() -> MechAgentConfig:
    return MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )


def test_llm_advisor_is_disabled_by_policy() -> None:
    config = MechAgentConfig(orchestrator=OrchestratorSettings(use_llm_agents=False))

    trace = AgentLLMAdvisor(config).advise("Planner", "task", "payload")

    assert trace.agent == "Planner"
    assert trace.used is False


def test_llm_advisor_is_disabled_without_credentials() -> None:
    trace = AgentLLMAdvisor(MechAgentConfig()).advise("Planner", "task", "payload")

    assert trace.used is False


def test_llm_advisor_records_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )

    def _raise_runtime_error(*_args: object, **_kwargs: object) -> str:
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", _raise_runtime_error)

    trace = AgentLLMAdvisor(config).advise("Planner", "task", "payload")

    assert trace.used is True
    assert trace.error == "boom"


def test_llm_advisor_uses_short_policy_for_advisory_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, LLMConfig] = {}

    def fake_completion(_prompt: str, config: LLMConfig) -> str:
        captured["config"] = config
        return "{}"

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)

    trace = AgentLLMAdvisor(_llm_enabled_config()).advise("MeshAgent", "task", "payload")

    assert trace.used is True
    assert captured["config"].timeout_seconds == 8.0
    assert captured["config"].max_attempts == 1


def test_llm_advisor_keeps_default_policy_for_structured_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, LLMConfig] = {}

    def fake_completion(_prompt: str, config: LLMConfig) -> str:
        captured["config"] = config
        return "{}"

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)

    trace = AgentLLMAdvisor(_llm_enabled_config()).complete(
        "Designer",
        "task",
        "payload",
        "{}",
    )

    assert trace.used is True
    assert captured["config"].timeout_seconds == 60.0
    assert captured["config"].max_attempts == 3


def test_llm_advisor_records_provider_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _llm_enabled_config()

    def _raise_value_error(*_args: object, **_kwargs: object) -> str:
        msg = "provider schema error"
        raise ValueError(msg)

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", _raise_value_error)

    trace = AgentLLMAdvisor(config).advise("Designer", "task", "payload")

    assert trace.used is True
    assert trace.error == "provider schema error"


def test_llm_advisor_redacts_secrets_from_trace_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(
            base_url="https://example.com/v1",
            api_key="sk-agent-secret",
            model="demo",
        ),
    )
    monkeypatch.setenv("API_KEY", "sk-env-secret")

    def _raise_secret_error(*_args: object, **_kwargs: object) -> str:
        msg = "provider failed with sk-agent-secret and sk-env-secret"
        raise RuntimeError(msg)

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", _raise_secret_error)

    trace = AgentLLMAdvisor(config).advise("Planner", "task", "payload")

    assert trace.used is True
    assert trace.error == "provider failed with *** and ***"


def test_advisory_payload_redacts_nested_trace_text() -> None:
    payload = advisory_payload(
        {
            "solver_llm_trace": {
                "agent": "SolverAgent",
                "used": True,
                "prompt": "private solver prompt",
                "response": "private solver response",
                "error": None,
            }
        }
    )

    assert "private solver prompt" not in payload
    assert "private solver response" not in payload
    assert '"prompt_chars": 21' in payload
    assert '"response_chars": 23' in payload


def test_advisory_payload_redacts_partial_trace_mapping() -> None:
    payload = advisory_payload(
        {
            "plugin_trace": {
                "agent": "PluginAgent",
                "used": "true",
                "prompt": "partial private prompt",
            }
        }
    )

    assert "partial private prompt" not in payload
    assert '"agent": "PluginAgent"' in payload
    assert '"prompt_chars": 22' in payload
    assert '"response_chars": 0' in payload


def test_advisory_payload_does_not_treat_false_text_as_trace_used() -> None:
    payload = advisory_payload(
        {
            "plugin_trace": {
                "agent": "PluginAgent",
                "used": "false",
                "response": "partial private response",
            }
        }
    )

    assert "partial private response" not in payload
    assert '"used": false' in payload


def test_advisory_payload_redacts_sensitive_tokens_from_trace_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_KEY", "sk-env-payload-secret")
    payload = advisory_payload(
        {
            "plugin_trace": {
                "agent": "PluginAgent",
                "used": True,
                "prompt": "private prompt",
                "error": (
                    "provider failed with sk-env-payload-secret, "
                    "sk-payload-secret-123456, Bearer payload.token and "
                    "https://example.com?access_token=query-secret"
                ),
            }
        }
    )

    assert "sk-env-payload-secret" not in payload
    assert "sk-payload-secret-123456" not in payload
    assert "payload.token" not in payload
    assert "query-secret" not in payload
    assert "sk-***" in payload
    assert "Bearer ***" in payload
    assert "access_token=***" in payload


def test_postproc_advisory_payload_excludes_solver_trace_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_completion(prompt: str, _config: object) -> str:
        captured["prompt"] = prompt
        return "{}"

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    solver_summary = SolverRunSummary(
        success=True,
        solver_llm_trace=_private_trace("SolverAgent"),
    )

    PostProcAgent(tmp_path, _llm_enabled_config()).summarize(solver_summary)

    assert "private SolverAgent prompt" not in captured["prompt"]
    assert "private SolverAgent response" not in captured["prompt"]
    assert "prompt_chars" in captured["prompt"]


def test_analyst_advisory_payload_excludes_prior_trace_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_completion(prompt: str, _config: object) -> str:
        captured["prompt"] = prompt
        return "{}"

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    task = TaskItem(
        task_id="TASK_1",
        case_id="STATIC-STRUCTURAL",
        title="结构静力分析",
        planner_llm_trace=_private_trace("Planner"),
    )
    post_summary = PostProcessingSummary(
        success=True,
        postproc_llm_trace=_private_trace("PostProcAgent"),
    )

    AnalystAgent(_llm_enabled_config()).analyze(task, post_summary)

    assert "private Planner prompt" not in captured["prompt"]
    assert "private PostProcAgent response" not in captured["prompt"]
    assert "prompt_chars" in captured["prompt"]


def test_reporter_advisory_payload_excludes_planner_trace_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_completion(prompt: str, _config: object) -> str:
        captured["prompt"] = prompt
        return "{}"

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    record = TaskRunRecord(
        task=TaskItem(
            task_id="TASK_1",
            case_id="STATIC-STRUCTURAL",
            title="结构静力分析",
            planner_llm_trace=_private_trace("Planner"),
        )
    )

    ReporterAgent(_llm_enabled_config()).render([record])

    assert "private Planner prompt" not in captured["prompt"]
    assert "private Planner response" not in captured["prompt"]
    assert "prompt_chars" not in captured["prompt"]
    assert "report_scope" in captured["prompt"]


def _private_trace(agent: str) -> AgentLLMTrace:
    return AgentLLMTrace(
        agent=agent,
        used=True,
        prompt=f"private {agent} prompt",
        response=f"private {agent} response",
    )

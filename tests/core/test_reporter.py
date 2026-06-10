"""报告生成测试。"""

from __future__ import annotations

import pytest

from mechagent.config import LLMSettings, MechAgentConfig, OrchestratorSettings
from mechagent.orchestrator.agents import ReporterAgent
from mechagent.orchestrator.llm_advisor import AgentLLMTrace
from mechagent.orchestrator.models import (
    ErrorRecord,
    PostProcessingSummary,
    SolverRunSummary,
    TaskItem,
    TaskRunRecord,
)


def test_reporter_marks_missing_reference_values_as_not_available() -> None:
    record = TaskRunRecord(
        task=TaskItem(task_id="TASK_1", case_id="STATIC-STRUCTURAL", title="结构静力分析"),
        solver_result=SolverRunSummary(
            success=True,
            passed=True,
            model_case_id="STATIC-CUSTOM",
            quantity="max_displacement",
            unit="mm",
            predicted=2.5,
            solver="calculix",
        ),
    )

    report = ReporterAgent().render([record])

    assert (
        "| TASK_1 | STATIC-CUSTOM | max_displacement (mm) | 2.5 | N/A | N/A | N/A | 未验证 |"
    ) in report


def test_reporter_uses_quantity_field_when_predicted_is_not_explicit() -> None:
    record = TaskRunRecord(
        task=TaskItem(task_id="TASK_1", case_id="UNIT-CUSTOM", title="自定义能力"),
        solver_result=SolverRunSummary.from_mapping(
            {
                "success": True,
                "model_case_id": "UNIT-CUSTOM",
                "quantity": "custom_metric",
                "custom_metric": 42.0,
                "unit": "mm",
            }
        ),
    )

    report = ReporterAgent().render([record])

    assert "| TASK_1 | UNIT-CUSTOM | custom_metric (mm) | 42 | N/A | N/A | N/A | 未验证 |" in report


def test_reporter_marks_failed_task_summary_as_failed_without_empty_unit() -> None:
    record = TaskRunRecord(
        task=TaskItem(task_id="TASK_1", case_id="STATIC-STRUCTURAL", title="结构静力分析"),
        error=ErrorRecord(
            node="designer",
            code="missing_required_inputs",
            message="静力梁分析缺少必要参数: 材料。",
            missing_fields=["材料"],
        ),
    )

    report = ReporterAgent().render([record])

    assert "| TASK_1 | STATIC-STRUCTURAL | result | N/A | N/A | N/A | N/A | 失败 |" in report
    assert "result ()" not in report


def test_reporter_escapes_agent_trace_table_text() -> None:
    record = TaskRunRecord(
        task=TaskItem(
            task_id="TASK|1",
            case_id="STATIC-STRUCTURAL",
            title="结构静力分析",
            planner_llm_trace=AgentLLMTrace(
                agent="Planner|Agent",
                used=True,
                error="provider | error\nsecond line",
            ),
        ),
    )

    report = ReporterAgent().render([record])

    assert "| TASK\\|1 | Planner\\|Agent | 启用 | provider \\| error second line |" in report


def test_reporter_redacts_sensitive_tokens_from_trace_and_error_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_KEY", "sk-env-report-secret")

    def fake_completion(prompt: str, _config: object) -> str:
        _ = prompt
        raise RuntimeError("reporter failed with sk-report-agent-secret and Bearer reporter.token")

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    record = TaskRunRecord(
        task=TaskItem(
            task_id="TASK_1",
            case_id="STATIC-STRUCTURAL",
            title="结构静力分析",
            planner_llm_trace=AgentLLMTrace(
                agent="Planner",
                used=True,
                error=(
                    "planner failed with sk-env-report-secret, "
                    "tp-report-secret-123456, Bearer planner.token and "
                    "https://example.com?token=query-secret"
                ),
            ),
        ),
        error=ErrorRecord(
            node="solver",
            code="solver_failed",
            message="solver failed with sk-direct-report-secret",
        ),
    )
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(
            base_url="https://example.com/v1",
            api_key="sk-report-agent-secret",
            model="demo",
        ),
    )

    report, trace = ReporterAgent(config).render_with_trace([record])

    assert trace.error is not None
    assert "sk-env-report-secret" not in report
    assert "sk-report-agent-secret" not in report
    assert "sk-direct-report-secret" not in report
    assert "tp-report-secret-123456" not in report
    assert "planner.token" not in report
    assert "reporter.token" not in report
    assert "query-secret" not in report
    assert "sk-***" in report
    assert "tp-***" in report
    assert "Bearer ***" in report
    assert "token=***" in report


def test_reporter_render_with_trace_returns_reporter_audit_record() -> None:
    report, trace = ReporterAgent().render_with_trace([])

    assert report.startswith("# MechAgent 仿真报告")
    assert trace.agent == "ReporterAgent"
    assert trace.used is False
    assert "| REPORT | 报告输出 | 未启用 | ok |" in report


def test_reporter_adds_llm_engineering_interpretation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_completion(prompt: str, _config: object) -> str:
        assert "solver_result" in prompt
        assert "post_summary" in prompt
        assert "planner_llm_trace" not in prompt
        assert "solver_llm_trace" not in prompt
        assert "嵌套求解 trace 超时" not in prompt
        assert "Agent trace" in prompt
        return (
            '{"executive_summary":["最大位移处于当前线弹性静力模型的可接受范围。"],'
            '"result_interpretation":["位移云图用于判断薄板整体弯曲趋势。"],'
            '"mesh_and_solver_assessment":["网格包含真实单元拓扑，求解器输出可用于后处理。"],'
            '"boundary_load_interpretation":["四边简支和向下压力决定主弯曲形态。"],'
            '"limitations":["当前结论限于线弹性小变形静力假设。"],'
            '"recommended_next_steps":["复核孔边应力集中并进行网格收敛检查。"]}'
        )

    monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
    config = MechAgentConfig(
        orchestrator=OrchestratorSettings(use_llm_agents=True),
        llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
    )
    record = TaskRunRecord(
        task=TaskItem(
            task_id="TASK_1",
            case_id="STATIC-PERFORATED-PLATE",
            title="多孔薄板",
            planner_llm_trace=AgentLLMTrace(
                agent="Planner",
                used=True,
                prompt="planner prompt",
                response="planner response",
            ),
        ),
        solver_result=SolverRunSummary(
            success=True,
            passed=False,
            model_case_id="STATIC-PERFORATED-PLATE",
            quantity="max_displacement",
            unit="mm",
            predicted=0.031,
            solver="calculix",
            verification_status="unverified",
            solver_llm_trace=AgentLLMTrace(
                agent="SolverAgent",
                used=True,
                prompt="solver prompt",
                response="solver response",
            ),
        ),
        post_summary=PostProcessingSummary(
            success=True,
            scalars={
                "max_displacement_mm": 0.031,
                "solver_llm_trace": {
                    "agent": "SolverAgent",
                    "used": True,
                    "error": "嵌套求解 trace 超时",
                    "prompt_chars": 1105,
                    "response_chars": 0,
                },
            },
        ),
    )

    report, trace = ReporterAgent(config).render_with_trace([record])

    assert trace.used is True
    assert trace.error is None
    assert "## LLM 工程解释" in report
    assert "最大位移处于当前线弹性静力模型的可接受范围" in report
    assert "复核孔边应力集中并进行网格收敛检查" in report

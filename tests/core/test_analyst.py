"""AnalystAgent 测试。"""

from __future__ import annotations

from mechagent.orchestrator.agents import AnalystAgent
from mechagent.orchestrator.models import PostProcessingSummary, TaskItem


def test_analyst_marks_missing_predicted_value_as_not_available() -> None:
    task = TaskItem(task_id="TASK_1", case_id="STATIC-CUSTOM", title="结构静力分析")
    summary = PostProcessingSummary(
        success=False,
        passed=False,
        model_case_id="STATIC-CUSTOM",
        quantity="max_displacement",
        unit="mm",
    )

    text = AnalystAgent().analyze(task, summary)

    assert "max_displacement 为 N/A mm" in text


def test_analyst_preserves_zero_predicted_value() -> None:
    task = TaskItem(task_id="TASK_1", case_id="STATIC-CUSTOM", title="结构静力分析")
    summary = PostProcessingSummary(
        success=True,
        passed=True,
        model_case_id="STATIC-CUSTOM",
        quantity="max_displacement",
        unit="mm",
        predicted=0.0,
    )

    text = AnalystAgent().analyze(task, summary)

    assert "max_displacement 为 0 mm" in text
    assert "未配置参考验收" in text

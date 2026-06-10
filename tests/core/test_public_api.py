"""公开 Python API 回归测试。"""

from __future__ import annotations

import mechagent
from mechagent import (
    DEFAULT_SHOWCASE_EXAMPLE_ID,
    MechAgent,
    MechAgentInspection,
    MechAgentResult,
    SimulationExample,
)
from mechagent import core as mechagent_core
from mechagent.config import MechAgentConfig


def test_public_api_exports_version_and_sdk() -> None:
    assert MechAgent.__name__ == "MechAgent"
    assert MechAgentInspection.__name__ == "MechAgentInspection"
    assert MechAgentResult.__name__ == "MechAgentResult"
    assert isinstance(mechagent.__version__, str)
    assert mechagent.__version__
    assert {
        "MechAgent",
        "MechAgentInspection",
        "MechAgentResult",
        "DEFAULT_SHOWCASE_EXAMPLE_ID",
        "SimulationExample",
        "all_examples",
        "example_by_id",
        "example_payloads",
        "showcase_example",
        "__version__",
    } <= set(mechagent.__all__)
    assert isinstance(mechagent.all_examples()[0], SimulationExample)


def test_public_api_exposes_showcase_example() -> None:
    example = mechagent.showcase_example()

    assert DEFAULT_SHOWCASE_EXAMPLE_ID == "SC-23"
    assert example.case_id == DEFAULT_SHOWCASE_EXAMPLE_ID
    assert example.model_case_id == "STATIC-PERFORATED-PLATE"
    assert "偏心圆孔" in example.title
    assert mechagent.example_by_id("sc-25").case_id == "SC-25"


def test_sdk_inspect_returns_planner_preflight_without_solving() -> None:
    inspection = MechAgent(MechAgentConfig()).inspect(
        "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力静力分析"
    )

    assert inspection.success is True
    assert inspection.ready is True
    assert inspection.tasks[0]["task_id"] == "TASK_1"
    assert inspection.tasks[0]["capability_id"] == "structural_static"
    assert inspection.tasks[0]["geometry_type"] == "beam"
    assert inspection.tasks[0]["missing_fields"] == []


def test_sdk_inspect_reports_missing_inputs() -> None:
    inspection = MechAgent(MechAgentConfig()).inspect("求解一根悬臂梁的静力响应")

    assert inspection.success is True
    assert inspection.ready is False
    assert inspection.tasks[0]["missing_fields"]


def test_core_public_api_exports_rule_checks() -> None:
    assert mechagent_core.check_parameter_ranges.__name__ == "check_parameter_ranges"
    assert (
        mechagent_core.check_static_execution_contract.__name__ == "check_static_execution_contract"
    )
    assert mechagent_core.ensure_parameter_ranges.__name__ == "ensure_parameter_ranges"
    assert (
        mechagent_core.ensure_static_execution_contract.__name__
        == "ensure_static_execution_contract"
    )

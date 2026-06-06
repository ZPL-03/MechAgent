"""公开 Python API 回归测试。"""

from __future__ import annotations

import mechagent
from mechagent import MechAgent, MechAgentResult
from mechagent import core as mechagent_core


def test_public_api_exports_version_and_sdk() -> None:
    assert MechAgent.__name__ == "MechAgent"
    assert MechAgentResult.__name__ == "MechAgentResult"
    assert isinstance(mechagent.__version__, str)
    assert mechagent.__version__
    assert {"MechAgent", "MechAgentResult", "__version__"} <= set(mechagent.__all__)


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

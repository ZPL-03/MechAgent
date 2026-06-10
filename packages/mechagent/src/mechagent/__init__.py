"""MechAgent 主包公开接口。"""

from importlib.metadata import PackageNotFoundError, version
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

from mechagent.app import MechAgent, MechAgentInspection, MechAgentResult
from mechagent.examples import (
    DEFAULT_SHOWCASE_EXAMPLE_ID,
    SimulationExample,
    all_examples,
    example_by_id,
    example_payloads,
    showcase_example,
)

try:
    __version__ = version("mechagent")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = [
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
]

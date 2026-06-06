"""MechAgent 主包公开接口。"""

from importlib.metadata import PackageNotFoundError, version
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

from mechagent.app import MechAgent, MechAgentResult

try:
    __version__ = version("mechagent")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = ["MechAgent", "MechAgentResult", "__version__"]

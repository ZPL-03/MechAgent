"""内置求解器和网格器适配器。"""

from mechagent.core.adapters.calculix import CalculiXAdapter
from mechagent.core.adapters.calculix_mesh import CalculiXInpMesher

__all__ = ["CalculiXAdapter", "CalculiXInpMesher"]

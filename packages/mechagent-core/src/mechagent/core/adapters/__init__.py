"""内置求解器、网格器和 CAD 内核适配器。"""

from mechagent.core.adapters.calculix import CalculiXAdapter
from mechagent.core.adapters.calculix_mesh import CalculiXInpMesher
from mechagent.core.adapters.gmsh_cad import GmshCADKernel

__all__ = ["CalculiXAdapter", "CalculiXInpMesher", "GmshCADKernel"]

"""MechAgent 工具抽象层公开接口。"""

from mechagent.core.exceptions import MechAgentCoreError, MeshError, PostProcError, SolverError
from mechagent.core.factory import (
    create_mesher,
    create_solver,
    register_mesher,
    register_solver,
    registered_meshers,
    registered_solvers,
    unregister_mesher,
    unregister_solver,
)
from mechagent.core.materials import BUILTIN_MATERIALS, MaterialDefinition, match_builtin_material
from mechagent.core.mesher import AbstractMesher, MeshConfig, MeshResult
from mechagent.core.postproc import PostProcessor
from mechagent.core.rules import (
    RuleViolation,
    check_parameter_ranges,
    check_static_execution_contract,
    ensure_parameter_ranges,
    ensure_static_execution_contract,
)
from mechagent.core.solver import AbstractSolver, SolverConfig, SolverResult

__all__ = [
    "AbstractMesher",
    "AbstractSolver",
    "BUILTIN_MATERIALS",
    "MaterialDefinition",
    "MechAgentCoreError",
    "MeshConfig",
    "MeshError",
    "MeshResult",
    "PostProcError",
    "PostProcessor",
    "RuleViolation",
    "SolverConfig",
    "SolverError",
    "SolverResult",
    "create_mesher",
    "create_solver",
    "check_static_execution_contract",
    "register_mesher",
    "register_solver",
    "registered_meshers",
    "registered_solvers",
    "unregister_mesher",
    "unregister_solver",
    "check_parameter_ranges",
    "ensure_parameter_ranges",
    "ensure_static_execution_contract",
    "match_builtin_material",
]

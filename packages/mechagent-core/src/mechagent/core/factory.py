"""求解器和网格器注册工厂。"""

from __future__ import annotations

from collections.abc import Callable

from mechagent.core.adapters import CalculiXAdapter, CalculiXInpMesher
from mechagent.core.mesher import AbstractMesher, MeshConfig
from mechagent.core.solver import AbstractSolver, SolverConfig

SolverBuilder = Callable[[SolverConfig], AbstractSolver]
MesherBuilder = Callable[[MeshConfig], AbstractMesher]

_SOLVER_REGISTRY: dict[str, SolverBuilder] = {}
_MESHER_REGISTRY: dict[str, MesherBuilder] = {}


def create_solver(name: str, config: SolverConfig) -> AbstractSolver:
    """创建求解器实例。

    Args:
        name: 求解器名称。
        config: 求解器配置。

    Returns:
        AbstractSolver: 求解器实例。

    Raises:
        ValueError: 当求解器名称不受支持时抛出。

    Example:
        >>> create_solver("calculix", SolverConfig())
        <mechagent.core.adapters.calculix.CalculiXAdapter object at ...>
    """

    normalized = _normalized_name(name)
    builder = _SOLVER_REGISTRY.get(normalized)
    if builder is not None:
        return builder(config)
    msg = f"未知求解器: {name}。已注册求解器: {', '.join(registered_solvers())}。"
    raise ValueError(msg)


def register_solver(name: str, builder: SolverBuilder, *, replace: bool = False) -> None:
    """注册求解器构造函数。

    Args:
        name: 求解器名称。
        builder: 接收 `SolverConfig` 并返回 `AbstractSolver` 的构造函数。
        replace: 是否覆盖同名注册项。

    Returns:
        无。

    Raises:
        ValueError: 当名称为空或同名注册项已存在时抛出。

    Example:
        >>> register_solver("custom", MySolver)
    """

    normalized = _registration_name(name)
    if normalized in _SOLVER_REGISTRY and not replace:
        msg = f"求解器已注册: {name}"
        raise ValueError(msg)
    _SOLVER_REGISTRY[normalized] = builder


def registered_solvers() -> tuple[str, ...]:
    """返回已注册求解器名称。"""

    return tuple(sorted(_SOLVER_REGISTRY))


def unregister_solver(name: str) -> None:
    """注销求解器构造函数。

    Args:
        name: 求解器名称。

    Returns:
        无。

    Raises:
        ValueError: 当名称未注册时抛出。
    """

    normalized = _normalized_name(name)
    if normalized not in _SOLVER_REGISTRY:
        msg = f"求解器未注册: {name}"
        raise ValueError(msg)
    del _SOLVER_REGISTRY[normalized]


def create_mesher(name: str, config: MeshConfig) -> AbstractMesher:
    """创建网格器实例。

    Args:
        name: 网格器名称。
        config: 网格器配置。

    Returns:
        AbstractMesher: 网格器实例。

    Raises:
        ValueError: 当网格器名称不受支持时抛出。

    Example:
        >>> create_mesher("calculix-inp", MeshConfig())
        <mechagent.core.adapters.calculix_mesh.CalculiXInpMesher object at ...>
    """

    normalized = _normalized_name(name)
    builder = _MESHER_REGISTRY.get(normalized)
    if builder is not None:
        return builder(config)
    msg = f"未知网格器: {name}。已注册网格器: {', '.join(registered_meshers())}。"
    raise ValueError(msg)


def register_mesher(name: str, builder: MesherBuilder, *, replace: bool = False) -> None:
    """注册网格器构造函数。

    Args:
        name: 网格器名称。
        builder: 接收 `MeshConfig` 并返回 `AbstractMesher` 的构造函数。
        replace: 是否覆盖同名注册项。

    Returns:
        无。

    Raises:
        ValueError: 当名称为空或同名注册项已存在时抛出。

    Example:
        >>> register_mesher("custom", MyMesher)
    """

    normalized = _registration_name(name)
    if normalized in _MESHER_REGISTRY and not replace:
        msg = f"网格器已注册: {name}"
        raise ValueError(msg)
    _MESHER_REGISTRY[normalized] = builder


def registered_meshers() -> tuple[str, ...]:
    """返回已注册网格器名称。"""

    return tuple(sorted(_MESHER_REGISTRY))


def unregister_mesher(name: str) -> None:
    """注销网格器构造函数。

    Args:
        name: 网格器名称。

    Returns:
        无。

    Raises:
        ValueError: 当名称未注册时抛出。
    """

    normalized = _normalized_name(name)
    if normalized not in _MESHER_REGISTRY:
        msg = f"网格器未注册: {name}"
        raise ValueError(msg)
    del _MESHER_REGISTRY[normalized]


def _normalized_name(name: str) -> str:
    normalized = name.strip().lower()
    if not normalized:
        msg = "注册名称不能为空。"
        raise ValueError(msg)
    return normalized


def _registration_name(name: str) -> str:
    normalized = _normalized_name(name)
    if name.strip() != name:
        msg = "注册名称不能包含首尾空白。"
        raise ValueError(msg)
    return normalized


register_solver("calculix", CalculiXAdapter)
register_mesher("calculix-inp", CalculiXInpMesher)

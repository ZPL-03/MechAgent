"""求解器和网格器注册工厂。"""

from __future__ import annotations

from collections.abc import Callable

from mechagent.core.adapters import CalculiXAdapter, CalculiXInpMesher, GmshCADKernel
from mechagent.core.cad import AbstractCADKernel, CADConfig
from mechagent.core.executor import AbstractJobExecutor, ExecutorConfig, LocalCommandExecutor
from mechagent.core.mesher import AbstractMesher, MeshConfig
from mechagent.core.solver import AbstractSolver, SolverConfig

SolverBuilder = Callable[[SolverConfig], AbstractSolver]
MesherBuilder = Callable[[MeshConfig], AbstractMesher]
CADKernelBuilder = Callable[[CADConfig], AbstractCADKernel]
ExecutorBuilder = Callable[[ExecutorConfig], AbstractJobExecutor]

_SOLVER_REGISTRY: dict[str, SolverBuilder] = {}
_MESHER_REGISTRY: dict[str, MesherBuilder] = {}
_CAD_REGISTRY: dict[str, CADKernelBuilder] = {}
_EXECUTOR_REGISTRY: dict[str, ExecutorBuilder] = {}


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


def create_cad_kernel(name: str, config: CADConfig) -> AbstractCADKernel:
    """创建 CAD 内核实例。

    Args:
        name: CAD 内核名称。
        config: CAD 内核配置。

    Returns:
        AbstractCADKernel: CAD 内核实例。

    Raises:
        ValueError: 当 CAD 内核名称不受支持时抛出。
    """

    normalized = _normalized_name(name)
    builder = _CAD_REGISTRY.get(normalized)
    if builder is not None:
        return builder(config)
    msg = f"未知 CAD 内核: {name}。已注册 CAD 内核: {', '.join(registered_cad_kernels())}。"
    raise ValueError(msg)


def register_cad_kernel(name: str, builder: CADKernelBuilder, *, replace: bool = False) -> None:
    """注册 CAD 内核构造函数。

    Args:
        name: CAD 内核名称。
        builder: 接收 `CADConfig` 并返回 `AbstractCADKernel` 的构造函数。
        replace: 是否覆盖同名注册项。

    Returns:
        无。

    Raises:
        ValueError: 当名称为空或同名注册项已存在时抛出。
    """

    normalized = _registration_name(name)
    if normalized in _CAD_REGISTRY and not replace:
        msg = f"CAD 内核已注册: {name}"
        raise ValueError(msg)
    _CAD_REGISTRY[normalized] = builder


def registered_cad_kernels() -> tuple[str, ...]:
    """返回已注册 CAD 内核名称。"""

    return tuple(sorted(_CAD_REGISTRY))


def unregister_cad_kernel(name: str) -> None:
    """注销 CAD 内核构造函数。

    Args:
        name: CAD 内核名称。

    Returns:
        无。

    Raises:
        ValueError: 当名称未注册时抛出。
    """

    normalized = _normalized_name(name)
    if normalized not in _CAD_REGISTRY:
        msg = f"CAD 内核未注册: {name}"
        raise ValueError(msg)
    del _CAD_REGISTRY[normalized]


def create_executor(name: str, config: ExecutorConfig) -> AbstractJobExecutor:
    """创建作业执行器实例。

    Args:
        name: 执行器名称。
        config: 执行器配置。

    Returns:
        AbstractJobExecutor: 执行器实例。

    Raises:
        ValueError: 当执行器名称不受支持时抛出。

    Example:
        >>> create_executor("local", ExecutorConfig())
        <mechagent.core.executor.LocalCommandExecutor object at ...>
    """

    normalized = _normalized_name(name)
    builder = _EXECUTOR_REGISTRY.get(normalized)
    if builder is not None:
        return builder(config)
    msg = f"未知执行器: {name}。已注册执行器: {', '.join(registered_executors())}。"
    raise ValueError(msg)


def register_executor(name: str, builder: ExecutorBuilder, *, replace: bool = False) -> None:
    """注册作业执行器构造函数。

    Args:
        name: 执行器名称。
        builder: 接收 `ExecutorConfig` 并返回 `AbstractJobExecutor` 的构造函数。
        replace: 是否覆盖同名注册项。

    Returns:
        无。

    Raises:
        ValueError: 当名称为空或同名注册项已存在时抛出。
    """

    normalized = _registration_name(name)
    if normalized in _EXECUTOR_REGISTRY and not replace:
        msg = f"执行器已注册: {name}"
        raise ValueError(msg)
    _EXECUTOR_REGISTRY[normalized] = builder


def registered_executors() -> tuple[str, ...]:
    """返回已注册执行器名称。"""

    return tuple(sorted(_EXECUTOR_REGISTRY))


def unregister_executor(name: str) -> None:
    """注销作业执行器构造函数。

    Args:
        name: 执行器名称。

    Returns:
        无。

    Raises:
        ValueError: 当名称未注册时抛出。
    """

    normalized = _normalized_name(name)
    if normalized not in _EXECUTOR_REGISTRY:
        msg = f"执行器未注册: {name}"
        raise ValueError(msg)
    del _EXECUTOR_REGISTRY[normalized]


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
register_cad_kernel("gmsh-occ", GmshCADKernel)
register_executor("local", LocalCommandExecutor)

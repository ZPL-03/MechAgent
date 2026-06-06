"""求解器抽象接口。"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mechagent.core.defaults import DEFAULT_CALCULIX_PATH
from mechagent.core.exceptions import SolverError
from mechagent.core.models import ModelParams


class SolverConfig(BaseModel):
    """求解器运行配置。

    Args:
        solver_path: 求解器可执行文件路径。
        work_dir: 求解工作目录。
        num_cpus: 并行 CPU 核数。
        timeout: 最大允许求解时间，单位为 s。

    Returns:
        SolverConfig: 经过校验的求解器配置。

    Raises:
        pydantic.ValidationError: 当配置字段不满足类型或范围约束时抛出。

    Example:
        >>> SolverConfig(work_dir="mechagent_output/RUN_demo")
        SolverConfig(...)
    """

    model_config = ConfigDict(extra="forbid")

    solver_path: Union[Path, str] = Field(default=DEFAULT_CALCULIX_PATH)
    work_dir: Path = Field(default=Path("mechagent_output"))
    num_cpus: int = Field(default=1, ge=1)
    timeout: int = Field(default=3600, ge=1)


class SolverResult(BaseModel):
    """求解器执行结果。

    Args:
        success: 求解是否成功。
        wall_time: 实际耗时，单位为 s。
        output_files: 物理输出文件路径列表。
        summary: 关键标量结果。
        error_message: 失败诊断信息。

    Returns:
        SolverResult: 统一求解器结果对象。

    Raises:
        pydantic.ValidationError: 当结果字段不满足 schema 时抛出。

    Example:
        >>> SolverResult(success=True, wall_time=0.1, output_files=[], summary={"u_max": 1.0})
        SolverResult(success=True, wall_time=0.1, output_files=[], summary={'u_max': 1.0}, ...)
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    wall_time: float = Field(ge=0)
    output_files: list[Path] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None

    @field_validator("wall_time")
    @classmethod
    def _wall_time_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "solver.wall_time 必须是有限数值。"
            raise ValueError(msg)
        return value


class AbstractSolver(ABC):
    """所有 FEM 求解器适配器必须实现的抽象基类。

    Args:
        config: 求解器配置。

    Returns:
        AbstractSolver: 具体求解器实例。

    Raises:
        TypeError: 当子类定义与模板方法冲突的 run 时抛出。

    Example:
        >>> class MySolver(AbstractSolver):
        ...     def generate_input(self, model_params): return Path("model.inp")
        ...     def solve(self, input_file):
        ...         return SolverResult(success=True, wall_time=0, summary={})
        ...     def extract_results(self, result): return result.summary
    """

    config: SolverConfig

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "run" in cls.__dict__:
            msg = "AbstractSolver.run() 是固定模板方法，子类只实现输入生成、执行和结果提取。"
            raise TypeError(msg)

    def __init__(self, config: SolverConfig) -> None:
        self.config = config
        self.config.work_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def generate_input(self, model_params: ModelParams) -> Path:
        """生成求解器输入文件。

        Args:
            model_params: 结构化仿真参数。

        Returns:
            Path: 生成的输入文件路径。

        Raises:
            SolverError: 当输入文件生成失败时抛出。

        Example:
            >>> solver.generate_input(model_params)
            WindowsPath('mechagent_output/model.inp')
        """

    @abstractmethod
    def solve(self, input_file: Path) -> SolverResult:
        """执行求解器。

        Args:
            input_file: 求解器输入文件路径。

        Returns:
            SolverResult: 求解器执行结果。

        Raises:
            SolverError: 当求解器进程异常失败时抛出。

        Example:
            >>> solver.solve(Path("model.inp"))
            SolverResult(success=True, ...)
        """

    @abstractmethod
    def extract_results(self, result: SolverResult) -> dict[str, Any]:
        """提取统一结果。

        Args:
            result: 求解器执行结果。

        Returns:
            dict[str, Any]: 面向上层 Agent 的结果字典。

        Raises:
            SolverError: 当结果文件缺失或解析失败时抛出。

        Example:
            >>> solver.extract_results(result)
            {'max_displacement_mm': 1.0}
        """

    def run(self, model_params: ModelParams) -> dict[str, Any]:
        """按固定模板执行完整求解流程。

        Args:
            model_params: 结构化仿真参数。

        Returns:
            dict[str, Any]: 统一结果字典。

        Raises:
            SolverError: 当输入生成、求解或结果提取任一阶段失败时抛出。

        Example:
            >>> solver.run(model_params)
            {'success': True, 'max_displacement_mm': 1.0}
        """

        start = time.perf_counter()
        input_file = self.generate_input(model_params)
        result = self.solve(input_file)
        if not result.success:
            raise SolverError(result.error_message or "求解器返回失败状态。")
        extracted = self.extract_results(result)
        extracted.setdefault("wall_time_s", time.perf_counter() - start)
        return extracted

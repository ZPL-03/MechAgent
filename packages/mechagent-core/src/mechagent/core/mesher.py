"""网格器抽象接口。"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mechagent.core.models import ModelParams


class MeshConfig(BaseModel):
    """网格器运行配置。

    Args:
        work_dir: 网格输出目录。
        seed_size: 全局网格种子尺寸，单位为 mm。
        min_quality: 最小网格质量阈值。

    Returns:
        MeshConfig: 经过校验的网格器配置。

    Raises:
        pydantic.ValidationError: 当字段不满足类型或范围约束时抛出。

    Example:
        >>> MeshConfig(work_dir="mechagent_output", seed_size=5)
        MeshConfig(...)
    """

    model_config = ConfigDict(extra="forbid")

    work_dir: Path = Field(default=Path("mechagent_output"))
    seed_size: float = Field(default=5.0, gt=0)
    min_quality: float = Field(default=0.3, ge=0, le=1)

    @field_validator("seed_size", "min_quality")
    @classmethod
    def _numeric_config_values_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "网格器数值配置必须是有限数值。"
            raise ValueError(msg)
        return value


class MeshResult(BaseModel):
    """网格生成结果。

    Args:
        success: 网格是否生成成功。
        mesh_file: 主网格文件路径。
        quality: 网格质量指标。
        metadata: 附加网格信息。
        error_message: 失败诊断信息。

    Returns:
        MeshResult: 统一网格结果对象。

    Raises:
        pydantic.ValidationError: 当结果字段不满足 schema 时抛出。

    Example:
        >>> MeshResult(success=True, mesh_file="model.inp", quality={"min_jacobian": 0.8})
        MeshResult(...)
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    mesh_file: Optional[Path] = None
    quality: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None


class AbstractMesher(ABC):
    """所有网格器适配器必须实现的抽象基类。

    Args:
        config: 网格器配置。

    Returns:
        AbstractMesher: 具体网格器实例。

    Raises:
        OSError: 当工作目录无法创建时抛出。

    Example:
        >>> class MyMesher(AbstractMesher):
        ...     def generate(self, model_params): return MeshResult(success=True)
    """

    def __init__(self, config: MeshConfig) -> None:
        self.config = config
        self.config.work_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def generate(self, model_params: ModelParams) -> MeshResult:
        """生成网格。

        Args:
            model_params: 结构化仿真参数。

        Returns:
            MeshResult: 网格生成结果。

        Raises:
            MeshError: 当网格生成失败时抛出。

        Example:
            >>> mesher.generate(model_params)
            MeshResult(success=True, ...)
        """

"""后处理工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field


class PostProcessSummary(BaseModel):
    """后处理摘要。

    Args:
        scalars: 标量结果。
        figures: 图片路径。
        files: 其他结果文件路径。

    Returns:
        PostProcessSummary: 后处理摘要对象。

    Raises:
        pydantic.ValidationError: 当结果字段不满足 schema 时抛出。

    Example:
        >>> PostProcessSummary(scalars={"u_max": 1.0})
        PostProcessSummary(scalars={'u_max': 1.0}, figures=[], files=[])
    """

    model_config = ConfigDict(extra="forbid")

    scalars: dict[str, Any] = Field(default_factory=dict)
    figures: list[Path] = Field(default_factory=list)
    files: list[Path] = Field(default_factory=list)


class PostProcessor:
    """统一后处理接口。

    Args:
        output_dir: 后处理输出目录。

    Returns:
        PostProcessor: 后处理工具实例。

    Raises:
        OSError: 当输出目录无法创建时抛出。

    Example:
        >>> PostProcessor("mechagent_output").summarize({"u_max": 1.0})
        PostProcessSummary(scalars={'u_max': 1.0}, figures=[], files=[])
    """

    def __init__(self, output_dir: Union[Path, str]) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def summarize(self, result: dict[str, Any]) -> PostProcessSummary:
        """生成后处理摘要。

        Args:
            result: 求解器统一结果字典。

        Returns:
            PostProcessSummary: 后处理摘要。

        Raises:
            pydantic.ValidationError: 当摘要字段不满足 schema 时抛出。

        Example:
            >>> processor.summarize({"max_stress_mpa": 12.0})
            PostProcessSummary(scalars={'max_stress_mpa': 12.0}, figures=[], files=[])
        """

        return PostProcessSummary(scalars=result)

"""仿真意图标准化模型。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SimulationIntent(BaseModel):
    """用户自然语言请求的标准化意图。

    Args:
        raw_request: 用户原始请求。
        capability_id: 能力注册表编号。
        analysis_type: 分析类型。
        physics_domain: 物理领域。
        geometry_type: 几何类型。
        missing_fields: 缺失字段列表。
        confidence: 意图识别置信度。
        source: 意图来源。

    Returns:
        SimulationIntent: 标准化仿真意图。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> SimulationIntent(raw_request="梁静力", capability_id="structural_static")
        SimulationIntent(...)
    """

    model_config = ConfigDict(extra="forbid")

    raw_request: str
    capability_id: str
    analysis_type: str = "static"
    physics_domain: str = "structural"
    geometry_type: Optional[str] = None
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = "deterministic"

    @property
    def complete(self) -> bool:
        """判断意图是否具备执行所需字段。

        Args:
            无。

        Returns:
            bool: 无缺失字段时返回 True。

        Raises:
            无。

        Example:
            >>> SimulationIntent(raw_request="x", capability_id="c").complete
            True
        """

        return not self.missing_fields

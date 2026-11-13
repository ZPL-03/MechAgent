"""GeometryAgent：CAD 形体导入与几何候选生成。

消费 CAD 内核的 `CADImportResult`，把几何摘要映射为结构化几何候选（几何类型、包围盒尺寸、
边界/载荷区域候选与缺参诊断），供 Designer 与能力解析进一步补全材料、载荷与边界。候选
只有在执行前契约、区域映射和网格门禁通过后才可能进入求解。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from mechagent.config import MechAgentConfig
from mechagent.core.cad import (
    CADArtifact,
    CADConfig,
    CADGeometrySummary,
    GeometryCandidate,
    GeometryValidation,
    RegionBinding,
    geometry_candidate_from_summary,
)
from mechagent.core.factory import create_cad_kernel
from mechagent.core.models import ModelParams
from mechagent.orchestrator.static_parser import parse_static_model_params_from_geometry


class GeometryAnalysis(BaseModel):
    """几何分析结果。

    Args:
        success: 导入与几何归纳是否成功。
        source: CAD 文件路径。
        kernel: 使用的 CAD 内核注册名。
        candidate: 成功时的几何候选。
        summary: 成功时的几何摘要。
        artifact: 源文件及摘要指纹。
        validation: 几何、拓扑和区域契约校验结果。
        region_bindings: 区域语义到拓扑实体的绑定记录。
        wall_time: 处理耗时，单位为 s。
        error_message: 失败诊断信息。

    Returns:
        GeometryAnalysis: 统一几何分析结果。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    source: Path
    kernel: str
    candidate: Optional[GeometryCandidate] = None
    summary: Optional[CADGeometrySummary] = None
    artifact: CADArtifact | None = None
    validation: GeometryValidation | None = None
    region_bindings: list[RegionBinding] = Field(default_factory=list)
    wall_time: float = Field(default=0.0, ge=0)
    error_message: Optional[str] = None


class GeometryAgent:
    """CAD 形体导入与几何候选生成 Agent。

    Args:
        config: 运行配置。
        work_dir: 几何处理工作目录。

    Returns:
        GeometryAgent: 几何 Agent 实例。

    Raises:
        无。

    Example:
        >>> GeometryAgent(MechAgentConfig(), Path("mechagent_output")).analyze(Path("bracket.step"))
        GeometryAnalysis(...)
    """

    def __init__(self, config: MechAgentConfig, work_dir: Path) -> None:
        self.config = config
        self.work_dir = work_dir

    def analyze(self, source: Path) -> GeometryAnalysis:
        """导入 CAD 形体并生成几何候选。

        Args:
            source: CAD 文件路径。

        Returns:
            GeometryAnalysis: 成功时含几何候选与摘要，失败时含诊断信息。

        Raises:
            ValueError: 当配置的 CAD 内核未注册时抛出。
        """

        kernel_name = self.config.cad.default or "gmsh-occ"
        kernel = create_cad_kernel(
            kernel_name,
            CADConfig(
                work_dir=self.work_dir,
                healing=self.config.cad.healing,
                linear_deflection=self.config.cad.linear_deflection,
            ),
        )
        result = kernel.import_model(source)
        if not result.success or result.summary is None:
            return GeometryAnalysis(
                success=False,
                source=source,
                kernel=kernel_name,
                summary=result.summary,
                artifact=result.artifact,
                validation=result.validation,
                region_bindings=result.region_bindings,
                wall_time=result.wall_time,
                error_message=result.error_message,
            )
        candidate = geometry_candidate_from_summary(result.summary)
        candidate = candidate.model_copy(
            update={
                "source_path": str(source.resolve()),
                "artifact": result.artifact,
                "geometry_validation": result.validation,
                "region_bindings": result.region_bindings,
            }
        )
        return GeometryAnalysis(
            success=True,
            source=source,
            kernel=kernel_name,
            candidate=candidate,
            summary=result.summary,
            artifact=result.artifact,
            validation=result.validation,
            region_bindings=result.region_bindings,
            wall_time=result.wall_time,
        )

    def to_model_params(
        self,
        source: Path,
        completion: str,
        *,
        analysis: GeometryAnalysis | None = None,
    ) -> ModelParams:
        """从 CAD 文件与自然语言补全生成结构化参数候选。

        导入 CAD 形体得到几何候选，与描述材料、载荷与边界的自然语言补全合并解析为
        `ModelParams`。只有候选属于当前参数化能力、区域来源通过执行前门禁且网格器支持
        该几何路径时，结果才可以进入网格和求解；该方法不证明任意 CAD 拓扑已被保留。

        Args:
            source: CAD 文件路径。
            completion: 描述材料、载荷与边界的自然语言补全。
            analysis: 可复用的同一源文件分析结果；省略时重新导入源文件。

        Returns:
            ModelParams: 结构化仿真参数候选；是否可执行由后续契约门禁决定。

        Raises:
            ValueError: 当 CAD 几何分析失败或合成请求缺少必要仿真参数时抛出。
        """

        resolved_analysis = analysis or self.analyze(source)
        if not resolved_analysis.success or resolved_analysis.candidate is None:
            msg = resolved_analysis.error_message or "CAD 几何分析失败。"
            raise ValueError(msg)
        return parse_static_model_params_from_geometry(resolved_analysis.candidate, completion)

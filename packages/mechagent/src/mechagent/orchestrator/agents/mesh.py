"""MeshAgent。"""

from __future__ import annotations

import math
from pathlib import Path

from mechagent.config import MechAgentConfig
from mechagent.core.factory import create_mesher
from mechagent.core.mesher import MeshConfig, MeshResult
from mechagent.core.models import ModelParams
from mechagent.orchestrator.capabilities import get_capability
from mechagent.orchestrator.llm_advisor import AgentLLMAdvisor
from mechagent.orchestrator.models import MeshAgentOutput, TaskItem


class MeshAgent:
    """生成网格并记录网格质量。

    Args:
        config: 全局配置。
        work_dir: 运行目录。

    Returns:
        MeshAgent: Mesh 节点实例。

    Raises:
        OSError: 当运行目录无法创建时抛出。

    Example:
        >>> MeshAgent(MechAgentConfig(), Path("mechagent_output")).generate(tc01_model_params())
        MeshResult(...)
    """

    def __init__(self, config: MechAgentConfig, work_dir: Path) -> None:
        self.config = config
        self.advisor = AgentLLMAdvisor(config)
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, model_params: ModelParams, task: TaskItem | None = None) -> MeshResult:
        """生成网格。

        Args:
            model_params: 结构化仿真参数。
            task: Planner 输出任务，用于能力级工具选择。

        Returns:
            MeshResult: 网格生成结果。

        Raises:
            无。

        Example:
            >>> agent.generate(model_params)
            MeshResult(success=True, ...)
        """

        return self.generate_with_trace(model_params, task).mesh_result

    def generate_with_trace(
        self,
        model_params: ModelParams,
        task: TaskItem | None = None,
    ) -> MeshAgentOutput:
        """生成网格和 Mesh LLM 审计记录。

        Args:
            model_params: 结构化仿真参数。
            task: Planner 输出任务，用于能力级工具选择。

        Returns:
            MeshAgentOutput: 网格结果和审计记录。

        Raises:
            无。
        """

        mesher_name = self._mesher_name(task)
        mesher = create_mesher(
            mesher_name,
            MeshConfig(
                work_dir=self.work_dir,
                seed_size=model_params.mesh.seed_size,
                min_quality=self.config.mesher.min_quality,
            ),
        )
        result = mesher.generate(model_params)
        result = _apply_quality_gate(result, self.config.mesher.min_quality)
        trace = self.advisor.advise(
            "MeshAgent",
            "检查网格尺寸、单元类型和网格生成策略",
            model_params.model_dump_json(),
        )
        return MeshAgentOutput(mesh_result=result, mesh_llm_trace=trace)

    def _mesher_name(self, task: TaskItem | None) -> str:
        if task is not None and task.capability_id:
            capability = get_capability(task.capability_id)
            if capability.mesher_name:
                return capability.mesher_name
        return self.config.mesher.default


def _apply_quality_gate(result: MeshResult, min_quality: float) -> MeshResult:
    if not result.success:
        return result
    if result.mesh_file is None:
        return result.model_copy(
            update={
                "success": False,
                "error_message": "网格结果缺少 mesh_file，求解阶段无法继续。",
            }
        )
    invalid = [name for name, value in result.quality.items() if not math.isfinite(value)]
    if invalid:
        details = "、".join(f"{name}={result.quality[name]}" for name in invalid)
        return result.model_copy(
            update={
                "success": False,
                "error_message": f"网格质量指标不是有限数值: {details}。",
            }
        )
    failed = [
        name
        for name, value in result.quality.items()
        if name.startswith("min_") and value < min_quality
    ]
    if not failed:
        return result
    details = "、".join(f"{name}={result.quality[name]:.6g}" for name in failed)
    return result.model_copy(
        update={
            "success": False,
            "error_message": f"网格质量低于阈值 {min_quality:.6g}: {details}。",
        }
    )

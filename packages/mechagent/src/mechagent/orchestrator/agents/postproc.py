"""PostProcAgent。"""

from __future__ import annotations

from pathlib import Path

from mechagent.config import MechAgentConfig
from mechagent.core.postproc import PostProcessor
from mechagent.orchestrator.llm_advisor import AgentLLMAdvisor
from mechagent.orchestrator.llm_payload import advisory_payload
from mechagent.orchestrator.models import PostProcessingSummary, SolverRunSummary


class PostProcAgent:
    """提取求解结果摘要。

    Args:
        work_dir: 运行目录。

    Returns:
        PostProcAgent: PostProc 节点实例。

    Raises:
        OSError: 当运行目录无法创建时抛出。

    Example:
        >>> summary = SolverRunSummary(success=True)
        >>> PostProcAgent(Path("mechagent_output")).summarize(summary).success
        True
    """

    def __init__(self, work_dir: Path, config: MechAgentConfig | None = None) -> None:
        self.processor = PostProcessor(work_dir)
        self.advisor = AgentLLMAdvisor(config)

    def summarize(self, solver_result: SolverRunSummary) -> PostProcessingSummary:
        """生成后处理摘要。

        Args:
            solver_result: 求解摘要。

        Returns:
            PostProcessingSummary: 标量摘要。

        Raises:
            pydantic.ValidationError: 当后处理摘要不满足 schema 时抛出。

        Example:
            >>> PostProcAgent(Path("out")).summarize(SolverRunSummary(predicted=1)).predicted
            1.0
        """

        scalars = self.processor.summarize(solver_result.to_mapping()).scalars
        trace = self.advisor.advise(
            "PostProcAgent",
            "检查后处理标量、单位和关键结果字段",
            advisory_payload(scalars),
        )
        return PostProcessingSummary.from_solver_summary(solver_result, trace, scalars)

"""SolverAgent。"""

from __future__ import annotations

from pathlib import Path

from mechagent.config import MechAgentConfig
from mechagent.core.factory import create_solver
from mechagent.core.mesher import MeshResult
from mechagent.core.models import ModelParams
from mechagent.core.solver import SolverConfig
from mechagent.orchestrator.capabilities import get_capability
from mechagent.orchestrator.evaluation import ResultEvaluationContext
from mechagent.orchestrator.llm_advisor import AgentLLMAdvisor
from mechagent.orchestrator.models import SolverRunSummary, TaskItem


class SolverAgent:
    """选择求解器并执行计算。

    Args:
        config: 全局配置。
        work_dir: 运行目录。

    Returns:
        SolverAgent: Solver 节点实例。

    Raises:
        OSError: 当运行目录无法创建时抛出。

    Example:
        >>> SolverAgent(MechAgentConfig(), Path("mechagent_output"))
        <mechagent.orchestrator.agents.solver.SolverAgent object at ...>
    """

    def __init__(self, config: MechAgentConfig, work_dir: Path) -> None:
        self.config = config
        self.advisor = AgentLLMAdvisor(config)
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def solve(
        self,
        task: TaskItem,
        model_params: ModelParams,
        mesh_result: MeshResult | None = None,
    ) -> SolverRunSummary:
        """执行求解。

        Args:
            task: 任务描述。
            model_params: 结构化仿真参数。
            mesh_result: MeshAgent 生成的网格结果。

        Returns:
            SolverRunSummary: 求解摘要。

        Raises:
            SolverError: 当求解器失败时抛出。

        Example:
            >>> agent.solve(task, model_params, mesh_result)
            SolverRunSummary(success=True, ...)
        """

        if mesh_result is not None:
            if not mesh_result.success or mesh_result.mesh_file is None:
                msg = mesh_result.error_message or "网格生成失败，求解阶段无法继续。"
                raise ValueError(msg)
            model_params = model_params.model_copy(update={"mesh_file": mesh_result.mesh_file})

        if not task.capability_id:
            msg = "SolverAgent 需要 TaskItem.capability_id 选择结果评价器。"
            raise ValueError(msg)
        capability = get_capability(task.capability_id)
        solver_name = capability.solver_name or self.config.solver.default
        solver = create_solver(
            solver_name,
            self._solver_config(solver_name),
        )
        result = solver.run(model_params)
        trace = self.advisor.advise(
            "SolverAgent",
            "检查求解器选择、输入模型和求解结果一致性",
            model_params.model_dump_json(),
        )
        if mesh_result is not None:
            result["mesh_file"] = str(mesh_result.mesh_file)
            result["mesh_metadata"] = mesh_result.metadata
        result["solver_llm_trace"] = trace.model_dump(mode="json")
        evaluated = capability.evaluator(
            ResultEvaluationContext(
                model_params=model_params,
                solver_result=result,
                solver_name=solver_name,
                task_case_id=task.case_id,
                task_title=task.title,
            )
        )
        return SolverRunSummary.from_mapping(evaluated)

    def failure_summary(
        self,
        task: TaskItem,
        model_params: ModelParams,
        mesh_result: MeshResult | None = None,
    ) -> SolverRunSummary:
        """生成求解阶段失败时的结构化摘要。"""

        mesh_file = mesh_result.mesh_file if mesh_result is not None else None
        mesh_metadata = mesh_result.metadata if mesh_result is not None else {}
        return SolverRunSummary(
            success=False,
            model_case_id=model_params.case_id or task.case_id,
            verification_status="failed",
            solver=self._solver_name(task),
            task_title=task.title,
            mesh_file=mesh_file,
            mesh_metadata=mesh_metadata,
        )

    def _solver_name(self, task: TaskItem) -> str:
        capability = get_capability(task.capability_id)
        return capability.solver_name or self.config.solver.default

    def _solver_config(self, solver_name: str) -> SolverConfig:
        if solver_name.lower() == "calculix":
            calculix = self.config.solver.calculix
            return SolverConfig(
                solver_path=calculix.path,
                work_dir=self.work_dir,
                num_cpus=calculix.num_cpus,
                timeout=calculix.timeout,
            )
        return SolverConfig(work_dir=self.work_dir)

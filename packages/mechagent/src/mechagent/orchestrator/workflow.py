"""顺序工作流执行器。"""

from __future__ import annotations

from mechagent.config import MechAgentConfig
from mechagent.orchestrator.agents import (
    AnalystAgent,
    DesignerAgent,
    MeshAgent,
    PlannerAgent,
    PostProcAgent,
    ReporterAgent,
    SolverAgent,
)
from mechagent.orchestrator.agents.designer import DesignerAgentError
from mechagent.orchestrator.ids import new_run_id
from mechagent.orchestrator.models import ErrorRecord, TaskItem, TaskRunRecord, WorkflowResult


class SequentialWorkflow:
    """自然语言到仿真报告的顺序工作流。

    Args:
        config: 全局配置。

    Returns:
        SequentialWorkflow: 工作流实例。

    Raises:
        OSError: 当输出目录无法创建时抛出。

    Example:
        >>> request = "长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，向下1000N"
        >>> SequentialWorkflow(MechAgentConfig()).run(request).success
        True
    """

    def __init__(self, config: MechAgentConfig) -> None:
        self.config = config

    def run(self, request: str) -> WorkflowResult:
        """执行完整工作流。

        Args:
            request: 用户自然语言请求。

        Returns:
            WorkflowResult: 完整运行结果。

        Raises:
            OSError: 当输出目录或报告文件无法写入时抛出。

        Example:
            >>> request = "长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，向下1000N"
            >>> workflow.run(request).success
            True
        """

        work_dir = self.config.output.output_dir / new_run_id(request)
        work_dir.mkdir(parents=True, exist_ok=True)
        planner = PlannerAgent(self.config)
        designer = DesignerAgent(self.config)
        analyst = AnalystAgent(self.config)
        reporter = ReporterAgent(self.config)

        records: list[TaskRunRecord] = []
        errors: list[ErrorRecord] = []
        try:
            tasks = planner.plan(request)
        except Exception as exc:
            error = ErrorRecord.from_exception("planner", exc)
            errors.append(error)
            records.append(_request_failure_record(error))
            report, reporter_trace = reporter.render_with_trace(records)
            report_path = work_dir / "report.md"
            report_path.write_text(report, encoding="utf-8")
            return WorkflowResult(
                success=False,
                request=request,
                tasks=records,
                report=report,
                work_dir=work_dir,
                report_path=report_path,
                errors=errors,
                reporter_llm_trace=reporter_trace,
            )

        for task in tasks:
            task_work_dir = work_dir / task.task_id
            task_work_dir.mkdir(parents=True, exist_ok=True)
            mesh_agent = MeshAgent(self.config, task_work_dir)
            solver_agent = SolverAgent(self.config, task_work_dir)
            post_agent = PostProcAgent(task_work_dir, self.config)
            record = TaskRunRecord(task=task)
            current_node = "designer"
            try:
                design_output = designer.design_with_trace(task)
                model_params = design_output.model_params
                record.model_params = model_params
                record.designer_llm_trace = design_output.designer_llm_trace
                current_node = "mesh"
                mesh_output = mesh_agent.generate_with_trace(model_params, task)
                mesh_result = mesh_output.mesh_result
                record.mesh_result = mesh_result
                record.mesh_llm_trace = mesh_output.mesh_llm_trace
                if not mesh_result.success:
                    msg = mesh_result.error_message or "网格生成失败，求解阶段无法继续。"
                    raise ValueError(msg)
                current_node = "solver"
                solver_result = solver_agent.solve(task, model_params, mesh_result)
                record.solver_result = solver_result
                current_node = "postproc"
                post_summary = post_agent.summarize(solver_result)
                record.post_summary = post_summary
                current_node = "analyst"
                analysis_text = analyst.analyze(task, post_summary)
                record.analysis_text = analysis_text
            except Exception as exc:
                error = ErrorRecord.from_exception(current_node, exc, task)
                errors.append(error)
                if current_node == "designer" and isinstance(exc, DesignerAgentError):
                    record.designer_llm_trace = exc.llm_trace
                if current_node == "solver" and record.model_params is not None:
                    record.solver_result = solver_agent.failure_summary(
                        task,
                        record.model_params,
                        record.mesh_result,
                    )
                record.error = error
            records.append(record)

        success = (
            not errors and bool(records) and all(record.solver_result.success for record in records)
        )
        report, reporter_trace = reporter.render_with_trace(records)
        report_path = work_dir / "report.md"
        report_path.write_text(report, encoding="utf-8")
        return WorkflowResult(
            success=success,
            request=request,
            tasks=records,
            report=report,
            work_dir=work_dir,
            report_path=report_path,
            errors=errors,
            reporter_llm_trace=reporter_trace,
        )


def _request_failure_record(error: ErrorRecord) -> TaskRunRecord:
    task = TaskItem(
        task_id="REQUEST",
        case_id="REQUEST",
        title="请求解析",
    )
    return TaskRunRecord(task=task, error=error)

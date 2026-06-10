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
from mechagent.orchestrator.progress import StageName, emit_progress


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
        emit_progress("planner", "running", _stage_message("planner", "running"))
        try:
            tasks = planner.plan(request)
        except Exception as exc:
            emit_progress("planner", "failed", _stage_message("planner", "failed"))
            error = ErrorRecord.from_exception("planner", exc)
            errors.append(error)
            records.append(_request_failure_record(error))
            emit_progress("reporter", "running", _stage_message("reporter", "running"))
            report, reporter_trace = reporter.render_with_trace(records)
            report_path = work_dir / "report.md"
            report_path.write_text(report, encoding="utf-8")
            emit_progress("reporter", "complete", _stage_message("reporter", "complete"))
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
        emit_progress("planner", "complete", _stage_message("planner", "complete"))

        for task in tasks:
            task_work_dir = work_dir / task.task_id
            task_work_dir.mkdir(parents=True, exist_ok=True)
            mesh_agent = MeshAgent(self.config, task_work_dir)
            solver_agent = SolverAgent(self.config, task_work_dir)
            post_agent = PostProcAgent(task_work_dir, self.config)
            record = TaskRunRecord(task=task)
            current_node = "designer"
            try:
                emit_progress("designer", "running", _stage_message("designer", "running"))
                design_output = designer.design_with_trace(task)
                model_params = design_output.model_params
                record.model_params = model_params
                record.designer_llm_trace = design_output.designer_llm_trace
                emit_progress("designer", "complete", _stage_message("designer", "complete"))
                current_node = "mesh"
                emit_progress("mesh", "running", _stage_message("mesh", "running"))
                mesh_output = mesh_agent.generate_with_trace(model_params, task)
                mesh_result = mesh_output.mesh_result
                record.mesh_result = mesh_result
                record.mesh_llm_trace = mesh_output.mesh_llm_trace
                if not mesh_result.success:
                    msg = mesh_result.error_message or "网格生成失败，求解阶段无法继续。"
                    raise ValueError(msg)
                emit_progress("mesh", "complete", _stage_message("mesh", "complete"))
                current_node = "solver"
                emit_progress("solver", "running", _stage_message("solver", "running"))
                solver_result = solver_agent.solve(task, model_params, mesh_result)
                record.solver_result = solver_result
                emit_progress("solver", "complete", _stage_message("solver", "complete"))
                current_node = "postproc"
                emit_progress("postproc", "running", _stage_message("postproc", "running"))
                post_summary = post_agent.summarize(solver_result)
                record.post_summary = post_summary
                emit_progress("postproc", "complete", _stage_message("postproc", "complete"))
                current_node = "analyst"
                emit_progress("analyst", "running", _stage_message("analyst", "running"))
                analysis_text = analyst.analyze(task, post_summary)
                record.analysis_text = analysis_text
                emit_progress("analyst", "complete", _stage_message("analyst", "complete"))
            except Exception as exc:
                emit_progress(
                    _stage_name(current_node),
                    "failed",
                    _stage_message(_stage_name(current_node), "failed"),
                )
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
        emit_progress("reporter", "running", _stage_message("reporter", "running"))
        report, reporter_trace = reporter.render_with_trace(records)
        report_path = work_dir / "report.md"
        report_path.write_text(report, encoding="utf-8")
        emit_progress("reporter", "complete", _stage_message("reporter", "complete"))
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


def _stage_name(value: str) -> StageName:
    if value == "planner":
        return "planner"
    if value == "designer":
        return "designer"
    if value == "mesh":
        return "mesh"
    if value == "solver":
        return "solver"
    if value == "postproc":
        return "postproc"
    if value == "analyst":
        return "analyst"
    return "reporter"


def _stage_message(stage: StageName, status: str) -> str:
    labels = {
        "planner": "任务识别",
        "designer": "参数建模",
        "mesh": "网格生成",
        "solver": "求解执行",
        "postproc": "结果提取",
        "analyst": "工程校核",
        "reporter": "报告输出",
    }
    status_labels = {
        "running": "开始",
        "complete": "完成",
        "failed": "失败",
    }
    return f"{labels[stage]}{status_labels[status]}"

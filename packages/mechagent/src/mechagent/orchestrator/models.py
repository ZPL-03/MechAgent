"""编排层结构化数据模型。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal, Optional, cast

from pydantic import BaseModel, ConfigDict, Field

from mechagent.core.mesher import MeshResult
from mechagent.core.models import ModelParams
from mechagent.orchestrator.intent import SimulationIntent
from mechagent.orchestrator.llm_advisor import AgentLLMTrace
from mechagent.redaction import redact_sensitive_text

ErrorCode = Literal[
    "empty_request",
    "validation_case_request",
    "unsupported_request",
    "ambiguous_request",
    "missing_required_inputs",
    "missing_intent",
    "design_failed",
    "mesh_failed",
    "solver_failed",
    "postproc_failed",
    "analysis_failed",
    "report_failed",
    "unknown_error",
]
VerificationStatus = Literal["passed", "failed", "unverified"]


class TaskItem(BaseModel):
    """Planner 输出的单条任务。

    Args:
        task_id: 会话内任务编号。
        case_id: 任务类别编号。
        capability_id: 能力注册表编号。
        title: 任务标题。
        analysis_type: 分析类型。
        intent: 标准化仿真意图。
        planner_llm_trace: PlannerAgent LLM 审计记录。

    Returns:
        TaskItem: 结构化任务。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> TaskItem(task_id="TASK_1", case_id="STATIC-STRUCTURAL", title="结构静力分析")
        TaskItem(...)
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    case_id: str
    capability_id: str = ""
    title: str
    analysis_type: str = "static"
    intent: Optional[SimulationIntent] = None
    planner_llm_trace: Optional[AgentLLMTrace] = None


class ErrorRecord(BaseModel):
    """编排层错误记录。

    Args:
        node: 出错节点名称。
        code: 机器可读错误码。
        message: 错误信息。
        missing_fields: 缺失的仿真输入字段。

    Returns:
        ErrorRecord: 错误记录。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> ErrorRecord(node="solver", code="solver_failed", message="failed")
        ErrorRecord(node='solver', code='solver_failed', message='failed', missing_fields=[])
    """

    model_config = ConfigDict(extra="forbid")

    node: str
    code: ErrorCode = "unknown_error"
    message: str
    missing_fields: list[str] = Field(default_factory=list)

    @classmethod
    def from_exception(
        cls,
        node: str,
        exc: Exception,
        task: Optional[TaskItem] = None,
    ) -> "ErrorRecord":
        """从 Agent 异常生成结构化错误记录。

        Args:
            node: 出错 Agent 节点。
            exc: 捕获到的异常。
            task: 关联任务。

        Returns:
            ErrorRecord: 结构化错误记录。

        Raises:
            pydantic.ValidationError: 当字段不满足 schema 时抛出。
        """

        raw_message = str(exc)
        missing_fields = _error_missing_fields(raw_message, task)
        message = _redact_error_message(raw_message)
        return cls(
            node=node,
            code=_classify_error(node, message, missing_fields),
            message=message,
            missing_fields=missing_fields,
        )


class SolverRunSummary(BaseModel):
    """SolverAgent 输出的结构化求解摘要。

    Args:
        success: 求解器是否执行成功。
        model_case_id: 模型能力编号。
        quantity: 主结果物理量。
        unit: 主结果单位。
        predicted: 主结果计算值。
        reference: 解析或工程参考值。
        relative_error: 相对误差。
        tolerance: 验收阈值。
        passed: 工程校核是否通过。
        verification_status: 结果校核状态。
        solver: 求解器编号。
        task_title: 任务标题。
        output_files: 求解器输出文件。
        mesh_file: 求解使用的网格文件。
        mesh_metadata: 网格摘要。
        solver_llm_trace: SolverAgent LLM 审计记录。
        values: 求解器和评价阶段产生的扩展字段。

    Returns:
        SolverRunSummary: 结构化求解摘要。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> SolverRunSummary(success=True, passed=True, predicted=1.0).get("predicted")
        1.0
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    success: bool = False
    model_case_id: str = ""
    quantity: str = "result"
    unit: str = ""
    predicted: Optional[float] = None
    reference: Optional[float] = None
    relative_error: Optional[float] = None
    tolerance: Optional[float] = None
    passed: bool = False
    verification_status: VerificationStatus = "unverified"
    solver: str = ""
    task_title: str = ""
    output_files: list[Path] = Field(default_factory=list)
    mesh_file: Optional[Path] = None
    mesh_metadata: dict[str, Any] = Field(default_factory=dict)
    solver_llm_trace: Optional[AgentLLMTrace] = None
    values: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "SolverRunSummary":
        """从求解器映射结果生成结构化摘要。

        Args:
            data: 求解器和评价阶段生成的字段。

        Returns:
            SolverRunSummary: 结构化求解摘要。

        Raises:
            pydantic.ValidationError: 当字段不满足 schema 时抛出。

        Example:
            >>> SolverRunSummary.from_mapping({"success": True, "passed": True}).passed
            True
        """

        trace = data.get("solver_llm_trace")
        parsed_trace = (
            trace
            if isinstance(trace, AgentLLMTrace)
            else AgentLLMTrace.model_validate(trace)
            if isinstance(trace, dict)
            else None
        )
        output_files = data.get("output_files", [])
        if not isinstance(output_files, list):
            output_files = []
        mesh_file = data.get("mesh_file")
        predicted = _predicted_value(data)
        success = _bool_value(data.get("success"), default=False)
        passed = _bool_value(data.get("passed"), default=False)
        verification_status = _verification_status(data)
        if not success:
            passed = False
            verification_status = "failed"
        return cls(
            success=success,
            model_case_id=str(data.get("model_case_id", "")),
            quantity=str(data.get("quantity", "result")),
            unit=str(data.get("unit", "")),
            predicted=predicted,
            reference=_optional_float(data.get("reference")),
            relative_error=_optional_float(data.get("relative_error")),
            tolerance=_optional_float(data.get("tolerance")),
            passed=passed,
            verification_status=verification_status,
            solver=str(data.get("solver", "")),
            task_title=str(data.get("task_title", "")),
            output_files=[Path(item) for item in output_files],
            mesh_file=Path(mesh_file) if mesh_file else None,
            mesh_metadata=_dict_value(data.get("mesh_metadata")),
            solver_llm_trace=parsed_trace,
            values=dict(data),
        )

    def get(self, key: str, default: Any = None) -> Any:
        """按字段名读取摘要值。

        Args:
            key: 字段名。
            default: 未命中时返回的默认值。

        Returns:
            Any: 字段值。

        Raises:
            无。

        Example:
            >>> SolverRunSummary(predicted=2.0).get("predicted")
            2.0
        """

        if key in self.__class__.model_fields:
            return getattr(self, key)
        return self.values.get(key, default)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, None)
        if value is None and key not in self:
            raise KeyError(key)
        return value

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and (key in self.__class__.model_fields or key in self.values)

    def to_mapping(self) -> dict[str, Any]:
        """导出兼容工具层的映射结果。

        Args:
            无。

        Returns:
            dict[str, Any]: JSON 友好的结果映射。

        Raises:
            无。

        Example:
            >>> SolverRunSummary(predicted=1.0).to_mapping()["predicted"]
            1.0
        """

        data = _public_solver_values(self.values)
        data.update(self.model_dump(mode="json", exclude={"solver_llm_trace", "values"}))
        data["solver_llm_trace"] = _public_llm_trace(self.solver_llm_trace)
        return data


class PostProcessingSummary(BaseModel):
    """PostProcAgent 输出的结构化后处理摘要。

    Args:
        success: 求解器是否成功。
        model_case_id: 模型能力编号。
        quantity: 主结果物理量。
        unit: 主结果单位。
        predicted: 主结果计算值。
        reference: 解析或工程参考值。
        relative_error: 相对误差。
        tolerance: 验收阈值。
        passed: 工程校核是否通过。
        verification_status: 结果校核状态。
        solver: 求解器编号。
        postproc_llm_trace: PostProcAgent LLM 审计记录。
        analyst_llm_trace: AnalystAgent LLM 审计记录。
        scalars: 后处理标量结果。

    Returns:
        PostProcessingSummary: 结构化后处理摘要。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> PostProcessingSummary(predicted=1.0).get("predicted")
        1.0
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    success: bool = False
    model_case_id: str = ""
    quantity: str = "result"
    unit: str = ""
    predicted: Optional[float] = None
    reference: Optional[float] = None
    relative_error: Optional[float] = None
    tolerance: Optional[float] = None
    passed: bool = False
    verification_status: VerificationStatus = "unverified"
    solver: str = ""
    postproc_llm_trace: Optional[AgentLLMTrace] = None
    analyst_llm_trace: Optional[AgentLLMTrace] = None
    scalars: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_solver_summary(
        cls,
        solver_result: SolverRunSummary,
        postproc_llm_trace: AgentLLMTrace,
        scalars: Optional[dict[str, Any]] = None,
    ) -> "PostProcessingSummary":
        """从求解摘要生成后处理摘要。

        Args:
            solver_result: SolverAgent 输出。
            postproc_llm_trace: PostProcAgent LLM 审计记录。
            scalars: 后处理阶段生成的标量结果。

        Returns:
            PostProcessingSummary: 结构化后处理摘要。

        Raises:
            pydantic.ValidationError: 当字段不满足 schema 时抛出。

        Example:
            >>> trace = AgentLLMTrace(agent="PostProc", used=False)
            >>> summary = SolverRunSummary(predicted=1.0)
            >>> PostProcessingSummary.from_solver_summary(summary, trace).predicted
            1.0
        """

        return cls(
            success=solver_result.success,
            model_case_id=solver_result.model_case_id,
            quantity=solver_result.quantity,
            unit=solver_result.unit,
            predicted=solver_result.predicted,
            reference=solver_result.reference,
            relative_error=solver_result.relative_error,
            tolerance=solver_result.tolerance,
            passed=solver_result.passed,
            verification_status=solver_result.verification_status,
            solver=solver_result.solver,
            postproc_llm_trace=postproc_llm_trace,
            scalars=_merged_scalars(solver_result, scalars),
        )

    def get(self, key: str, default: Any = None) -> Any:
        """按字段名读取后处理摘要值。"""

        if key in self.__class__.model_fields:
            return getattr(self, key)
        return self.scalars.get(key, default)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, None)
        if value is None and key not in self:
            raise KeyError(key)
        return value

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and (key in self.__class__.model_fields or key in self.scalars)

    def to_mapping(self) -> dict[str, Any]:
        """导出 JSON 友好的后处理摘要。"""

        data = _public_solver_values(self.scalars)
        data.update(
            self.model_dump(
                mode="json",
                exclude={"postproc_llm_trace", "analyst_llm_trace", "scalars"},
            )
        )
        data["postproc_llm_trace"] = _public_llm_trace(self.postproc_llm_trace)
        data["analyst_llm_trace"] = _public_llm_trace(self.analyst_llm_trace)
        return data


class DesignAgentOutput(BaseModel):
    """DesignerAgent 输出。

    Args:
        model_params: 结构化仿真参数。
        designer_llm_trace: DesignerAgent LLM 审计记录。

    Returns:
        DesignAgentOutput: Designer 节点输出。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    model_params: ModelParams
    designer_llm_trace: AgentLLMTrace


class MeshAgentOutput(BaseModel):
    """MeshAgent 输出。

    Args:
        mesh_result: 网格生成结果。
        mesh_llm_trace: MeshAgent LLM 审计记录。

    Returns:
        MeshAgentOutput: Mesh 节点输出。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    mesh_result: MeshResult
    mesh_llm_trace: AgentLLMTrace


class TaskRunRecord(BaseModel):
    """单条任务运行记录。

    Args:
        task: 任务描述。
        model_params: 结构化仿真参数。
        mesh_result: 网格生成结果。
        solver_result: 求解摘要。
        analysis_text: 工程分析文本。
        designer_llm_trace: DesignerAgent LLM 审计记录。
        mesh_llm_trace: MeshAgent LLM 审计记录。
        error: 任务错误记录。

    Returns:
        TaskRunRecord: 单条任务运行记录。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> TaskRunRecord(task=TaskItem(task_id="TASK_1", case_id="STATIC-STRUCTURAL", title="x"))
        TaskRunRecord(...)
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    task: TaskItem
    model_params: Optional[ModelParams] = None
    mesh_result: Optional[MeshResult] = None
    solver_result: SolverRunSummary = Field(default_factory=SolverRunSummary)
    post_summary: PostProcessingSummary = Field(default_factory=PostProcessingSummary)
    analysis_text: str = ""
    designer_llm_trace: Optional[AgentLLMTrace] = None
    mesh_llm_trace: Optional[AgentLLMTrace] = None
    figures: list[Path] = Field(default_factory=list)
    error: Optional[ErrorRecord] = None


class WorkflowResult(BaseModel):
    """完整工作流结果。

    Args:
        success: 工作流是否成功。
        request: 用户请求文本。
        tasks: 任务运行记录。
        report: Markdown 报告。
        errors: 错误记录。
        reporter_llm_trace: ReporterAgent LLM 审计记录。

    Returns:
        WorkflowResult: 完整工作流结果。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> WorkflowResult(success=True, request="结构静力分析")
        WorkflowResult(success=True, request='结构静力分析', ...)
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    request: str
    tasks: list[TaskRunRecord] = Field(default_factory=list)
    report: str = ""
    work_dir: Optional[Path] = None
    report_path: Optional[Path] = None
    errors: list[ErrorRecord] = Field(default_factory=list)
    reporter_llm_trace: Optional[AgentLLMTrace] = None

    def summary(self) -> dict[str, Any]:
        """导出 SDK 摘要。

        Args:
            无。

        Returns:
            dict[str, Any]: 结构化摘要。

        Raises:
            无。

        Example:
            >>> WorkflowResult(success=True, request="x").summary()["success"]
            True
        """

        return {
            "success": self.success,
            "work_dir": str(self.work_dir) if self.work_dir else None,
            "report_path": str(self.report_path) if self.report_path else None,
            "reporter_llm_trace": _public_llm_trace(self.reporter_llm_trace),
            "tasks": [
                {
                    "task_id": record.task.task_id,
                    "case_id": record.task.case_id,
                    "capability_id": record.task.capability_id,
                    "title": record.task.title,
                    "analysis_type": record.task.analysis_type,
                    "intent": record.task.intent.model_dump(mode="json")
                    if record.task.intent
                    else None,
                    "planner_llm_trace": _public_llm_trace(record.task.planner_llm_trace),
                    "designer_llm_trace": _public_llm_trace(record.designer_llm_trace),
                    "model_params": record.model_params.model_dump(mode="json")
                    if record.model_params
                    else None,
                    "mesh_llm_trace": _public_llm_trace(record.mesh_llm_trace),
                    "mesh_result": record.mesh_result.model_dump(mode="json")
                    if record.mesh_result
                    else None,
                    "solver_result": _public_solver_summary(record.solver_result),
                    "post_summary": _public_post_summary(record.post_summary),
                    "analysis_text": record.analysis_text,
                    "error": record.error.model_dump(mode="json") if record.error else None,
                }
                for record in self.tasks
            ],
            "errors": [error.model_dump() for error in self.errors],
        }


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _bool_value(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return default
        if value == 0:
            return False
        if value == 1:
            return True
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y", "pass", "passed", "ok", "success"}:
            return True
        if text in {"false", "0", "no", "n", "fail", "failed", "error", "failure"}:
            return False
    return default


def _predicted_value(data: dict[str, Any]) -> Optional[float]:
    predicted = _optional_float(data.get("predicted"))
    if predicted is not None:
        return predicted
    quantity = data.get("quantity")
    if isinstance(quantity, str) and quantity:
        return _optional_float(data.get(quantity))
    return None


def _verification_status(data: dict[str, Any]) -> VerificationStatus:
    value = str(data.get("verification_status", "")).lower()
    if value in {"passed", "failed", "unverified"}:
        return cast(VerificationStatus, value)

    has_reference_check = all(
        _optional_float(data.get(key)) is not None
        for key in ("reference", "relative_error", "tolerance")
    )
    if has_reference_check:
        return "passed" if _bool_value(data.get("passed"), default=False) else "failed"
    if _bool_value(data.get("success"), default=False):
        return "unverified"
    return "failed"


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _public_llm_trace(trace: Optional[AgentLLMTrace]) -> dict[str, Any] | None:
    if trace is None:
        return None
    return {
        "agent": trace.agent,
        "used": trace.used,
        "error": redact_sensitive_text(trace.error) if trace.error is not None else None,
        "prompt_chars": len(trace.prompt),
        "response_chars": len(trace.response),
    }


def _public_solver_summary(summary: SolverRunSummary) -> dict[str, Any]:
    data = summary.model_dump(
        mode="json",
        exclude={"solver_llm_trace", "values"},
    )
    data["solver_llm_trace"] = _public_llm_trace(summary.solver_llm_trace)
    data["values"] = _public_solver_values(summary.values)
    return data


def _public_post_summary(summary: PostProcessingSummary) -> dict[str, Any]:
    data = summary.model_dump(
        mode="json",
        exclude={"postproc_llm_trace", "analyst_llm_trace"},
    )
    data["postproc_llm_trace"] = _public_llm_trace(summary.postproc_llm_trace)
    data["analyst_llm_trace"] = _public_llm_trace(summary.analyst_llm_trace)
    data["scalars"] = _public_solver_values(summary.scalars)
    return data


def _public_solver_values(values: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _public_value(value) for key, value in values.items()}


def _public_value(value: Any) -> Any:
    if isinstance(value, AgentLLMTrace):
        return _public_llm_trace(value)
    if isinstance(value, BaseModel):
        return _public_value(value.model_dump(mode="json"))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        if _looks_like_trace_mapping(value):
            return _public_trace_mapping(value)
        return {str(key): _public_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    return value


def _looks_like_trace_mapping(value: dict[Any, Any]) -> bool:
    keys = {str(key) for key in value}
    return {"agent", "used"}.issubset(keys) and bool({"prompt", "response"} & keys)


def _public_trace_mapping(value: dict[Any, Any]) -> dict[str, Any]:
    prompt = str(value.get("prompt", ""))
    response = str(value.get("response", ""))
    error = value.get("error")
    return {
        "agent": str(value.get("agent", "")),
        "used": _bool_value(value.get("used"), default=False),
        "error": redact_sensitive_text(str(error)) if error is not None else None,
        "prompt_chars": len(prompt),
        "response_chars": len(response),
    }


def _merged_scalars(
    solver_result: SolverRunSummary,
    postproc_scalars: Optional[dict[str, Any]],
) -> dict[str, Any]:
    scalars = solver_result.to_mapping()
    if postproc_scalars:
        scalars.update(postproc_scalars)
    return scalars


def _error_missing_fields(message: str, task: Optional[TaskItem]) -> list[str]:
    if task is not None and task.intent is not None and task.intent.missing_fields:
        return list(task.intent.missing_fields)

    marker = "缺少必要参数:"
    if marker not in message:
        return []
    tail = message.split(marker, 1)[1].strip().rstrip("。")
    return [item for item in tail.split("、") if item]


def _redact_error_message(message: str) -> str:
    return redact_sensitive_text(message)


def _classify_error(node: str, message: str, missing_fields: list[str]) -> ErrorCode:
    if node == "planner":
        if "request 不能为空" in message:
            return "empty_request"
        if "标准验证算例属于独立测试入口" in message:
            return "validation_case_request"
        if "无法识别" in message:
            return "unsupported_request"

    if "多个几何类型" in message or "单个仿真任务" in message:
        return "ambiguous_request"

    if missing_fields:
        return "missing_required_inputs"

    if node == "designer":
        if "TaskItem.intent" in message:
            return "missing_intent"
        return "design_failed"
    if node == "mesh":
        return "mesh_failed"
    if node == "solver":
        return "solver_failed"
    if node == "postproc":
        return "postproc_failed"
    if node == "analyst":
        return "analysis_failed"
    if node == "reporter":
        return "report_failed"
    return "unknown_error"

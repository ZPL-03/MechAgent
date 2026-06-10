"""MechAgent SDK 接口。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional, Union, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field

from mechagent.config import MechAgentConfig
from mechagent.orchestrator import (
    ErrorRecord,
    SequentialWorkflow,
    TaskItem,
    TaskRunRecord,
    WorkflowResult,
)
from mechagent.orchestrator.agents import PlannerAgent
from mechagent.orchestrator.graph import build_graph
from mechagent.orchestrator.llm_advisor import AgentLLMTrace

_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")


class MechAgentResult(BaseModel):
    """MechAgent 运行结果。

    Args:
        report: Markdown 报告文本。
        summary: 结构化摘要。
        output_dir: 输出目录。
        report_path: 已写入的报告路径。

    Returns:
        MechAgentResult: SDK 和 CLI 共用结果对象。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> MechAgentResult(report="# ok", summary={"success": True})
        MechAgentResult(report='# ok', summary={'success': True}, output_dir=None)
    """

    model_config = ConfigDict(extra="forbid")

    report: str
    summary: dict[str, Any] = Field(default_factory=dict)
    output_dir: Optional[Path] = None
    report_path: Optional[Path] = None

    def save_report(self, path: Union[str, Path]) -> Path:
        """保存 Markdown 报告。

        Args:
            path: 报告文件路径。

        Returns:
            Path: 写入完成的报告路径。

        Raises:
            OSError: 当目标目录无法创建或文件无法写入时抛出。

        Example:
            >>> result = MechAgentResult(report="# ok")
            >>> result.save_report("mechagent_output/report.md").suffix
            '.md'
        """

        report_path = Path(path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(self.report, encoding="utf-8")
        return report_path


class MechAgentInspection(BaseModel):
    """自然语言仿真请求预检结果。

    Args:
        success: Planner 是否完成任务识别。
        ready: 识别到的任务是否具备执行所需输入。
        request: 原始自然语言请求。
        tasks: 任务识别结果。
        errors: 预检错误记录。
    Returns:
        MechAgentInspection: SDK、CLI 和 Studio 共用的预检结果。
    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。
    Example:
        >>> MechAgentInspection(success=True, ready=True, request="x").ready
        True
    """

    model_config = ConfigDict(extra="forbid")

    success: bool = False
    ready: bool = False
    request: str = ""
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class MechAgent:
    """自然语言驱动仿真工作流的 SDK 接口。

    Args:
        config: 已加载的配置对象。

    Returns:
        MechAgent: SDK 实例。

    Raises:
        FileNotFoundError: 当配置文件不存在时抛出。

    Example:
        >>> agent = MechAgent.from_config("config/mechagent.yaml")
        >>> isinstance(agent, MechAgent)
        True
    """

    def __init__(self, config: MechAgentConfig) -> None:
        self.config = config

    @classmethod
    def from_config(cls, path: Union[str, Path]) -> "MechAgent":
        """从 YAML 配置文件创建 SDK 实例。

        Args:
            path: YAML 配置文件路径。

        Returns:
            MechAgent: SDK 实例。

        Raises:
            FileNotFoundError: 当配置文件不存在时抛出。
            yaml.YAMLError: 当 YAML 解析失败时抛出。

        Example:
            >>> MechAgent.from_config("config/mechagent.yaml")
            <mechagent.app.MechAgent object at ...>
        """

        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(config_path)
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        expanded = _expand_env(cast(dict[str, Any], data), _config_env(config_path))
        return cls(config=MechAgentConfig.model_validate(expanded))

    def run(
        self,
        request: str,
        use_llm_agents: Optional[bool] = None,
    ) -> MechAgentResult:
        """执行自然语言仿真请求。

        Args:
            request: 用户自然语言请求。
            use_llm_agents: 单次运行是否启用 Agent LLM trace；为 None 时使用配置值。

        Returns:
            MechAgentResult: 运行结果。

        Raises:
            OSError: 当输出目录或报告文件无法写入时抛出。

        Example:
            >>> agent = MechAgent(MechAgentConfig())
            >>> result = agent.run("长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，向下1000N")
            >>> result.summary["success"]
            True
        """

        active_config = self.config
        if use_llm_agents is not None:
            active_config = self.config.model_copy(deep=True)
            active_config.orchestrator.use_llm_agents = use_llm_agents
        if active_config.orchestrator.mode.lower() == "dag":
            result = _run_langgraph_workflow(active_config, request)
        else:
            workflow = SequentialWorkflow(active_config)
            result = workflow.run(request)
        return MechAgentResult(
            report=result.report,
            summary=result.summary(),
            output_dir=result.work_dir,
            report_path=result.report_path,
        )

    def inspect(
        self,
        request: str,
        use_llm_agents: Optional[bool] = None,
    ) -> MechAgentInspection:
        """预检自然语言请求，不执行网格、求解和后处理。

        Args:
            request: 用户自然语言仿真请求。
            use_llm_agents: 单次预检是否启用 Planner LLM；为 None 时使用配置值。
        Returns:
            MechAgentInspection: 任务识别、缺参和错误信息。
        Raises:
            pydantic.ValidationError: 当结果字段不满足 schema 时抛出。
        Example:
            >>> agent = MechAgent(MechAgentConfig())
            >>> agent.inspect("长1000mm钢悬臂梁，一端固支，端部向下1000N").success
            True
        """

        active_config = self.config
        if use_llm_agents is not None:
            active_config = self.config.model_copy(deep=True)
            active_config.orchestrator.use_llm_agents = use_llm_agents

        text = request.strip()
        if not text:
            error = ErrorRecord(
                node="planner",
                code="empty_request",
                message="request 不能为空。",
            )
            return MechAgentInspection(
                success=False,
                ready=False,
                request=request,
                errors=[error.model_dump(mode="json")],
            )

        try:
            tasks = PlannerAgent(active_config).plan(text)
        except Exception as exc:
            error = ErrorRecord.from_exception("planner", exc)
            return MechAgentInspection(
                success=False,
                ready=False,
                request=request,
                errors=[error.model_dump(mode="json")],
            )

        task_payloads = [_inspection_task_payload(task) for task in tasks]
        ready = bool(task_payloads) and all(bool(task.get("complete")) for task in task_payloads)
        return MechAgentInspection(
            success=True,
            ready=ready,
            request=request,
            tasks=task_payloads,
            errors=[],
        )


def _inspection_task_payload(task: TaskItem) -> dict[str, Any]:
    data = task.model_dump(mode="json", exclude={"planner_llm_trace"})
    intent = getattr(task, "intent", None)
    trace = getattr(task, "planner_llm_trace", None)
    missing_fields = list(getattr(intent, "missing_fields", []) or [])
    data["intent"] = intent.model_dump(mode="json") if intent is not None else None
    data["complete"] = not missing_fields
    data["missing_fields"] = missing_fields
    data["geometry_type"] = getattr(intent, "geometry_type", None) if intent is not None else None
    data["confidence"] = getattr(intent, "confidence", None) if intent is not None else None
    data["source"] = getattr(intent, "source", "") if intent is not None else ""
    data["planner_llm_trace"] = _public_trace(trace)
    return data


def _public_trace(trace: AgentLLMTrace | None) -> dict[str, Any] | None:
    if trace is None:
        return None
    return {
        "agent": trace.agent,
        "used": trace.used,
        "error": trace.error,
        "prompt_chars": len(trace.prompt),
        "response_chars": len(trace.response),
    }


def _config_env(config_path: Path) -> dict[str, str]:
    env = _dotenv_values(Path(".env"))
    config_env = config_path.parent / ".env"
    if config_path.parent.resolve() != Path(".").resolve():
        env.update(_dotenv_values(config_env))
    env.update(dict(os.environ))
    return env


def _dotenv_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        key = name.strip()
        if key:
            values[key] = value.strip()
    return values


def _expand_env(value: Any, env: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env(item, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item, env) for item in value]
    if isinstance(value, str):
        return _ENV_PATTERN.sub(
            lambda match: env.get(match.group(1)) or (match.group(2) or ""),
            value,
        )
    return value


def _run_langgraph_workflow(config: MechAgentConfig, request: str) -> WorkflowResult:
    graph = build_graph(config)
    state = graph.invoke({"user_request": request})
    raw_records = cast(list[Any], state.get("records", []))
    raw_errors = cast(list[Any], state.get("errors", []))
    records = [TaskRunRecord.model_validate(item) for item in raw_records]
    errors = [ErrorRecord.model_validate(item) for item in raw_errors]
    reporter_trace_value = state.get("reporter_trace")
    work_dir_value = state.get("work_dir")
    report_path_value = state.get("report_path")
    return WorkflowResult(
        success=bool(state.get("success", False)),
        request=request,
        tasks=records,
        report=str(state.get("report", "")),
        work_dir=Path(str(work_dir_value)) if work_dir_value else None,
        report_path=Path(str(report_path_value)) if report_path_value else None,
        errors=errors,
        reporter_llm_trace=AgentLLMTrace.model_validate(reporter_trace_value)
        if reporter_trace_value
        else None,
    )

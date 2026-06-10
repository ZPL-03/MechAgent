"""Typer CLI 接口。"""

from __future__ import annotations

import json
import math
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from mechagent import MechAgent
from mechagent.config import config_to_public_dict
from mechagent.core.validation import run_core_benchmarks
from mechagent.examples import SimulationExample, all_examples
from mechagent.knowledge import build_index, query_index, standardize_documents
from mechagent.llm import LLMConfig, check_connection
from mechagent.orchestrator.capabilities import SimulationCapability, all_capabilities
from mechagent.ui import run_studio

app = typer.Typer(help="MechAgent 命令行工具。")
config_app = typer.Typer(help="配置管理。")
knowledge_app = typer.Typer(help="知识库管理。")
app.add_typer(config_app, name="config")
app.add_typer(knowledge_app, name="knowledge")
console = Console()


class StudioView(str, Enum):
    """Studio 初始 3D 视图。"""

    geometry = "geometry"
    mesh = "mesh"
    result = "result"


@app.command()
def studio(
    config: Path = typer.Option(Path("config/mechagent.yaml"), help="配置文件路径。"),
    host: str = typer.Option("127.0.0.1", help="Studio 服务监听地址。"),
    port: int = typer.Option(8765, min=1, max=65535, help="Studio 服务监听端口。"),
    open_browser: bool = typer.Option(False, "--open-browser", help="启动后打开浏览器。"),
    request: Optional[str] = typer.Option(
        None, "--request", "-r", help="打开工作台时填入的自然语言请求。"
    ),
    llm_agents: bool = typer.Option(False, "--llm-agents", help="打开工作台时启用参数补全开关。"),
    view: StudioView = typer.Option(
        StudioView.geometry,
        "--view",
        help="打开工作台时选中的 3D 视图。",
    ),
    auto_run: bool = typer.Option(False, "--auto-run", help="打开工作台后自动提交当前请求。"),
) -> None:
    """启动 MechAgent Studio 工程工作台。"""

    if auto_run and not (request and request.strip()):
        raise typer.BadParameter("--auto-run 需要同时提供 --request。")

    run_studio(
        host=host,
        port=port,
        config=config,
        open_browser=open_browser,
        request=request,
        use_llm_agents=llm_agents,
        view=view.value,
        auto_run=auto_run,
    )


@app.command()
def capabilities(
    json_output: bool = typer.Option(False, "--json", help="输出结构化 JSON 能力清单。"),
    examples: bool = typer.Option(False, "--examples", help="显示每个能力的自然语言示例。"),
) -> None:
    """显示已注册仿真能力、工具绑定和示例请求。"""

    items = all_capabilities()
    rows = [_capability_payload(item) for item in items]
    if json_output:
        _echo_json({"capabilities": rows})
        return

    table = Table(title="MechAgent 已注册仿真能力", expand=True)
    table.add_column("能力编号", no_wrap=True)
    table.add_column("名称", no_wrap=True)
    table.add_column("分析", no_wrap=True)
    table.add_column("物理域", no_wrap=True)
    table.add_column("求解器", no_wrap=True)
    table.add_column("网格器", no_wrap=True)
    table.add_column("模型", overflow="fold")
    for row in rows:
        table.add_row(
            _text(row.get("capability_id"), "-"),
            _text(row.get("title"), "-"),
            _text(row.get("analysis_type"), "-"),
            _text(row.get("physics_domain"), "-"),
            _text(row.get("solver"), "-"),
            _text(row.get("mesher"), "-"),
            "、".join(row["model_case_ids"]) if row["model_case_ids"] else "-",
        )
    console.print(table)
    for row in rows:
        model_case_ids = "、".join(row["model_case_ids"]) if row["model_case_ids"] else "-"
        console.print(f"{row['capability_id']} 模型编号: {model_case_ids}")

    if examples:
        for row in rows:
            console.print(f"\n[bold]{row['capability_id']} 示例[/bold]")
            for index, request in enumerate(row["examples"], start=1):
                console.print(f"{index}. {request}")


@app.command()
def examples(
    capability: Optional[str] = typer.Option(None, "--capability", help="按能力编号过滤。"),
    model_case: Optional[str] = typer.Option(None, "--model-case", help="按模型编号过滤。"),
    geometry: Optional[str] = typer.Option(None, "--geometry", help="按几何类型过滤。"),
    limit: Optional[int] = typer.Option(None, "--limit", min=1, help="最多显示的示例数量。"),
    json_output: bool = typer.Option(False, "--json", help="输出结构化 JSON 示例清单。"),
) -> None:
    """显示自然语言仿真示例。"""

    rows = [
        _example_payload(item)
        for item in all_examples(
            capability_id=capability,
            model_case_id=model_case,
            geometry_type=geometry,
        )
    ]
    if limit is not None:
        rows = rows[:limit]

    if json_output:
        _echo_json({"examples": rows})
        return

    table = Table(title="MechAgent 自然语言仿真示例", expand=True)
    table.add_column("编号", no_wrap=True)
    table.add_column("标题", no_wrap=True)
    table.add_column("几何", no_wrap=True)
    table.add_column("载荷", no_wrap=True)
    table.add_column("模型", no_wrap=True)
    table.add_column("请求", overflow="fold")
    for row in rows:
        table.add_row(
            _text(row.get("example_id"), "-"),
            _text(row.get("title"), "-"),
            _text(row.get("geometry_type"), "-"),
            _text(row.get("load_type"), "-"),
            _text(row.get("model_case_id"), "-"),
            _text(row.get("request"), "-"),
        )
    console.print(table)
    console.print(f"共 {len(rows)} 条示例。")


@app.command()
def run(
    request: str = typer.Argument(..., help="自然语言仿真请求。"),
    config: Path = typer.Option(Path("config/mechagent.yaml"), help="配置文件路径。"),
    json_output: bool = typer.Option(False, "--json", help="输出结构化 JSON 摘要。"),
    llm_agents: bool = typer.Option(False, "--llm-agents", help="本次运行启用 Agent LLM trace。"),
) -> None:
    """执行单次仿真请求。"""

    agent = MechAgent.from_config(config)
    result = agent.run(request, use_llm_agents=True if llm_agents else None)
    if json_output:
        _echo_json(result.summary)
        if not result.summary.get("success", False):
            raise typer.Exit(code=1)
        return

    console.print(result.report)
    _print_run_summary(result.summary)
    if result.report_path:
        console.print(f"报告已写入: {result.report_path}")
    if result.output_dir:
        console.print(f"输出目录: {result.output_dir}")
    if not result.summary.get("success", False):
        raise typer.Exit(code=1)


@app.command()
def inspect(
    request: str = typer.Argument(..., help="自然语言仿真请求。"),
    config: Path = typer.Option(Path("config/mechagent.yaml"), help="配置文件路径。"),
    json_output: bool = typer.Option(False, "--json", help="输出结构化 JSON 预检结果。"),
    llm_agents: bool = typer.Option(False, "--llm-agents", help="本次预检启用 Planner LLM。"),
) -> None:
    """预检自然语言请求，不执行求解。"""

    agent = MechAgent.from_config(config)
    inspection = agent.inspect(request, use_llm_agents=True if llm_agents else None)
    payload = inspection.model_dump(mode="json")
    if json_output:
        _echo_json(payload)
        if not inspection.ready:
            raise typer.Exit(code=1)
        return

    _print_inspection(payload)
    if not inspection.ready:
        raise typer.Exit(code=1)


@app.command()
def benchmark(
    config: Path = typer.Option(Path("config/mechagent.yaml"), help="配置文件路径。"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON。"),
) -> None:
    """运行核心标准验证算例。"""

    agent = MechAgent.from_config(config)
    calculix = agent.config.solver.calculix
    results = run_core_benchmarks(
        solver_path=calculix.path,
        num_cpus=calculix.num_cpus,
        timeout=calculix.timeout,
    )
    rows = [
        {
            "case_id": item.case_id,
            "description": item.description,
            "quantity": item.quantity,
            "unit": item.unit,
            "solver": item.solver,
            "predicted": item.predicted,
            "reference": item.reference,
            "relative_error": item.relative_error,
            "tolerance": item.tolerance,
            "passed": item.passed,
        }
        for item in results
    ]
    if json_output:
        _echo_json(rows)
        raise typer.Exit(code=0 if all(item.passed for item in results) else 1)

    table = Table(title="MechAgent 标准验证算例")
    table.add_column("算例")
    table.add_column("描述")
    table.add_column("物理量")
    table.add_column("求解器")
    table.add_column("计算值")
    table.add_column("参考值")
    table.add_column("相对误差")
    table.add_column("阈值")
    table.add_column("状态")
    for item in results:
        table.add_row(
            item.case_id,
            item.description,
            f"{item.quantity} ({item.unit})",
            item.solver,
            f"{item.predicted:.8g}",
            f"{item.reference:.8g}",
            f"{item.relative_error:.4%}",
            f"{item.tolerance:.2%}",
            "通过" if item.passed else "失败",
        )
    console.print(table)
    raise typer.Exit(code=0 if all(item.passed for item in results) else 1)


@config_app.command("validate")
def validate_config(
    config: Path = typer.Option(Path("config/mechagent.yaml"), help="配置文件路径。"),
    llm: bool = typer.Option(False, "--llm", help="同时检查 LLM 远端连接。"),
) -> None:
    """验证配置文件和可选 LLM 连接。"""

    agent = MechAgent.from_config(config)
    console.print(f"配置文件有效: {config}")
    if llm:
        settings = agent.config.llm
        health = check_connection(
            LLMConfig(
                base_url=settings.base_url,
                api_key=settings.api_key,
                model=settings.model,
                temperature=settings.temperature,
            )
        )
        console.print(health.message)
        if not health.ok:
            raise typer.Exit(code=1)


@config_app.command("show")
def show_config(
    config: Path = typer.Option(Path("config/mechagent.yaml"), help="配置文件路径。"),
) -> None:
    """显示隐藏敏感字段后的配置。"""

    agent = MechAgent.from_config(config)
    _echo_json(config_to_public_dict(agent.config))


@knowledge_app.command("build")
def build_knowledge(
    config: Path = typer.Option(Path("config/mechagent.yaml"), help="配置文件路径。"),
) -> None:
    """标准化知识源文档并构建本地知识库索引。"""

    agent = MechAgent.from_config(config)
    document_count = standardize_documents(
        agent.config.knowledge.raw_dir,
        agent.config.knowledge.external_dir,
    )
    count = build_index(
        agent.config.knowledge.external_dir,
        agent.config.knowledge.index_path,
        chunk_size=agent.config.knowledge.chunk_size,
        chunk_overlap=agent.config.knowledge.chunk_overlap,
    )
    console.print(f"知识库构建完成: {document_count} 个文档，{count} 个文本块")


@knowledge_app.command("query")
def query_knowledge(
    query: str = typer.Argument(..., help="检索文本。"),
    config: Path = typer.Option(Path("config/mechagent.yaml"), help="配置文件路径。"),
    top_k: int = typer.Option(5, min=1, help="返回数量。"),
) -> None:
    """检索本地知识库索引。"""

    agent = MechAgent.from_config(config)
    index_path = agent.config.knowledge.index_path
    if not index_path.exists():
        console.print(f"知识库索引不存在: {index_path}")
        raise typer.Exit(code=1)
    hits = query_index(
        index_path,
        query,
        top_k=top_k,
        bm25_weight=agent.config.knowledge.bm25_weight,
        tfidf_weight=agent.config.knowledge.tfidf_weight,
    )
    table = Table(title="知识库检索结果")
    table.add_column("doc_id")
    table.add_column("score")
    table.add_column("source")
    table.add_column("text")
    for hit in hits:
        preview = hit.text[:120] + ("..." if len(hit.text) > 120 else "")
        table.add_row(hit.doc_id, f"{hit.score:.6f}", hit.source, preview)
    console.print(table)


def _print_run_summary(summary: dict[str, Any]) -> None:
    tasks = summary.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return
    table = Table(title="任务摘要")
    table.add_column("任务")
    table.add_column("算例")
    table.add_column("状态")
    table.add_column("主结果")
    table.add_column("相对误差")
    table.add_column("求解器")
    for item in tasks:
        task = item if isinstance(item, dict) else {}
        solver = _dict_value(task.get("solver_result"))
        error = _dict_value(task.get("error"))
        table.add_row(
            _text(task.get("task_id"), "-"),
            _text(solver.get("model_case_id") or task.get("case_id"), "-"),
            _task_status(task, solver, error),
            _main_result(solver),
            _percent_text(solver.get("relative_error"), precision=4),
            _text(solver.get("solver"), "-"),
        )
    console.print(table)


def _print_inspection(inspection: dict[str, Any]) -> None:
    table = Table(title="请求预检", expand=True)
    table.add_column("任务", no_wrap=True)
    table.add_column("能力", no_wrap=True)
    table.add_column("几何", no_wrap=True)
    table.add_column("完整度", no_wrap=True)
    table.add_column("缺项", no_wrap=True)
    missing_details: list[tuple[str, list[str]]] = []
    tasks = inspection.get("tasks")
    if isinstance(tasks, list) and tasks:
        for item in tasks:
            task = item if isinstance(item, dict) else {}
            missing = task.get("missing_fields")
            missing_values = [str(value) for value in missing] if isinstance(missing, list) else []
            task_id = _text(task.get("task_id"), "-")
            if missing_values:
                missing_details.append((task_id, missing_values))
            table.add_row(
                task_id,
                _text(task.get("capability_id"), "-"),
                _text(task.get("geometry_type"), "-"),
                "可执行" if bool(task.get("complete")) else "需补充",
                f"{len(missing_values)} 项" if missing_values else "-",
            )
    else:
        errors = inspection.get("errors")
        message = "-"
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            message = _text(errors[0].get("message"), "-")
        table.add_row("-", "-", "-", "无法识别", message)
    console.print(table)
    if missing_details:
        console.print("补参建议")
        for task_id, missing_values in missing_details:
            console.print(f"- {task_id}: {'、'.join(missing_values)}")


def _capability_payload(capability: SimulationCapability) -> dict[str, Any]:
    return {
        "capability_id": capability.capability_id,
        "title": capability.title,
        "analysis_type": capability.analysis_type,
        "physics_domain": capability.physics_domain,
        "solver": capability.solver_name,
        "mesher": capability.mesher_name,
        "task_case_id": capability.task_case_id,
        "model_case_ids": list(capability.model_case_ids),
        "keywords": list(capability.planner_keywords),
        "examples": list(capability.example_requests),
    }


def _example_payload(example: SimulationExample) -> dict[str, Any]:
    return example.to_payload()


def _echo_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=True, indent=2))


def _task_status(
    task: dict[str, Any],
    solver: dict[str, Any],
    error: dict[str, Any],
) -> str:
    if error:
        return "失败"
    status = str(solver.get("verification_status") or "").lower()
    if status == "passed":
        return "通过"
    if status == "failed":
        return "失败"
    if _bool_value(task.get("success")) or _bool_value(solver.get("success")):
        return "完成"
    return "待确认"


def _main_result(solver: dict[str, Any]) -> str:
    value = _number_value(solver.get("predicted"))
    if value is None:
        quantity = solver.get("quantity")
        if isinstance(quantity, str):
            value = _number_value(solver.get(quantity))
    if value is None:
        return "-"
    unit = str(solver.get("unit") or "").strip()
    return f"{value:.6g} {unit}".strip()


def _percent_text(value: Any, *, precision: int) -> str:
    number = _number_value(value)
    if number is None:
        return "-"
    return f"{number:.{precision}%}"


def _number_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "passed", "success"}
    return False


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any, default: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


if __name__ == "__main__":
    app()

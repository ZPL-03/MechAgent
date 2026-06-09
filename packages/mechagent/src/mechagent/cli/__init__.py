"""Typer CLI 接口。"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from mechagent import MechAgent
from mechagent.config import config_to_public_dict
from mechagent.core.validation import run_core_benchmarks
from mechagent.knowledge import build_index, query_index, standardize_documents
from mechagent.llm import LLMConfig, check_connection
from mechagent.ui import run_studio

app = typer.Typer(help="MechAgent 命令行工具。")
config_app = typer.Typer(help="配置管理。")
knowledge_app = typer.Typer(help="知识库管理。")
app.add_typer(config_app, name="config")
app.add_typer(knowledge_app, name="knowledge")
console = Console()


@app.command()
def studio(
    config: Path = typer.Option(Path("config/mechagent.yaml"), help="配置文件路径。"),
    host: str = typer.Option("127.0.0.1", help="Studio 服务监听地址。"),
    port: int = typer.Option(8765, min=1, max=65535, help="Studio 服务监听端口。"),
    open_browser: bool = typer.Option(False, "--open-browser", help="启动后打开浏览器。"),
) -> None:
    """启动 MechAgent Studio 工程工作台。"""

    run_studio(host=host, port=port, config=config, open_browser=open_browser)


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
        typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
        if not result.summary.get("success", False):
            raise typer.Exit(code=1)
        return

    console.print(result.report)
    if result.report_path:
        console.print(f"报告已写入: {result.report_path}")
    if not result.summary.get("success", False):
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
        console.print(json.dumps(rows, ensure_ascii=False, indent=2))
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
    console.print(json.dumps(config_to_public_dict(agent.config), ensure_ascii=False, indent=2))


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


if __name__ == "__main__":
    app()

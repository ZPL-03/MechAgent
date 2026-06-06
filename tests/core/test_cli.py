"""CLI 行为测试。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch
from typer.testing import CliRunner

from mechagent.cli import app
from mechagent.core.validation import BenchmarkResult


def test_cli_main_module_import_has_no_side_effect() -> None:
    module = importlib.import_module("mechagent.cli.__main__")

    assert callable(module.main)


def test_cli_run_returns_nonzero_for_failed_request(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"""
output:
  output_dir: {tmp_path.as_posix()}/runs
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "分析一个完全未知的任务",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 1
    assert "错误诊断" in result.output
    assert "unsupported_request" in result.output
    assert "无法识别" in result.output


def test_cli_run_json_returns_structured_failed_summary(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"""
output:
  output_dir: {tmp_path.as_posix()}/runs
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "分析一个完全未知的任务",
            "--config",
            str(config_path),
            "--json",
        ],
    )

    summary = json.loads(result.output)
    assert result.exit_code == 1
    assert summary["success"] is False
    assert summary["errors"][0]["code"] == "unsupported_request"
    assert summary["tasks"][0]["error"]["node"] == "planner"


def test_cli_run_json_returns_structured_empty_request_summary(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"""
output:
  output_dir: {tmp_path.as_posix()}/runs
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            "   ",
            "--config",
            str(config_path),
            "--json",
        ],
    )

    summary = json.loads(result.output)
    assert result.exit_code == 1
    assert summary["success"] is False
    assert summary["errors"][0]["code"] == "empty_request"
    assert summary["tasks"][0]["error"]["node"] == "planner"


def test_cli_run_llm_agents_enables_runtime_trace(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, bool | None] = {}

    class FakeAgent:
        def run(
            self,
            request: str,
            use_llm_agents: bool | None = None,
        ) -> SimpleNamespace:
            captured["use_llm_agents"] = use_llm_agents
            captured["request_seen"] = bool(request.strip())
            return SimpleNamespace(summary={"success": True}, report="", report_path=None)

    monkeypatch.setattr("mechagent.cli.MechAgent.from_config", lambda _path: FakeAgent())
    runner = CliRunner()

    result = runner.invoke(app, ["run", "solve a beam", "--llm-agents", "--json"])

    assert result.exit_code == 0
    assert captured == {"use_llm_agents": True, "request_seen": True}


def test_cli_config_show_masks_api_key(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        """
llm:
  api_key: secret-token
output:
  output_dir: runs
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(app, ["config", "show", "--config", str(config_path)])

    public_config = json.loads(result.output)
    assert result.exit_code == 0
    assert public_config["llm"]["api_key"] == "***"
    assert "secret-token" not in result.output


def test_cli_benchmark_uses_configured_solver_path(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        """
solver:
  calculix:
    path: custom-ccx
    num_cpus: 7
    timeout: 123
""".strip(),
        encoding="utf-8",
    )
    captured: dict[str, int | str] = {}

    def fake_run_core_benchmarks(
        solver_path: str,
        num_cpus: int,
        timeout: int,
    ) -> list[BenchmarkResult]:
        captured["solver_path"] = solver_path
        captured["num_cpus"] = num_cpus
        captured["timeout"] = timeout
        return [
            BenchmarkResult(
                case_id="TC-XX",
                description="unit",
                predicted=1.0,
                reference=1.0,
                relative_error=0.0,
                tolerance=0.01,
                quantity="u",
                unit="mm",
                solver="unit",
            )
        ]

    monkeypatch.setattr("mechagent.cli.run_core_benchmarks", fake_run_core_benchmarks)
    runner = CliRunner()

    result = runner.invoke(app, ["benchmark", "--config", str(config_path), "--json"])

    assert result.exit_code == 0
    assert captured["solver_path"] == "custom-ccx"
    assert captured["num_cpus"] == 7
    assert captured["timeout"] == 123


def test_cli_knowledge_build_standardizes_raw_documents(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "beam.txt").write_text("悬臂梁 挠度 解析解", encoding="utf-8")
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"""
knowledge:
  raw_dir: {raw_dir.as_posix()}
  external_dir: {(tmp_path / "external").as_posix()}
  index_path: {(tmp_path / "index.jsonl").as_posix()}
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(app, ["knowledge", "build", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "1 个文档" in result.output
    assert (tmp_path / "external" / "beam.md").exists()
    assert (tmp_path / "index.jsonl").exists()


def test_cli_knowledge_query_reports_missing_index(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"""
knowledge:
  raw_dir: {(tmp_path / "raw").as_posix()}
  external_dir: {(tmp_path / "external").as_posix()}
  index_path: {(tmp_path / "missing.jsonl").as_posix()}
""".strip(),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["knowledge", "query", "悬臂梁", "--config", str(config_path)],
    )

    assert result.exit_code == 1
    assert "知识库索引不存在" in result.output
    assert "Traceback" not in result.output

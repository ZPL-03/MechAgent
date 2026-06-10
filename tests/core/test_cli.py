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


def test_cli_capabilities_json_lists_registered_examples() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["capabilities", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    structural = payload["capabilities"][0]
    assert structural["capability_id"] == "structural_static"
    assert structural["solver"] == "calculix"
    assert structural["mesher"] == "calculix-inp"
    assert "STATIC-PERFORATED-PLATE" in structural["model_case_ids"]
    assert any("偏心圆孔" in item for item in structural["examples"])


def test_cli_capabilities_table_can_show_examples() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["capabilities", "--examples"])

    assert result.exit_code == 0
    assert "MechAgent 已注册仿真能力" in result.output
    assert "structural_static" in result.output
    assert "STATIC-PERFORATED-PLATE" in result.output
    assert "孔中心x=180mm" in result.output


def test_cli_examples_json_supports_model_and_geometry_filters() -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "examples",
            "--json",
            "--geometry",
            "plate",
            "--model-case",
            "STATIC-PERFORATED-PLATE",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    examples = payload["examples"]
    assert len(examples) == 6
    assert {item["model_case_id"] for item in examples} == {"STATIC-PERFORATED-PLATE"}
    assert {item["geometry_type"] for item in examples} == {"plate"}
    assert any("孔中心x=180mm" in item["request"] for item in examples)
    assert any("孔1中心x=130mm" in item["request"] for item in examples)


def test_cli_examples_table_can_limit_rows() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["examples", "--limit", "2"])

    assert result.exit_code == 0
    assert "MechAgent 自然语言仿真示例" in result.output
    assert "SC-01" in result.output
    assert "SC-02" in result.output
    assert "SC-03" not in result.output
    assert "共 2 条示例" in result.output


def test_cli_run_non_json_prints_engineering_summary(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    report_path = tmp_path / "report.md"
    output_dir = tmp_path / "run"

    class FakeAgent:
        def run(
            self,
            _request: str,
            use_llm_agents: bool | None = None,
        ) -> SimpleNamespace:
            assert use_llm_agents is None
            return SimpleNamespace(
                summary={
                    "success": True,
                    "tasks": [
                        {
                            "task_id": "TASK_1",
                            "case_id": "STATIC-BEAM",
                            "solver_result": {
                                "success": True,
                                "model_case_id": "STATIC-BEAM",
                                "quantity": "tip_deflection",
                                "unit": "mm",
                                "predicted": 5.58805,
                                "relative_error": 0.00137856,
                                "verification_status": "passed",
                                "solver": "calculix",
                            },
                        }
                    ],
                },
                report="# 报告",
                report_path=report_path,
                output_dir=output_dir,
            )

    monkeypatch.setattr("mechagent.cli.MechAgent.from_config", lambda _path: FakeAgent())
    runner = CliRunner()

    result = runner.invoke(app, ["run", "solve a beam"])

    assert result.exit_code == 0
    assert "任务摘要" in result.output
    assert "TASK_1" in result.output
    assert "STATIC-BEAM" in result.output
    assert "5.58805 mm" in result.output
    assert "0.1379%" in result.output
    assert "报告已写入" in result.output
    assert "输出目录" in result.output


def test_cli_inspect_json_returns_preflight(monkeypatch: MonkeyPatch) -> None:
    class FakeInspection:
        ready = True

        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {
                "success": True,
                "ready": True,
                "tasks": [
                    {
                        "task_id": "TASK_1",
                        "capability_id": "structural_static",
                        "geometry_type": "beam",
                        "complete": True,
                        "missing_fields": [],
                    }
                ],
                "errors": [],
            }

    class FakeAgent:
        def inspect(
            self,
            request: str,
            use_llm_agents: bool | None = None,
        ) -> FakeInspection:
            assert request == "solve a beam"
            assert use_llm_agents is True
            return FakeInspection()

    monkeypatch.setattr("mechagent.cli.MechAgent.from_config", lambda _path: FakeAgent())
    runner = CliRunner()

    result = runner.invoke(app, ["inspect", "solve a beam", "--llm-agents", "--json"])

    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["ready"] is True
    assert payload["tasks"][0]["geometry_type"] == "beam"


def test_cli_inspect_exits_nonzero_when_request_is_not_ready(
    monkeypatch: MonkeyPatch,
) -> None:
    class FakeInspection:
        ready = False

        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {
                "success": True,
                "ready": False,
                "tasks": [
                    {
                        "task_id": "TASK_1",
                        "capability_id": "structural_static",
                        "geometry_type": "beam",
                        "complete": False,
                        "missing_fields": [
                            "geometry.dimensions.length",
                            "geometry.section.width",
                            "geometry.section.height",
                        ],
                    }
                ],
                "errors": [],
            }

    class FakeAgent:
        def inspect(
            self,
            _request: str,
            use_llm_agents: bool | None = None,
        ) -> FakeInspection:
            assert use_llm_agents is None
            return FakeInspection()

    monkeypatch.setattr("mechagent.cli.MechAgent.from_config", lambda _path: FakeAgent())
    runner = CliRunner()

    result = runner.invoke(app, ["inspect", "solve a beam"])

    assert result.exit_code == 1
    assert "请求预检" in result.output
    assert "需补充" in result.output
    assert "补参建议" in result.output
    assert "geometry.dimensions.length" in result.output
    assert "geometry.section.width" in result.output
    assert "geometry.section.height" in result.output


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

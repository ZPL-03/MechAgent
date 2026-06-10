"""项目脚本入口测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch
from scripts import (
    check_wheel_install,
    natural_language_cases,
    run_benchmarks,
    run_llm_smoke,
    run_natural_language_cases,
)

from mechagent.config import MechAgentConfig, OutputSettings
from mechagent.core.validation import BenchmarkResult


def test_run_benchmarks_script_uses_configured_output_dir(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "reports"
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"""
solver:
  calculix:
    path: custom-ccx
output:
  output_dir: {output_dir.as_posix()}
""".strip(),
        encoding="utf-8",
    )

    def fake_run_core_benchmarks(
        solver_path: str,
        num_cpus: int,
        timeout: int,
    ) -> list[BenchmarkResult]:
        assert solver_path == "custom-ccx"
        assert num_cpus == 1
        assert timeout == 3600
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

    monkeypatch.setattr(run_benchmarks, "run_core_benchmarks", fake_run_core_benchmarks)

    result = run_benchmarks.main(["--config", str(config_path)])

    assert result == 0
    assert (output_dir / "benchmark_results.json").exists()


def test_run_natural_language_cases_uses_configured_output_dir(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "runs"
    config = MechAgentConfig(output=OutputSettings(output_dir=output_dir))
    captured: dict[str, object] = {}

    class FakeResult:
        summary = {
            "tasks": [
                {
                    "model_params": {
                        "case_id": "STATIC-BEAM",
                        "geometry": {"type": "beam"},
                        "loads": [{"type": "force"}],
                    },
                    "solver_result": {"passed": True},
                }
            ],
            "report_path": "report.md",
        }

    class FakeAgent:
        def __init__(self, active_config: MechAgentConfig) -> None:
            captured["output_dir"] = active_config.output.output_dir
            self.config = active_config

        @classmethod
        def from_config(cls, _path: Path) -> "FakeAgent":
            return cls(config)

        def run(self, _request: str) -> FakeResult:
            return FakeResult()

    monkeypatch.setattr(run_natural_language_cases, "MechAgent", FakeAgent)
    monkeypatch.setattr(
        run_natural_language_cases,
        "STATIC_LANGUAGE_CASES",
        [
            natural_language_cases.StaticLanguageCase(
                case_id="SC-XX",
                request="unit",
                geometry_type="beam",
                load_type="force",
                model_case_id="STATIC-BEAM",
            )
        ],
    )

    result = run_natural_language_cases.main(["--config", str(tmp_path / "config.yaml")])

    assert result == 0
    assert captured["output_dir"] == output_dir / "natural_language_cases"


def test_run_llm_smoke_uses_configured_output_dir_and_validates_trace_summary(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "runs"
    report_path = output_dir / "llm_smoke" / "RUN" / "report.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("# unit\n\n## LLM 工程解释\n\n### 综合结论\n\n- ok\n", encoding="utf-8")
    config = MechAgentConfig(output=OutputSettings(output_dir=output_dir))
    captured: dict[str, object] = {}

    class FakeResult:
        summary = {
            "success": True,
            "work_dir": str(output_dir / "llm_smoke" / "RUN"),
            "report_path": str(report_path),
            "reporter_llm_trace": _trace_summary("ReporterAgent"),
            "tasks": [
                {
                    "task_id": "TASK_1",
                    "capability_id": "structural_static",
                    "planner_llm_trace": _trace_summary("Planner"),
                    "designer_llm_trace": _trace_summary("Designer"),
                    "mesh_llm_trace": _trace_summary("MeshAgent"),
                    "model_params": {"case_id": "STATIC-BEAM"},
                    "solver_result": {
                        "success": True,
                        "passed": True,
                        "verification_status": "passed",
                        "quantity": "tip_deflection",
                        "relative_error": 0.001,
                        "solver_llm_trace": _trace_summary("SolverAgent"),
                    },
                    "post_summary": {
                        "postproc_llm_trace": _trace_summary("PostProcAgent"),
                        "analyst_llm_trace": _trace_summary("AnalystAgent"),
                    },
                }
            ],
        }

    class FakeAgent:
        def __init__(self, active_config: MechAgentConfig) -> None:
            captured["output_dir"] = active_config.output.output_dir
            captured["llm_enabled"] = active_config.orchestrator.use_llm_agents
            self.config = active_config

        @classmethod
        def from_config(cls, _path: Path) -> "FakeAgent":
            return cls(config)

        def run(self, _request: str, use_llm_agents: bool | None = None) -> FakeResult:
            assert use_llm_agents is True
            return FakeResult()

    monkeypatch.setattr(run_llm_smoke, "MechAgent", FakeAgent)

    result = run_llm_smoke.main(["--config", str(tmp_path / "config.yaml")])

    assert result == 0
    assert captured["output_dir"] == output_dir / "llm_smoke"
    assert captured["llm_enabled"] is True


def test_run_llm_smoke_rejects_missing_agent_trace() -> None:
    summary = {
        "success": True,
        "reporter_llm_trace": _trace_summary("ReporterAgent"),
        "tasks": [
            {
                "task_id": "TASK_1",
                "planner_llm_trace": _trace_summary("Planner"),
                "designer_llm_trace": {"agent": "Designer", "used": False},
                "mesh_llm_trace": _trace_summary("MeshAgent"),
                "model_params": {"case_id": "STATIC-BEAM"},
                "solver_result": {
                    "success": True,
                    "passed": True,
                    "verification_status": "passed",
                    "solver_llm_trace": _trace_summary("SolverAgent"),
                },
                "post_summary": {
                    "postproc_llm_trace": _trace_summary("PostProcAgent"),
                    "analyst_llm_trace": _trace_summary("AnalystAgent"),
                },
            }
        ],
    }

    smoke = run_llm_smoke.evaluate_llm_smoke_summary(summary)

    assert smoke["passed"] is False
    assert any(
        item["name"] == "TASK_1.designer_llm_trace" and item["passed"] is False
        for item in smoke["checks"]
    )


def test_run_llm_smoke_accepts_noncritical_advisory_errors(tmp_path: Path) -> None:
    report_path = tmp_path / "RUN" / "report.md"
    report_path.parent.mkdir()
    report_path.write_text("# unit\n\n## LLM 工程解释\n\n### 综合结论\n\n- ok\n", encoding="utf-8")
    summary = {
        "success": True,
        "report_path": str(report_path),
        "reporter_llm_trace": _trace_summary("ReporterAgent"),
        "tasks": [
            {
                "task_id": "TASK_1",
                "planner_llm_trace": _trace_summary("Planner", error="请求超时"),
                "designer_llm_trace": _trace_summary("Designer"),
                "mesh_llm_trace": _trace_summary("MeshAgent", error="请求超时"),
                "model_params": {"case_id": "STATIC-BEAM"},
                "solver_result": {
                    "success": True,
                    "passed": True,
                    "verification_status": "passed",
                    "solver_llm_trace": _trace_summary("SolverAgent", error="请求超时"),
                },
                "post_summary": {
                    "postproc_llm_trace": _trace_summary("PostProcAgent", error="请求超时"),
                    "analyst_llm_trace": _trace_summary("AnalystAgent", error="请求超时"),
                },
            }
        ],
    }

    smoke = run_llm_smoke.evaluate_llm_smoke_summary(summary)

    assert smoke["passed"] is True
    assert any(
        item["name"] == "TASK_1.mesh_llm_trace_attempted" and item["passed"] is True
        for item in smoke["checks"]
    )


def test_check_wheel_install_finds_single_wheel(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "mechagent-0.1.0-py3-none-any.whl"
    wheel.write_text("unit", encoding="utf-8")

    assert check_wheel_install._find_single_wheel(dist, "mechagent-*.whl") == wheel


def test_check_wheel_install_rejects_missing_or_ambiguous_wheels(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()

    with pytest.raises(FileNotFoundError, match="数量必须为 1"):
        check_wheel_install._find_single_wheel(dist, "mechagent-*.whl")

    (dist / "mechagent-0.1.0-py3-none-any.whl").write_text("unit", encoding="utf-8")
    (dist / "mechagent-0.1.1-py3-none-any.whl").write_text("unit", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="数量必须为 1"):
        check_wheel_install._find_single_wheel(dist, "mechagent-*.whl")


def test_check_wheel_install_import_check_validates_type_markers() -> None:
    assert "app_typed.exists()" in check_wheel_install._IMPORT_CHECK_CODE
    assert "core_typed.exists()" in check_wheel_install._IMPORT_CHECK_CODE


def test_check_wheel_install_import_check_validates_license_files() -> None:
    assert 'single_path("mechagent-*.dist-info")' in check_wheel_install._IMPORT_CHECK_CODE
    assert 'single_path("mechagent_core-*.dist-info")' in check_wheel_install._IMPORT_CHECK_CODE
    assert '"licenses" / "LICENSE"' in check_wheel_install._IMPORT_CHECK_CODE
    assert "Requires-Dist: mechagent-core==0.1.0" in check_wheel_install._IMPORT_CHECK_CODE
    assert "Requires-Dist: langgraph>=0.2" in check_wheel_install._IMPORT_CHECK_CODE
    assert "Requires-Dist: gmsh>=4.13" in check_wheel_install._IMPORT_CHECK_CODE
    assert "entry_points.txt" in check_wheel_install._IMPORT_CHECK_CODE
    assert "mechagent = mechagent.cli:app" in check_wheel_install._IMPORT_CHECK_CODE


def _trace_summary(agent: str, error: str | None = None) -> dict[str, object]:
    return {
        "agent": agent,
        "used": True,
        "error": error,
        "prompt_chars": 10,
        "response_chars": 0 if error else 10,
    }

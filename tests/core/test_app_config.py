"""SDK 配置加载测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from mechagent import MechAgent
from mechagent.config import (
    KnowledgeSettings,
    LLMSettings,
    MechAgentConfig,
    MesherSettings,
    OrchestratorSettings,
    OutputSettings,
    SolverSettings,
)
from mechagent.core import (
    AbstractMesher,
    AbstractSolver,
    MeshResult,
    SolverResult,
    register_mesher,
    register_solver,
    unregister_mesher,
    unregister_solver,
)
from mechagent.core.models import ModelParams
from mechagent.llm import LLMConfig
from mechagent.orchestrator import WorkflowResult


def test_config_expands_environment_variables(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("llm:\n  base_url: ${URL}\n", encoding="utf-8")
    monkeypatch.setenv("URL", "https://example.com/v1")

    agent = MechAgent.from_config(config_path)

    assert agent.config.llm.base_url == "https://example.com/v1"


def test_config_expands_environment_variables_with_defaults(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        "solver:\n  calculix:\n    path: ${CALCULIX_CCX:-ccx}\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CALCULIX_CCX", raising=False)

    agent = MechAgent.from_config(config_path)

    assert agent.config.solver.calculix.path == "ccx"


def test_config_loads_env_next_to_config_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    run_dir = tmp_path / "run"
    config_dir = tmp_path / "config_home"
    run_dir.mkdir()
    config_dir.mkdir()
    (config_dir / ".env").write_text("URL=https://config.example/v1\n", encoding="utf-8")
    config_path = config_dir / "mechagent.yaml"
    config_path.write_text("llm:\n  base_url: ${URL}\n", encoding="utf-8")
    monkeypatch.chdir(run_dir)
    monkeypatch.delenv("URL", raising=False)

    agent = MechAgent.from_config(config_path)

    assert agent.config.llm.base_url == "https://config.example/v1"


def test_config_adjacent_env_takes_precedence_over_working_directory_env(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    config_dir = tmp_path / "config_home"
    run_dir.mkdir()
    config_dir.mkdir()
    (run_dir / ".env").write_text("URL=https://run.example/v1\n", encoding="utf-8")
    (config_dir / ".env").write_text("URL=https://config.example/v1\n", encoding="utf-8")
    config_path = config_dir / "mechagent.yaml"
    config_path.write_text("llm:\n  base_url: ${URL}\n", encoding="utf-8")
    monkeypatch.chdir(run_dir)
    monkeypatch.delenv("URL", raising=False)

    agent = MechAgent.from_config(config_path)

    assert agent.config.llm.base_url == "https://config.example/v1"


def test_config_explicit_environment_takes_precedence_over_dotenv(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = tmp_path / "mechagent.yaml"
    (tmp_path / ".env").write_text("URL=https://dotenv.example/v1\n", encoding="utf-8")
    config_path.write_text("llm:\n  base_url: ${URL}\n", encoding="utf-8")
    monkeypatch.setenv("URL", "https://process.example/v1")

    agent = MechAgent.from_config(config_path)

    assert agent.config.llm.base_url == "https://process.example/v1"


def test_config_dotenv_loading_does_not_mutate_process_environment(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first_config = first_dir / "mechagent.yaml"
    second_config = second_dir / "mechagent.yaml"
    first_config.write_text("llm:\n  base_url: ${URL}\n", encoding="utf-8")
    second_config.write_text("llm:\n  base_url: ${URL}\n", encoding="utf-8")
    (first_dir / ".env").write_text("URL=https://first.example/v1\n", encoding="utf-8")
    (second_dir / ".env").write_text("URL=https://second.example/v1\n", encoding="utf-8")
    monkeypatch.delenv("URL", raising=False)

    first_agent = MechAgent.from_config(first_config)
    second_agent = MechAgent.from_config(second_config)

    assert first_agent.config.llm.base_url == "https://first.example/v1"
    assert second_agent.config.llm.base_url == "https://second.example/v1"
    assert "URL" not in os.environ


def test_knowledge_config_rejects_invalid_chunk_overlap() -> None:
    with pytest.raises(ValueError):
        KnowledgeSettings(chunk_size=100, chunk_overlap=100)


def test_config_rejects_non_finite_public_numeric_settings() -> None:
    with pytest.raises(ValueError, match="temperature"):
        LLMSettings(temperature=float("nan"))
    with pytest.raises(ValueError, match="temperature"):
        LLMConfig(temperature=float("nan"))
    with pytest.raises(ValueError, match="min_quality"):
        MesherSettings(min_quality=float("nan"))
    with pytest.raises(ValueError, match="knowledge.bm25_weight"):
        KnowledgeSettings(bm25_weight=float("inf"))


def test_config_normalizes_supported_backend_names() -> None:
    assert LLMSettings(provider="OPENAI_COMPATIBLE").provider == "openai_compatible"
    assert SolverSettings(default="CALCULIX").default == "calculix"
    assert MesherSettings(default="CALCULIX-INP").default == "calculix-inp"
    assert OrchestratorSettings(mode="SEQUENTIAL").mode == "sequential"
    assert OutputSettings(default_format="MARKDOWN").default_format == "markdown"


def test_config_accepts_registered_tool_plugins() -> None:
    register_solver("unit-config-solver", _ConfigDummySolver)
    register_mesher("unit-config-mesher", _ConfigDummyMesher)
    try:
        assert SolverSettings(default="UNIT-CONFIG-SOLVER").default == "unit-config-solver"
        assert MesherSettings(default="UNIT-CONFIG-MESHER").default == "unit-config-mesher"
    finally:
        unregister_solver("unit-config-solver")
        unregister_mesher("unit-config-mesher")


def test_run_llm_agents_override_is_single_call(monkeypatch: MonkeyPatch) -> None:
    config = MechAgentConfig(orchestrator=OrchestratorSettings(mode="dag", use_llm_agents=False))
    agent = MechAgent(config)
    captured: list[bool] = []
    workflow_config_ids: list[int] = []

    def fake_run_langgraph_workflow(
        workflow_config: MechAgentConfig,
        request: str,
    ) -> WorkflowResult:
        captured.append(workflow_config.orchestrator.use_llm_agents)
        workflow_config_ids.append(id(workflow_config))
        return WorkflowResult(success=True, request=request)

    monkeypatch.setattr("mechagent.app._run_langgraph_workflow", fake_run_langgraph_workflow)

    result = agent.run("solve a beam", use_llm_agents=True)

    assert result.summary["success"] is True
    assert captured == [True]
    assert workflow_config_ids[0] != id(agent.config)
    assert agent.config.orchestrator.use_llm_agents is False


def test_config_rejects_unsupported_backend_names() -> None:
    with pytest.raises(ValueError, match="llm.provider"):
        LLMSettings(provider="unknown")
    with pytest.raises(ValueError, match="solver.default"):
        SolverSettings(default="unknown")
    with pytest.raises(ValueError, match="mesher.default"):
        MesherSettings(default="unknown")
    with pytest.raises(ValueError, match="orchestrator.mode"):
        OrchestratorSettings(mode="unknown")
    with pytest.raises(ValueError, match="output.default_format"):
        OutputSettings(default_format="html")


def test_config_rejects_unclean_default_tool_names() -> None:
    with pytest.raises(ValueError, match="solver.default 不能为空"):
        SolverSettings(default=" ")
    with pytest.raises(ValueError, match="solver.default 不能包含首尾空白"):
        SolverSettings(default=" calculix ")
    with pytest.raises(ValueError, match="mesher.default 不能为空"):
        MesherSettings(default=" ")
    with pytest.raises(ValueError, match="mesher.default 不能包含首尾空白"):
        MesherSettings(default=" calculix-inp ")


class _ConfigDummySolver(AbstractSolver):
    def generate_input(self, _model_params: ModelParams) -> Path:
        return self.config.work_dir / "config_dummy.inp"

    def solve(self, _input_file: Path) -> SolverResult:
        return SolverResult(success=True, wall_time=0.0)

    def extract_results(self, _result: SolverResult) -> dict[str, object]:
        return {"success": True}


class _ConfigDummyMesher(AbstractMesher):
    def generate(self, _model_params: ModelParams) -> MeshResult:
        return MeshResult(success=True)

"""MeshAgent 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mechagent.config import LLMSettings, MechAgentConfig, MesherSettings, OrchestratorSettings
from mechagent.core.factory import register_mesher, unregister_mesher
from mechagent.core.mesher import AbstractMesher, MeshResult
from mechagent.core.models import ModelParams
from mechagent.core.validation import tc01_model_params
from mechagent.orchestrator.agents import MeshAgent
from mechagent.orchestrator.capabilities import (
    SimulationCapability,
    register_capability,
    unregister_capability,
)
from mechagent.orchestrator.evaluation import ResultEvaluationContext
from mechagent.orchestrator.models import TaskItem


def test_mesh_agent_rejects_mesh_below_min_quality(tmp_path: Path) -> None:
    register_mesher("unit-low-quality-mesher", LowQualityMesher)
    try:
        config = MechAgentConfig(
            mesher=MesherSettings(default="unit-low-quality-mesher", min_quality=0.5)
        )
        result = MeshAgent(config, tmp_path).generate(tc01_model_params())
    finally:
        unregister_mesher("unit-low-quality-mesher")

    assert result.success is False
    assert result.mesh_file == tmp_path / "mesh.inp"
    assert "网格质量低于阈值" in str(result.error_message)
    assert "min_jacobian=0.2" in str(result.error_message)


def test_mesh_agent_validates_mesh_output_contract_and_upper_bound_metrics(
    tmp_path: Path,
) -> None:
    register_mesher("unit-aspect-mesher", AspectMetricMesher)
    register_mesher("unit-nonfinite-quality-mesher", NonFiniteQualityMesher)
    register_mesher("unit-missing-file-mesher", MissingFileMesher)
    try:
        aspect_config = MechAgentConfig(
            mesher=MesherSettings(default="unit-aspect-mesher", min_quality=0.5),
        )
        nonfinite_config = MechAgentConfig(
            mesher=MesherSettings(default="unit-nonfinite-quality-mesher", min_quality=0.5),
        )
        missing_file_config = MechAgentConfig(
            mesher=MesherSettings(default="unit-missing-file-mesher", min_quality=0.5),
        )
        aspect_result = MeshAgent(aspect_config, tmp_path / "aspect").generate(tc01_model_params())
        nonfinite_result = MeshAgent(nonfinite_config, tmp_path / "nonfinite").generate(
            tc01_model_params()
        )
        missing_file_result = MeshAgent(missing_file_config, tmp_path / "missing").generate(
            tc01_model_params()
        )
    finally:
        unregister_mesher("unit-missing-file-mesher")
        unregister_mesher("unit-nonfinite-quality-mesher")
        unregister_mesher("unit-aspect-mesher")

    assert aspect_result.success is True
    assert nonfinite_result.success is False
    assert nonfinite_result.error_message is not None
    assert "不是有限数值" in nonfinite_result.error_message
    assert missing_file_result.success is False
    assert missing_file_result.error_message == "网格结果缺少 mesh_file，求解阶段无法继续。"


def test_mesh_agent_passes_model_seed_size_to_mesher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_mesher("unit-seed-capturing-mesher", SeedCapturingMesher)
    params = tc01_model_params().model_copy(
        update={"mesh": tc01_model_params().mesh.model_copy(update={"seed_size": 12.5})}
    )
    try:
        config = MechAgentConfig(mesher=MesherSettings(default="unit-seed-capturing-mesher"))
        result = MeshAgent(config, tmp_path).generate(params)

        def fake_completion(prompt: str, _config: object) -> str:
            assert "current_mesh" in prompt
            assert "strategy_rules" in prompt
            return '{"seed_size": 6.25, "element_type": "B31", "rationale": "梁长方向加密"}'

        monkeypatch.setattr("mechagent.orchestrator.llm_advisor.completion", fake_completion)
        llm_config = MechAgentConfig(
            mesher=MesherSettings(default="unit-seed-capturing-mesher"),
            orchestrator=OrchestratorSettings(use_llm_agents=True),
            llm=LLMSettings(base_url="https://example.com/v1", api_key="key", model="demo"),
        )
        llm_output = MeshAgent(llm_config, tmp_path / "llm").generate_with_trace(params)
    finally:
        unregister_mesher("unit-seed-capturing-mesher")

    assert result.success is True
    assert result.metadata["seed_size_mm"] == 12.5
    assert llm_output.mesh_result.success is True
    assert llm_output.mesh_result.metadata["seed_size_mm"] == 6.25
    assert llm_output.mesh_result.metadata["mesh_strategy_source"] == "llm"
    assert llm_output.mesh_llm_trace.used is True
    assert llm_output.mesh_llm_trace.error is None


def test_mesh_agent_uses_capability_mesher_over_global_default(tmp_path: Path) -> None:
    register_mesher("unit-capability-mesher", CapabilityMesher)
    capability = SimulationCapability(
        capability_id="unit_mesh_tool_capability",
        task_case_id="UNIT-MESH-TOOL",
        title="单元网格工具能力",
        analysis_type="static",
        physics_domain="structural",
        parser=lambda _request: tc01_model_params(),
        matcher=lambda _request: False,
        geometry_detector=lambda _request: "beam",
        evaluator=_unit_evaluator,
        mesher_name="unit-capability-mesher",
    )
    register_capability(capability)
    try:
        task = TaskItem(
            task_id="TASK_1",
            case_id=capability.task_case_id,
            capability_id=capability.capability_id,
            title=capability.title,
        )

        result = MeshAgent(MechAgentConfig(), tmp_path).generate(tc01_model_params(), task)
    finally:
        unregister_capability("unit_mesh_tool_capability")
        unregister_mesher("unit-capability-mesher")

    assert result.success is True
    assert result.metadata["mesher"] == "capability"


class LowQualityMesher(AbstractMesher):
    def generate(self, _model_params: ModelParams) -> MeshResult:
        return MeshResult(
            success=True,
            mesh_file=self.config.work_dir / "mesh.inp",
            quality={"min_jacobian": 0.2},
        )


class AspectMetricMesher(AbstractMesher):
    def generate(self, _model_params: ModelParams) -> MeshResult:
        return MeshResult(
            success=True,
            mesh_file=self.config.work_dir / "mesh.inp",
            quality={"max_aspect_ratio": 20.0},
        )


class NonFiniteQualityMesher(AbstractMesher):
    def generate(self, _model_params: ModelParams) -> MeshResult:
        return MeshResult(
            success=True,
            mesh_file=self.config.work_dir / "mesh.inp",
            quality={"min_jacobian": float("nan")},
        )


class MissingFileMesher(AbstractMesher):
    def generate(self, _model_params: ModelParams) -> MeshResult:
        return MeshResult(
            success=True,
            quality={"min_jacobian": 1.0},
        )


class SeedCapturingMesher(AbstractMesher):
    def generate(self, _model_params: ModelParams) -> MeshResult:
        return MeshResult(
            success=True,
            mesh_file=self.config.work_dir / "mesh.inp",
            metadata={"seed_size_mm": self.config.seed_size},
        )


class CapabilityMesher(AbstractMesher):
    def generate(self, _model_params: ModelParams) -> MeshResult:
        return MeshResult(
            success=True,
            mesh_file=self.config.work_dir / "capability_mesh.inp",
            quality={"min_jacobian": 1.0},
            metadata={"mesher": "capability"},
        )


def _unit_evaluator(context: ResultEvaluationContext) -> dict[str, object]:
    return {
        **context.solver_result,
        "model_case_id": context.model_params.case_id or context.task_case_id,
        "passed": True,
        "quantity": "unit",
        "unit": "",
        "solver": context.solver_name,
        "task_title": context.task_title,
    }

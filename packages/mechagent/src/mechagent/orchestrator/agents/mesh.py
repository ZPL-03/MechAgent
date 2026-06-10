"""MeshAgent。"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from mechagent.config import MechAgentConfig
from mechagent.core.factory import create_mesher
from mechagent.core.mesher import MeshConfig, MeshResult
from mechagent.core.models import ElementType, ModelParams
from mechagent.orchestrator.capabilities import get_capability
from mechagent.orchestrator.llm_advisor import AgentLLMAdvisor
from mechagent.orchestrator.llm_payload import advisory_payload
from mechagent.orchestrator.models import MeshAgentOutput, TaskItem


class MeshAgent:
    """生成网格并记录网格质量。

    Args:
        config: 全局配置。
        work_dir: 运行目录。

    Returns:
        MeshAgent: Mesh 节点实例。

    Raises:
        OSError: 当运行目录无法创建时抛出。

    Example:
        >>> MeshAgent(MechAgentConfig(), Path("mechagent_output")).generate(tc01_model_params())
        MeshResult(...)
    """

    def __init__(self, config: MechAgentConfig, work_dir: Path) -> None:
        self.config = config
        self.advisor = AgentLLMAdvisor(config)
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, model_params: ModelParams, task: TaskItem | None = None) -> MeshResult:
        """生成网格。

        Args:
            model_params: 结构化仿真参数。
            task: Planner 输出任务，用于能力级工具选择。

        Returns:
            MeshResult: 网格生成结果。

        Raises:
            无。

        Example:
            >>> agent.generate(model_params)
            MeshResult(success=True, ...)
        """

        return self.generate_with_trace(model_params, task).mesh_result

    def generate_with_trace(
        self,
        model_params: ModelParams,
        task: TaskItem | None = None,
    ) -> MeshAgentOutput:
        """生成网格和 Mesh LLM 审计记录。

        Args:
            model_params: 结构化仿真参数。
            task: Planner 输出任务，用于能力级工具选择。

        Returns:
            MeshAgentOutput: 网格结果和审计记录。

        Raises:
            无。
        """

        trace = self.advisor.complete(
            "MeshAgent",
            "根据结构化有限元模型生成网格策略建议",
            advisory_payload(_mesh_strategy_context(model_params, task)),
            (
                "只输出 JSON 对象，字段包括 seed_size、element_type、rationale。"
                "seed_size 单位为 mm，必须是正数；element_type 必须匹配当前几何。"
            ),
        )
        model_for_mesh, trace = _apply_llm_mesh_strategy(model_params, trace)
        mesher_name = self._mesher_name(task)
        mesher = create_mesher(
            mesher_name,
            MeshConfig(
                work_dir=self.work_dir,
                seed_size=model_for_mesh.mesh.seed_size,
                min_quality=self.config.mesher.min_quality,
            ),
        )
        result = mesher.generate(model_for_mesh)
        result = _apply_quality_gate(result, self.config.mesher.min_quality)
        if (
            result.success
            and model_for_mesh.mesh.seed_size != model_params.mesh.seed_size
            and result.metadata.get("mesh_strategy_source") is None
        ):
            result = result.model_copy(
                update={"metadata": {**result.metadata, "mesh_strategy_source": "llm"}}
            )
        return MeshAgentOutput(mesh_result=result, mesh_llm_trace=trace)

    def _mesher_name(self, task: TaskItem | None) -> str:
        if task is not None and task.capability_id:
            capability = get_capability(task.capability_id)
            if capability.mesher_name:
                return capability.mesher_name
        return self.config.mesher.default


def _apply_quality_gate(result: MeshResult, min_quality: float) -> MeshResult:
    if not result.success:
        return result
    if result.mesh_file is None:
        return result.model_copy(
            update={
                "success": False,
                "error_message": "网格结果缺少 mesh_file，求解阶段无法继续。",
            }
        )
    invalid = [name for name, value in result.quality.items() if not math.isfinite(value)]
    if invalid:
        details = "、".join(f"{name}={result.quality[name]}" for name in invalid)
        return result.model_copy(
            update={
                "success": False,
                "error_message": f"网格质量指标不是有限数值: {details}。",
            }
        )
    failed = [
        name
        for name, value in result.quality.items()
        if name.startswith("min_") and value < min_quality
    ]
    if not failed:
        return result
    details = "、".join(f"{name}={result.quality[name]:.6g}" for name in failed)
    return result.model_copy(
        update={
            "success": False,
            "error_message": f"网格质量低于阈值 {min_quality:.6g}: {details}。",
        }
    )


def _mesh_strategy_context(model_params: ModelParams, task: TaskItem | None) -> dict[str, Any]:
    return {
        "task": task.model_dump(mode="json", exclude={"planner_llm_trace"}) if task else None,
        "model_params": model_params.model_dump(mode="json"),
        "current_mesh": model_params.mesh.model_dump(mode="json"),
        "strategy_rules": [
            "保持与几何兼容的单元类型。",
            "网格尺寸需要兼顾计算成本、几何特征和载荷边界区域。",
            "开孔板应考虑孔径附近网格加密。",
        ],
    }


def _apply_llm_mesh_strategy(
    model_params: ModelParams,
    trace: Any,
) -> tuple[ModelParams, Any]:
    if not trace.used or trace.error or not trace.response.strip():
        return model_params, trace

    payload = _parse_json_object(trace.response)
    if not payload:
        return model_params, trace.model_copy(
            update={"error": "LLM 网格策略不是可解析的 JSON 对象。"}
        )

    errors: list[str] = []
    seed_size = _strategy_seed_size(payload)
    element_type = _strategy_element_type(payload)
    mesh_updates: dict[str, Any] = {}

    if seed_size is not None:
        seed_error = _validate_seed_size(seed_size, model_params.mesh.seed_size)
        if seed_error:
            errors.append(seed_error)
        else:
            mesh_updates["seed_size"] = seed_size

    if element_type is not None:
        element_error = _validate_element_type(element_type, model_params)
        if element_error:
            errors.append(element_error)
        else:
            mesh_updates["element_type"] = ElementType(element_type)

    if errors:
        return model_params, trace.model_copy(update={"error": "；".join(errors)})
    if not mesh_updates:
        return model_params, trace

    next_mesh = model_params.mesh.model_copy(update=mesh_updates)
    return model_params.model_copy(update={"mesh": next_mesh}), trace


def _parse_json_object(response: str) -> dict[str, Any]:
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match is None:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _strategy_seed_size(payload: dict[str, Any]) -> float | None:
    for key in ("seed_size", "seed_size_mm", "mesh_seed", "mesh_seed_mm", "element_size"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            seed = float(value)
        except (TypeError, ValueError):
            return None
        return seed
    mesh = payload.get("mesh")
    if isinstance(mesh, dict):
        return _strategy_seed_size(mesh)
    return None


def _strategy_element_type(payload: dict[str, Any]) -> str | None:
    value = payload.get("element_type") or payload.get("element")
    if isinstance(value, str) and value.strip():
        return value.strip().upper()
    mesh = payload.get("mesh")
    if isinstance(mesh, dict):
        return _strategy_element_type(mesh)
    return None


def _validate_seed_size(seed_size: float, current_seed_size: float) -> str:
    if not math.isfinite(seed_size) or seed_size <= 0:
        return "LLM 网格尺寸必须是有限正数。"
    lower = max(current_seed_size / 5.0, 0.1)
    upper = current_seed_size * 5.0
    if seed_size < lower or seed_size > upper:
        return f"LLM 网格尺寸 {seed_size:.6g} mm 超出允许范围 [{lower:.6g}, {upper:.6g}] mm。"
    return ""


def _validate_element_type(element_type: str, model_params: ModelParams) -> str:
    try:
        parsed = ElementType(element_type)
    except ValueError:
        return f"LLM 单元类型 {element_type} 不在支持集合内。"
    allowed = _allowed_element_types(model_params.geometry.type)
    if parsed not in allowed:
        allowed_text = "、".join(
            item.value for item in sorted(allowed, key=lambda item: item.value)
        )
        return (
            f"LLM 单元类型 {parsed.value} 与几何 {model_params.geometry.type.value} "
            f"不兼容，允许 {allowed_text}。"
        )
    return ""


def _allowed_element_types(geometry_type: object) -> set[ElementType]:
    mapping = {
        "beam": {ElementType.B31},
        "plate": {ElementType.S4},
        "solid": {ElementType.C3D8R},
    }
    return mapping.get(str(getattr(geometry_type, "value", geometry_type)), set(ElementType))

"""仿真能力注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from typing import Callable, Optional

from mechagent.core.factory import registered_meshers, registered_solvers
from mechagent.core.models import GeometryType, LoadType, ModelParams
from mechagent.core.rules import ensure_static_execution_contract
from mechagent.orchestrator.evaluation import (
    ResultEvaluator,
    evaluate_structural_static_result,
)
from mechagent.orchestrator.intent import SimulationIntent
from mechagent.orchestrator.static_parser import (
    detect_static_geometry_type,
    detect_static_missing_fields,
    looks_like_static_request,
    parse_static_model_params,
    split_static_simulation_requests,
)


@dataclass(frozen=True)
class SimulationCapability:
    """可执行仿真能力声明。

    Args:
        capability_id: 能力编号。
        task_case_id: Planner 输出的任务类别编号。
        title: 能力名称。
        analysis_type: 分析类型。
        physics_domain: 物理领域。
        parser: 自然语言到 `ModelParams` 的解析函数。
        matcher: 请求匹配函数。
        geometry_detector: 请求几何类型识别函数。
        evaluator: 求解结果评价函数。
        solver_name: 能力默认求解器注册名。
        mesher_name: 能力默认网格器注册名。
        request_splitter: 复合自然语言请求拆分函数。
        planner_description: Planner LLM 能力选择描述。
        planner_keywords: Planner LLM 能力选择关键词。
        example_requests: Planner LLM 能力选择示例请求。
        missing_field_detector: 缺少字段诊断函数。
        execution_validator: 能力专属执行契约检查函数。
        llm_model_contract: Designer LLM 参数抽取补充契约。
        model_case_ids: 能力支持的模型编号。
        model_normalizer: LLM `ModelParams` 解析后的能力归一化函数。

    Returns:
        SimulationCapability: 能力注册项。

    Raises:
        TypeError: 当字段类型不匹配时由 dataclass 构造阶段抛出。

    Example:
        >>> all_capabilities()[0].capability_id
        'structural_static'
    """

    capability_id: str
    task_case_id: str
    title: str
    analysis_type: str
    physics_domain: str
    parser: Callable[[str], ModelParams]
    matcher: Callable[[str], bool]
    geometry_detector: Callable[[str], Optional[str]]
    evaluator: ResultEvaluator
    solver_name: str = ""
    mesher_name: str = ""
    request_splitter: Callable[[str], tuple[str, ...]] | None = None
    planner_description: str = ""
    planner_keywords: tuple[str, ...] = ()
    example_requests: tuple[str, ...] = ()
    missing_field_detector: Callable[[str], list[str]] | None = None
    execution_validator: Callable[[ModelParams], None] | None = None
    llm_model_contract: str = ""
    model_case_ids: tuple[str, ...] = ()
    model_normalizer: Callable[[ModelParams, str], ModelParams] | None = None

    def build_intent(self, request: str) -> SimulationIntent:
        """构建标准化意图。

        Args:
            request: 用户自然语言请求。

        Returns:
            SimulationIntent: 标准化意图。

        Raises:
            无。

        Example:
            >>> all_capabilities()[0].build_intent("梁静力").capability_id
            'structural_static'
        """

        missing_fields = (
            self.missing_field_detector(request)
            if self.missing_field_detector is not None
            else _missing_fields_from_parser(self.parser, request)
        )
        geometry_type = self.geometry_detector(request)
        return SimulationIntent(
            raw_request=request,
            capability_id=self.capability_id,
            analysis_type=self.analysis_type,
            physics_domain=self.physics_domain,
            geometry_type=geometry_type,
            missing_fields=missing_fields,
            confidence=1.0 if not missing_fields else 0.75,
        )


_CAPABILITY_REGISTRY: dict[str, SimulationCapability] = {}


def register_capability(capability: SimulationCapability, *, replace: bool = False) -> None:
    """注册可执行仿真能力。

    Args:
        capability: 能力声明。
        replace: 是否覆盖同名能力。

    Returns:
        无。

    Raises:
        ValueError: 当能力编号为空、编号重复或任务类别重复时抛出。

    Example:
        >>> register_capability(capability)
    """

    capability_id = _clean_required_field("capability_id", capability.capability_id)
    task_case_id = _clean_required_field("task_case_id", capability.task_case_id)
    _clean_required_field("title", capability.title)
    _clean_required_field("analysis_type", capability.analysis_type)
    _clean_required_field("physics_domain", capability.physics_domain)
    _clean_optional_field("solver_name", capability.solver_name)
    _clean_optional_field("mesher_name", capability.mesher_name)
    solver_name = _registered_solver_name(capability.solver_name)
    mesher_name = _registered_mesher_name(capability.mesher_name)
    _clean_optional_field("planner_description", capability.planner_description)
    _clean_optional_items("planner_keywords", capability.planner_keywords)
    _clean_optional_items("example_requests", capability.example_requests)
    _clean_optional_items("model_case_ids", capability.model_case_ids)
    if capability_id in _CAPABILITY_REGISTRY and not replace:
        msg = f"仿真能力已注册: {capability.capability_id}"
        raise ValueError(msg)
    duplicated_task_case = [
        item.capability_id
        for item in _CAPABILITY_REGISTRY.values()
        if item.task_case_id == task_case_id and item.capability_id != capability_id
    ]
    if duplicated_task_case:
        msg = f"任务类别编号已注册: {capability.task_case_id}"
        raise ValueError(msg)
    _CAPABILITY_REGISTRY[capability_id] = dataclass_replace(
        capability,
        solver_name=solver_name,
        mesher_name=mesher_name,
    )


def registered_capability_ids() -> tuple[str, ...]:
    """返回已注册能力编号。"""

    return tuple(_CAPABILITY_REGISTRY)


def unregister_capability(capability_id: str) -> None:
    """注销仿真能力。

    Args:
        capability_id: 能力编号。

    Returns:
        无。

    Raises:
        ValueError: 当能力未注册时抛出。
    """

    normalized = capability_id.strip()
    if not normalized:
        msg = "capability_id 不能为空。"
        raise ValueError(msg)
    if normalized not in _CAPABILITY_REGISTRY:
        msg = f"仿真能力未注册: {capability_id}"
        raise ValueError(msg)
    del _CAPABILITY_REGISTRY[normalized]


def _clean_required_field(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        msg = f"{name} 不能为空。"
        raise ValueError(msg)
    if normalized != value:
        msg = f"{name} 不能包含首尾空白。"
        raise ValueError(msg)
    return normalized


def _clean_optional_field(name: str, value: str) -> None:
    if value and value.strip() != value:
        msg = f"{name} 不能包含首尾空白。"
        raise ValueError(msg)


def _clean_optional_items(name: str, values: tuple[str, ...]) -> None:
    for value in values:
        if not value.strip():
            msg = f"{name} 不能包含空白条目。"
            raise ValueError(msg)
        if value.strip() != value:
            msg = f"{name} 不能包含首尾空白。"
            raise ValueError(msg)


def _registered_solver_name(name: str) -> str:
    if not name:
        return ""
    registered = registered_solvers()
    normalized = name.strip().lower()
    if normalized in registered:
        return normalized
    msg = f"solver_name 未注册: {name}。已注册求解器: {', '.join(registered)}。"
    raise ValueError(msg)


def _registered_mesher_name(name: str) -> str:
    if not name:
        return ""
    registered = registered_meshers()
    normalized = name.strip().lower()
    if normalized in registered:
        return normalized
    msg = f"mesher_name 未注册: {name}。已注册网格器: {', '.join(registered)}。"
    raise ValueError(msg)


def _normalize_structural_static_model_params(
    params: ModelParams,
    request: str,
) -> ModelParams:
    geometry_type = params.geometry.type
    load_type = params.loads[0].type
    case_id = params.case_id
    load_case = params.load_case

    if geometry_type is GeometryType.BEAM:
        case_id = "STATIC-BEAM"
        load_case = (
            "cantilever_uniform_line_load"
            if load_type is LoadType.LINE_LOAD
            else "cantilever_tip_force"
        )
    elif geometry_type is GeometryType.PLATE:
        case_id = "STATIC-PLATE"
        load_case = "simply_supported_pressure"
    elif geometry_type is GeometryType.SOLID:
        case_id = "STATIC-SOLID"
        load_case = (
            "fixed_solid_axial_pressure"
            if load_type is LoadType.PRESSURE
            else "fixed_solid_axial_force"
        )

    metadata = dict(params.metadata)
    metadata["source"] = "llm_structured"
    metadata["raw_request"] = request
    return params.model_copy(
        update={
            "case_id": case_id,
            "load_case": load_case,
            "metadata": metadata,
        }
    )


register_capability(
    SimulationCapability(
        capability_id="structural_static",
        task_case_id="STATIC-STRUCTURAL",
        title="结构静力分析",
        analysis_type="static",
        physics_domain="structural",
        parser=parse_static_model_params,
        matcher=looks_like_static_request,
        geometry_detector=detect_static_geometry_type,
        evaluator=evaluate_structural_static_result,
        solver_name="calculix",
        mesher_name="calculix-inp",
        request_splitter=split_static_simulation_requests,
        planner_description=(
            "结构线弹性静力分析，覆盖梁、矩形板和矩形实体块的几何建模、网格、求解、后处理和报告。"
        ),
        planner_keywords=(
            "static",
            "structural",
            "beam",
            "plate",
            "solid",
            "静力",
            "结构",
            "梁",
            "板",
            "实体",
            "挠度",
            "位移",
            "应力",
        ),
        example_requests=(
            "钢制悬臂梁，长度2m，截面100mmx200mm，左端固定，右端向下10kN集中力。",
            "矩形板四边简支，承受均布压力，求中心挠度。",
            "长方体实体左端固定，右端端面轴向拉伸。",
        ),
        missing_field_detector=detect_static_missing_fields,
        execution_validator=ensure_static_execution_contract,
        llm_model_contract=(
            "`geometry.type` 使用 beam、plate 或 solid；"
            "梁使用 dimensions.length/width/height、B31 单元、root 固支，"
            "载荷为 tip 集中力或 span 线载荷；"
            "板使用 dimensions.length/width/thickness、S4 单元、all_edges 简支和 top_surface 压力；"
            "实体使用 dimensions.length/width/height、C3D8R 单元、root 固定，"
            "载荷为 end_face 轴向压力或端面合力。"
        ),
        model_case_ids=("STATIC-BEAM", "STATIC-PLATE", "STATIC-SOLID"),
        model_normalizer=_normalize_structural_static_model_params,
    )
)


def all_capabilities() -> tuple[SimulationCapability, ...]:
    """返回全部注册能力。

    Args:
        无。

    Returns:
        tuple[SimulationCapability, ...]: 能力注册项。

    Raises:
        无。

    Example:
        >>> len(all_capabilities()) >= 1
        True
    """

    return tuple(_CAPABILITY_REGISTRY.values())


def match_capabilities(request: str) -> list[SimulationIntent]:
    """匹配用户请求对应的能力意图。

    Args:
        request: 用户自然语言请求。

    Returns:
        list[SimulationIntent]: 匹配到的能力意图。

    Raises:
        无。

    Example:
        >>> match_capabilities("长1000mm 的梁静力分析")[0].capability_id
        'structural_static'
    """

    intents: list[SimulationIntent] = []
    for capability in _CAPABILITY_REGISTRY.values():
        for segment in _capability_request_segments(capability, request):
            if capability.matcher(segment):
                intents.append(capability.build_intent(segment))
    return intents


def get_capability(capability_id: str) -> SimulationCapability:
    """按编号获取能力注册项。

    Args:
        capability_id: 能力编号。

    Returns:
        SimulationCapability: 能力注册项。

    Raises:
        ValueError: 当能力编号未注册时抛出。

    Example:
        >>> get_capability("structural_static").analysis_type
        'static'
    """

    capability = _CAPABILITY_REGISTRY.get(capability_id.strip())
    if capability is not None:
        return capability
    msg = f"未注册仿真能力: {capability_id}"
    raise ValueError(msg)


def _missing_fields_from_parser(
    parser: Callable[[str], ModelParams],
    request: str,
) -> list[str]:
    try:
        parser(request)
    except ValueError as exc:
        return _extract_missing_fields(str(exc))
    return []


def _extract_missing_fields(message: str) -> list[str]:
    marker = "缺少必要参数:"
    if marker not in message:
        return []
    tail = message.split(marker, 1)[1].strip().rstrip("。")
    return [item for item in tail.split("、") if item]


def _capability_request_segments(
    capability: SimulationCapability,
    request: str,
) -> tuple[str, ...]:
    if capability.request_splitter is None:
        return (request,)
    segments = tuple(
        segment.strip() for segment in capability.request_splitter(request) if segment.strip()
    )
    return segments or (request,)

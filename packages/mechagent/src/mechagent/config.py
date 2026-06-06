"""MechAgent 配置模型。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mechagent.core.defaults import DEFAULT_CALCULIX_PATH
from mechagent.core.factory import registered_meshers, registered_solvers


class LLMSettings(BaseModel):
    """LLM 后端配置。

    Args:
        provider: LLM 服务类型。
        base_url: OpenAI 兼容接口地址。
        api_key: 接口密钥。
        model: 模型名称。
        temperature: 采样温度。

    Returns:
        LLMSettings: 经过校验的 LLM 配置。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> LLMSettings(base_url="https://example.com/v1", api_key="x", model="demo")
        LLMSettings(...)
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)

    @field_validator("provider")
    @classmethod
    def _provider_must_be_supported(cls, value: str) -> str:
        normalized = value.lower()
        if normalized != "openai_compatible":
            msg = "llm.provider 支持 openai_compatible。"
            raise ValueError(msg)
        return normalized

    @field_validator("temperature")
    @classmethod
    def _temperature_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "llm.temperature 必须是有限数值。"
            raise ValueError(msg)
        return value


class CalculiXSettings(BaseModel):
    """CalculiX 配置。

    Args:
        path: `ccx` 可执行文件路径或命令名。
        num_cpus: CPU 核数。
        timeout: 超时时间，单位为 s。

    Returns:
        CalculiXSettings: 经过校验的 CalculiX 配置。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> CalculiXSettings()
        CalculiXSettings(...)
    """

    model_config = ConfigDict(extra="forbid")

    path: str = DEFAULT_CALCULIX_PATH
    num_cpus: int = Field(default=1, ge=1)
    timeout: int = Field(default=3600, ge=1)


class SolverSettings(BaseModel):
    """求解器配置。

    Args:
        default: 默认求解器名称。
        calculix: CalculiX 配置。

    Returns:
        SolverSettings: 经过校验的求解器配置。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> SolverSettings()
        SolverSettings(...)
    """

    model_config = ConfigDict(extra="forbid")

    default: str = "calculix"
    calculix: CalculiXSettings = Field(default_factory=CalculiXSettings)

    @field_validator("default")
    @classmethod
    def _default_solver_must_be_supported(cls, value: str) -> str:
        return _registered_config_name(value, registered_solvers(), "solver.default", "求解器")


class MesherSettings(BaseModel):
    """网格器配置。

    Args:
        default: 默认网格器名称。
        min_quality: 最小质量阈值。

    Returns:
        MesherSettings: 经过校验的网格器配置。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> MesherSettings()
        MesherSettings(default='calculix-inp', min_quality=0.3)
    """

    model_config = ConfigDict(extra="forbid")

    default: str = "calculix-inp"
    min_quality: float = Field(default=0.3, ge=0.0, le=1.0)

    @field_validator("default")
    @classmethod
    def _default_mesher_must_be_supported(cls, value: str) -> str:
        return _registered_config_name(value, registered_meshers(), "mesher.default", "网格器")

    @field_validator("min_quality")
    @classmethod
    def _min_quality_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "mesher.min_quality 必须是有限数值。"
            raise ValueError(msg)
        return value


class KnowledgeSettings(BaseModel):
    """知识库配置。

    Args:
        raw_dir: 知识源文件目录。
        external_dir: 外部知识库解析产物目录。
        index_path: JSONL 索引路径。
        top_k: 检索返回数量。
        chunk_size: 文本块最大字符数。
        chunk_overlap: 相邻文本块重叠字符数。
        bm25_weight: BM25 归一化得分权重。
        tfidf_weight: TF-IDF 余弦归一化得分权重。

    Returns:
        KnowledgeSettings: 经过校验的知识库配置。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> KnowledgeSettings(top_k=5)
        KnowledgeSettings(...)
    """

    model_config = ConfigDict(extra="forbid")

    raw_dir: Path = Path("knowledge/sources")
    external_dir: Path = Path("knowledge/external")
    index_path: Path = Path("knowledge/index.jsonl")
    top_k: int = Field(default=5, ge=1)
    chunk_size: int = Field(default=1200, ge=1)
    chunk_overlap: int = Field(default=120, ge=0)
    bm25_weight: float = Field(default=0.55, ge=0.0)
    tfidf_weight: float = Field(default=0.45, ge=0.0)

    @model_validator(mode="after")
    def _knowledge_weights_and_chunks_are_valid(self) -> "KnowledgeSettings":
        if self.chunk_overlap >= self.chunk_size:
            msg = "knowledge.chunk_overlap 必须小于 knowledge.chunk_size。"
            raise ValueError(msg)
        if not math.isfinite(self.bm25_weight) or not math.isfinite(self.tfidf_weight):
            msg = "knowledge.bm25_weight 与 knowledge.tfidf_weight 必须是有限数值。"
            raise ValueError(msg)
        if self.bm25_weight + self.tfidf_weight <= 0:
            msg = "knowledge.bm25_weight 与 knowledge.tfidf_weight 不能同时为 0。"
            raise ValueError(msg)
        return self


class OrchestratorSettings(BaseModel):
    """编排层配置。

    Args:
        mode: 编排模式。
        use_llm_agents: 是否允许 Agent 调用 LLM 生成结构化抽取和审阅输出。

    Returns:
        OrchestratorSettings: 经过校验的编排层配置。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> OrchestratorSettings()
        OrchestratorSettings(mode='dag', use_llm_agents=False)
    """

    model_config = ConfigDict(extra="forbid")

    mode: str = "dag"
    use_llm_agents: bool = False

    @field_validator("mode")
    @classmethod
    def _mode_must_be_supported(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"dag", "sequential"}:
            msg = "orchestrator.mode 支持 dag 或 sequential。"
            raise ValueError(msg)
        return normalized


class OutputSettings(BaseModel):
    """输出配置。

    Args:
        default_format: 默认报告格式。
        output_dir: 输出目录。

    Returns:
        OutputSettings: 经过校验的输出配置。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> OutputSettings(output_dir="mechagent_output")
        OutputSettings(default_format='markdown', output_dir=WindowsPath('mechagent_output'))
    """

    model_config = ConfigDict(extra="forbid")

    default_format: str = "markdown"
    output_dir: Path = Path("mechagent_output")

    @field_validator("default_format")
    @classmethod
    def _default_format_must_be_supported(cls, value: str) -> str:
        normalized = value.lower()
        if normalized != "markdown":
            msg = "output.default_format 支持 markdown。"
            raise ValueError(msg)
        return normalized


class MechAgentConfig(BaseModel):
    """MechAgent 全局配置。

    Args:
        llm: LLM 后端配置。
        solver: 求解器配置。
        mesher: 网格器配置。
        knowledge: 知识库配置。
        orchestrator: 编排层配置。
        output: 输出配置。

    Returns:
        MechAgentConfig: 经过校验的全局配置。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> MechAgentConfig()
        MechAgentConfig(...)
    """

    model_config = ConfigDict(extra="forbid")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    solver: SolverSettings = Field(default_factory=SolverSettings)
    mesher: MesherSettings = Field(default_factory=MesherSettings)
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)
    orchestrator: OrchestratorSettings = Field(default_factory=OrchestratorSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)


def config_to_public_dict(config: MechAgentConfig) -> dict[str, Any]:
    """导出隐藏敏感字段后的配置字典。

    Args:
        config: 全局配置对象。

    Returns:
        dict[str, Any]: 适合日志和诊断展示的配置字典。

    Raises:
        pydantic.ValidationError: 当模型序列化失败时抛出。

    Example:
        >>> public = config_to_public_dict(MechAgentConfig(llm={"api_key": "secret"}))
        >>> public["llm"]["api_key"]
        '***'
    """

    data = config.model_dump(mode="json")
    llm = data.get("llm")
    if isinstance(llm, dict) and llm.get("api_key"):
        llm["api_key"] = "***"
    return data


def maybe_config(data: Optional[dict[str, Any]]) -> MechAgentConfig:
    """将可选字典转换为全局配置。

    Args:
        data: 原始配置字典。

    Returns:
        MechAgentConfig: 全局配置对象。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> maybe_config(None)
        MechAgentConfig(...)
    """

    return MechAgentConfig.model_validate(data or {})


def _registered_config_name(
    value: str,
    registered: tuple[str, ...],
    setting_name: str,
    tool_label: str,
) -> str:
    normalized = value.strip().lower()
    if not normalized:
        msg = f"{setting_name} 不能为空。"
        raise ValueError(msg)
    if value.strip() != value:
        msg = f"{setting_name} 不能包含首尾空白。"
        raise ValueError(msg)
    if normalized not in registered:
        msg = f"{setting_name} 必须是已注册{tool_label}: {', '.join(registered)}。"
        raise ValueError(msg)
    return normalized

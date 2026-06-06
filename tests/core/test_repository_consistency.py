"""仓库文档与开源 CAE/FEA 多智能体定位一致性测试。"""

from __future__ import annotations

from pathlib import Path

from scripts.natural_language_cases import STATIC_LANGUAGE_CASES

from mechagent.config import KnowledgeSettings

TEXT_SUFFIXES = {".md", ".py", ".toml", ".yaml", ".yml", ".txt"}
LOCAL_ONLY_FILES = {Path("AGENTS.md"), Path("MechAgent_Project_Plan.docx")}
FORBIDDEN_TERMS = [
    "".join(["AB", "AQ", "US"]),
    "".join(["Aba", "qus"]),
    "".join(["aba", "qus"]),
    "".join(["Open", "FOAM"]),
    "".join(["open", "foam"]),
    "." + "odb",
    "packages/mechagent[agent]",
    "mechagent[agent]",
]
STALE_RELEASE_MARKERS = [
    "".join(["未实现", "承诺"]),
    "".join(["旧", "方案"]),
    "".join(["修改", "痕迹"]),
    "".join(["临时", "替代"]),
    "".join(["TO", "DO"]),
]
LOCAL_INSTALLATION_MARKERS = [
    "D:/Calculix",
    "D:/anaconda3",
    "ccx_MT.exe",
]
PUBLIC_DOCS = [
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("CONTRIBUTING.md"),
    Path("docs/index.md"),
    Path("docs/local_setup.md"),
    Path("docs/technical_report.md"),
    Path("packages/mechagent/README.md"),
    Path("packages/mechagent-core/README.md"),
]


def test_repository_has_no_non_scope_solver_terms() -> None:
    offenders: list[str] = []
    for path in _iter_text_files(Path(".")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for term in FORBIDDEN_TERMS:
            if term in text:
                offenders.append(f"{path}: {term}")

    assert offenders == []


def test_ignored_local_rule_and_plan_files_are_not_release_artifacts() -> None:
    ignore_text = Path(".gitignore").read_text(encoding="utf-8")

    assert "AGENTS.md" in ignore_text
    assert "MechAgent_Project_Plan.docx" in ignore_text
    assert not LOCAL_ONLY_FILES.intersection(PUBLIC_DOCS)


def test_env_example_contains_public_sample_values() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")

    assert "URL=https://example.com/v1" in text
    assert "API_KEY=replace-with-openai-compatible-api-key" in text
    assert "MODEL_NAME=replace-with-model-name" in text
    assert "CALCULIX_CCX=ccx" in text
    assert "tp-" not in text


def test_public_docs_have_no_stale_release_markers() -> None:
    offenders: list[str] = []
    for path in PUBLIC_DOCS:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in STALE_RELEASE_MARKERS:
            if marker in text:
                offenders.append(f"{path}: {marker}")

    assert offenders == []


def test_public_docs_describe_llm_structured_extraction() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    docs_index = Path("docs/index.md").read_text(encoding="utf-8")
    local_setup = Path("docs/local_setup.md").read_text(encoding="utf-8")
    package_readme = Path("packages/mechagent/README.md").read_text(encoding="utf-8")

    assert "LLM 生成 `ModelParams`" in readme
    assert "合并能力缺参诊断" in readme
    assert "`SimulationIntent.missing_fields` 非空时" in readme
    assert "本地 `ModelParams`" in readme
    assert "`model_case_ids`" in readme
    assert "SDK 单次覆盖使用独立配置副本" in readme
    assert "Planner 可让 LLM" in technical_report
    assert "注册能力自身的缺参诊断" in technical_report
    assert "缺参补齐与门禁" in technical_report
    assert "Designer 仍尝试 LLM 结构化补齐" in technical_report
    assert "本地参数优先" in technical_report
    assert "模型编号契约" in technical_report
    assert "不改变 `MechAgent.config`" in technical_report
    assert "远端 LLM 结构化抽取与\n审阅" in local_setup
    assert "Planner 已记录缺失字段时" in local_setup
    assert "后续链路使用本地参数" in local_setup
    assert "`ModelParams.case_id` 必须属于声明集合" in local_setup
    assert "SDK 单次覆盖使用独立配置副本" in local_setup
    assert "Designer 可调用\nLLM 生成 `ModelParams` JSON" in package_readme
    assert "合并能力缺参诊断" in package_readme
    assert "`SimulationIntent.missing_fields` 非空时" in package_readme
    assert "后续链路使用本地参数" in package_readme
    assert "`ModelParams.case_id` 必须属于声明集合" in package_readme
    assert "SDK 单次覆盖使用独立配置副本" in package_readme
    assert "不直接覆盖 `ModelParams`" not in technical_report
    assert "不直接覆盖 `ModelParams`" not in local_setup
    assert "Designer 不进行本地参数建模或 LLM 参数抽取" not in technical_report
    assert "技术细节索引" in docs_index
    assert "Agent 间通信和错误记录" in docs_index
    assert "LLM 结构化抽取和插件扩展契约" in docs_index
    assert "求解摘要状态、后处理摘要和失败优先规则" in docs_index


def test_package_source_has_no_local_installation_paths() -> None:
    offenders: list[str] = []
    for path in Path("packages").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in LOCAL_INSTALLATION_MARKERS:
            if marker in text:
                offenders.append(f"{path}: {marker}")

    assert offenders == []


def test_public_docs_match_current_test_and_case_counts() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")

    assert len(STATIC_LANGUAGE_CASES) == 20
    assert "测试集包含 336 个测试" in readme
    assert "完整测试范围、质量结果和清理策略见" in readme
    assert "`pytest`：336 passed" in technical_report
    for coverage_label in [
        "插件主结果字段推断",
        "插件数值字符串解析",
        "插件布尔字符串解析",
        "LLM provider 错误脱敏",
        "LLM 端到端 smoke 脚本",
        "trace error 脱敏",
        "报告通信摘要脱敏",
        "错误消息脱敏",
        "扩展字段递归脱敏",
        "映射导出脱敏",
        "advisory payload 脱敏",
        "空知识索引门禁",
        "MeshAgent 输出契约",
        "LLM 工程别名归一化",
        "LLM 中文结构化字段归一化",
        "Planner LLM 字符串意图归一化",
        "LLM 单对象载荷边界归一化",
        "LLM 空数组与单对象优先级归一化",
        "LLM 几何非线性布尔归一化",
        "求解失败摘要",
        "求解失败优先验收状态",
        "摘要失败优先归一化",
    ]:
        assert coverage_label in technical_report
    assert "与 `quantity`\n  同名的数值字段" in technical_report
    assert "有限数值字符串" in technical_report
    assert "不把任意非空字符串解释为真" in technical_report
    assert "嵌套 LLM trace 递归转换为公开摘要" in technical_report
    assert "`SolverRunSummary.to_mapping()`" in technical_report
    assert "部分 trace\n  映射使用显式布尔解析" in technical_report
    assert "`ErrorRecord` 前会脱敏" in technical_report
    assert "LLM HTTP 后端" in technical_report
    assert "中文几何类型、载荷类型、边界类型、方向、尺寸字段和材料字段" in technical_report
    assert "Markdown 报告通信摘要" in technical_report
    assert "`Requires-Dist` 依赖元数据、CLI entry point" in technical_report
    assert "`scripts/run_llm_smoke.py` 通过 SDK 启用 `use_llm_agents=True`" in technical_report
    assert "失败状态的 `SolverRunSummary`" in technical_report
    assert "即使主结果与参考值完全一致，也标记为 `failed`" in technical_report
    assert "`success` 为失败时，`passed` 固定为 `false`" in technical_report
    assert "`analysis.nlgeom` 使用显式布尔语义" in technical_report
    assert "能力编号按注册表编号做大小写、空白和连字符归一化" in technical_report
    assert "缺参字段可由字符串数组或" in technical_report
    assert "`ModelParams.loads` 和 `ModelParams.bcs` 数组" in technical_report
    assert "以非空对象或非空数组作为解析源" in technical_report


def test_public_docs_describe_capability_tool_contract() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    local_setup = Path("docs/local_setup.md").read_text(encoding="utf-8")
    package_readme = Path("packages/mechagent/README.md").read_text(encoding="utf-8")

    assert "能力默认工具注册契约" in readme
    assert "能力默认工具按注册表名称校验" in readme
    assert "能力默认工具在注册时规范化为工厂注册名" in readme
    assert "配置默认工具和能力默认工具均按工厂注册名称校验" in technical_report
    assert "能力默认工具在注册时规范化为工厂注册名" in technical_report
    assert "能力默认工具在注册时规范化为工厂注册名" in local_setup
    assert "能力默认工具使用工厂注册名称校验" in package_readme
    assert "规范化为工厂注册名" in package_readme


def test_public_docs_describe_langgraph_state_contract() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    package_readme = Path("packages/mechagent/README.md").read_text(encoding="utf-8")

    assert "LangGraph 状态契约校验" in readme
    assert "状态契约不一致时生成对应节点的" in technical_report
    assert "不会被 `zip()` 截断后从报告中静默消失" in technical_report
    assert "状态契约不一致时生成对应节点错误记录" in package_readme


def test_public_docs_describe_compound_request_handling() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    package_readme = Path("packages/mechagent/README.md").read_text(encoding="utf-8")

    assert "复合请求会拆分为独立任务" in readme
    assert "ambiguous_request" in readme
    assert "复合请求中的单个任务失败时" in readme
    assert "请求分段器" in technical_report
    assert "复合请求中的同类模型不会共享文件名" in technical_report
    assert "failed_records" in technical_report
    assert "复合请求拆分" in package_readme
    assert "其余任务继续执行" in package_readme


def test_public_docs_describe_parser_safety_boundaries() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    core_readme = Path("packages/mechagent-core/README.md").read_text(encoding="utf-8")

    assert "梁横向载荷和实体轴向载荷需要显式方向" in readme
    assert "梁纯全局 Y 向横向弯曲" in readme
    assert "矩形板纯全局 Z 向均布压力弯曲" in readme
    assert "矩形实体块纯全局 X 向端面轴向载荷" in readme
    assert "几何必需尺寸" in readme
    assert "不按内置钢/铝别名自动匹配" in readme
    assert "几何必需尺寸" in technical_report
    assert "几何必需尺寸" in core_readme
    assert "纯全局 Y 向端部集中力" in technical_report
    assert "纯全局 Z 向均布压力" in technical_report
    assert "纯全局 X 向端面压力" in technical_report
    assert "纯全局 Y 向端部集中力" in core_readme
    assert "纯全局 Z 向均布压力" in core_readme
    assert "纯全局 X 向端面压力" in core_readme
    assert "`载荷方向` 或 `端面载荷方向`" in technical_report
    assert "等效各向同性线弹性参数" in technical_report


def test_public_docs_describe_mesh_output_contract() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")

    assert "成功网格结果提供 `mesh_file`" in readme
    assert "质量指标为有限数值" in readme
    assert "`mesher.min_quality` 校验 `min_*`" in readme
    assert "MeshResult.quality` 中的数值均为有限数值" in technical_report
    assert "`max_*` 等上界指标不使用最小质量阈值判定" in technical_report


def test_public_docs_describe_finite_model_parameter_contract() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    core_readme = Path("packages/mechagent-core/README.md").read_text(encoding="utf-8")

    assert "核心仿真 schema 拒绝非有限控制数值" in readme
    assert "尺寸必须为有限正数" in technical_report
    assert "载荷幅值和方向向量必须为有限数值" in technical_report
    assert "`mesh.seed_size` 必须为有限正数" in technical_report
    assert "复合铺层数值均为有限数值" in core_readme
    finite_public_models = (
        "`MeshConfig.seed_size`、`MeshConfig.min_quality` 和 `SolverResult.wall_time`"
    )
    assert finite_public_models in technical_report
    assert finite_public_models in core_readme
    assert "非有限 `llm.temperature`、`mesher.min_quality`、`knowledge.bm25_weight`" in (
        technical_report
    )
    assert "公开检索函数 `query_index()` 在入口处拒绝非有限" in technical_report


def test_ci_workflow_matches_portable_quality_gate() -> None:
    workflow = Path(".github/workflows/pr.yml").read_text(encoding="utf-8")
    contributing = Path("CONTRIBUTING.md").read_text(encoding="utf-8")

    required_commands = [
        "actions/setup-python@v5",
        'python-version: "3.9"',
        "python scripts/check_env.py --profile portable",
        "python -m ruff format --check packages tests scripts",
        "python -m ruff check packages tests scripts",
        "python -m mypy packages scripts tests",
        'python -m pytest -m "not real_solver"',
        "python scripts/build_knowledge.py",
        "python scripts/index_knowledge.py",
        "python -m mechagent.cli config validate",
        "python -m pip check",
        "python -m build packages/mechagent-core --no-isolation",
        "python -m build packages/mechagent --no-isolation",
        "python scripts/check_wheel_install.py",
        "python -m mkdocs build --strict",
        "python scripts/clean_artifacts.py",
    ]
    missing = [command for command in required_commands if command not in workflow]
    forbidden_commands = [
        "D:/anaconda3",
        "self-hosted",
        "scripts/run_benchmarks.py",
        "scripts/run_natural_language_cases.py",
        "scripts/run_llm_smoke.py",
        "config validate --llm",
    ]
    forbidden = [command for command in forbidden_commands if command in workflow]
    assert missing == []
    assert forbidden == []
    assert "公开 PR 便携门禁" in contributing
    assert "不依赖本机 D 盘路径、CalculiX 可执行文件或远端 LLM 凭证" in contributing
    assert "维护者发布前运行本地完整门禁" in contributing


def test_public_quality_gate_docs_include_cleanup_step() -> None:
    docs = [
        Path("README.md"),
        Path("CONTRIBUTING.md"),
        Path("docs/index.md"),
        Path("docs/local_setup.md"),
        Path("docs/technical_report.md"),
    ]

    missing = [
        str(path)
        for path in docs
        if "scripts/clean_artifacts.py" not in path.read_text(encoding="utf-8")
    ]
    assert missing == []

    missing_llm_smoke = [
        str(path)
        for path in docs
        if "scripts/run_llm_smoke.py" not in path.read_text(encoding="utf-8")
    ]
    assert missing_llm_smoke == []

    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    quality_section = technical_report.split("## 质量结果", maxsplit=1)[1].split(
        "## 清理策略", maxsplit=1
    )[0]
    command_lines = [
        line.strip()
        for line in quality_section.splitlines()
        if line.startswith("D:/anaconda3/envs/GPT/python.exe")
    ]
    assert command_lines == list(dict.fromkeys(command_lines))


def test_public_knowledge_source_is_documented_and_configured() -> None:
    config = Path("config/mechagent.yaml").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    build_script = Path("scripts/build_knowledge.py").read_text(encoding="utf-8")
    document_module = Path("packages/mechagent/src/mechagent/knowledge/documents.py").read_text(
        encoding="utf-8"
    )

    assert "raw_dir: knowledge/sources" in config
    assert KnowledgeSettings().raw_dir == Path("knowledge/sources")
    assert Path("knowledge/sources/static_structural_validation.md").exists()
    assert Path("knowledge/sources/calculix_structural_workflow.md").exists()
    assert "默认知识源为 `knowledge/sources`" in readme
    assert "`knowledge/sources/` 是公开知识源目录" in technical_report
    assert "默认使用配置中的 knowledge.raw_dir" in build_script
    assert 'Path("knowledge/sources")' in document_module
    assert "knowledge/raw` 下的公开知识文件" not in build_script


def test_packages_publish_pep561_type_markers() -> None:
    app_pyproject = Path("packages/mechagent/pyproject.toml").read_text(encoding="utf-8")
    core_pyproject = Path("packages/mechagent-core/pyproject.toml").read_text(encoding="utf-8")

    assert Path("packages/mechagent/src/mechagent/py.typed").exists()
    assert Path("packages/mechagent-core/src/mechagent/core/py.typed").exists()
    assert 'mechagent = ["py.typed"]' in app_pyproject
    assert '"mechagent.core" = ["py.typed"]' in core_pyproject


def test_package_metadata_declares_open_source_release_fields() -> None:
    root_license = Path("LICENSE").read_text(encoding="utf-8")
    app_pyproject = Path("packages/mechagent/pyproject.toml").read_text(encoding="utf-8")
    core_pyproject = Path("packages/mechagent-core/pyproject.toml").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    for package_dir in (Path("packages/mechagent"), Path("packages/mechagent-core")):
        package_license = package_dir.joinpath("LICENSE").read_text(encoding="utf-8")
        assert package_license.strip() == root_license.strip()

    for pyproject in (app_pyproject, core_pyproject):
        assert 'requires = ["setuptools>=77", "wheel"]' in pyproject
        assert 'license = "Apache-2.0"' in pyproject
        assert 'license-files = ["LICENSE"]' in pyproject
        assert "Operating System :: OS Independent" in pyproject
        assert "Typing :: Typed" in pyproject

    assert "项目采用 Apache License 2.0" in readme


def test_llm_http_dependency_is_declared_consistently() -> None:
    app_pyproject = Path("packages/mechagent/pyproject.toml").read_text(encoding="utf-8")
    check_env = Path("scripts/check_env.py").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    old_backend = "".join(["lite", "llm"])

    assert '"httpx>=0.27,<1"' in app_pyproject
    assert '"httpx"' in check_env
    assert "`httpx` 直连 OpenAI 兼容 Chat Completions 接口" in changelog
    assert old_backend not in app_pyproject
    assert old_backend not in check_env
    assert old_backend not in changelog


def test_changelog_matches_current_natural_language_case_count() -> None:
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert len(STATIC_LANGUAGE_CASES) == 20
    assert "自然语言案例：二十个独立结构静力请求真实执行并通过验收" in changelog
    assert "十三个独立结构静力请求" not in changelog


def test_clean_artifact_docs_do_not_treat_env_file_as_generated_output() -> None:
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    local_setup = Path("docs/local_setup.md").read_text(encoding="utf-8")

    assert "- `.env`" not in technical_report
    assert ".env` 是本机私密配置文件" in technical_report
    assert "显式进程环境变量、\n配置文件同目录 `.env`、当前工作目录 `.env`" in local_setup
    assert "不写入进程级环境变量" in local_setup


def _iter_text_files(root: Path) -> list[Path]:
    skipped_parts = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "mechagent_output",
        "site",
    }
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and path not in LOCAL_ONLY_FILES
        and path.name != "test_repository_consistency.py"
        and not _is_generated_knowledge_path(path)
        and not skipped_parts.intersection(path.parts)
    ]


def _is_generated_knowledge_path(path: Path) -> bool:
    return (
        path == Path("knowledge/index.jsonl")
        or path.is_relative_to(Path("knowledge/raw"))
        or path.is_relative_to(Path("knowledge/external"))
    )

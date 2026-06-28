"""仓库文档与开源 CAE/FEA 多智能体定位一致性测试。

文档按主题组织：`docs/technical_report.md` 为汇总入口，技术内容分布在
`architecture`、`orchestration`、`capabilities`、`solver_mesh`、`validation` 专题页。
断言对这些专题页的并集（`_technical_text()`）做内容校验，避免绑定单一文件或排版。
前端断言校验模块化结构（`theme/`、`lib/`、`components/`）的稳定不变量，
而非绑定具体 CSS 声明或行内组件实现。
"""

from __future__ import annotations

from pathlib import Path

from scripts.natural_language_cases import STATIC_LANGUAGE_CASES

from mechagent.config import KnowledgeSettings
from mechagent.examples import all_examples

TEXT_SUFFIXES = {".md", ".py", ".toml", ".yaml", ".yml", ".txt"}
LOCAL_ONLY_FILES = {Path("AGENTS.md"), Path("CLAUDE.md")}
FORBIDDEN_TERMS = [
    "".join(["AB", "AQ", "US"]),
    "".join(["Aba", "qus"]),
    "".join(["aba", "qus"]),
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
TECHNICAL_DOCS = [
    Path("docs/architecture.md"),
    Path("docs/orchestration.md"),
    Path("docs/capabilities.md"),
    Path("docs/solver_mesh.md"),
    Path("docs/validation.md"),
]
PUBLIC_DOCS = [
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("CONTRIBUTING.md"),
    Path("docs/index.md"),
    Path("docs/product_blueprint.md"),
    Path("docs/development_plan.md"),
    Path("docs/studio_ui.md"),
    Path("docs/design_system.md"),
    Path("docs/frontend_architecture.md"),
    Path("docs/local_setup.md"),
    Path("docs/technical_report.md"),
    *TECHNICAL_DOCS,
    Path("packages/mechagent/README.md"),
    Path("packages/mechagent-core/README.md"),
]


def _read(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _technical_text() -> str:
    """技术专题页内容并集，用于跨拆分页的文档一致性校验。"""
    return "\n\n".join(doc.read_text(encoding="utf-8") for doc in TECHNICAL_DOCS)


def test_repository_has_no_non_scope_solver_terms() -> None:
    offenders: list[str] = []
    for path in _iter_text_files(Path(".")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for term in FORBIDDEN_TERMS:
            if term in text:
                offenders.append(f"{path}: {term}")

    assert offenders == []


def test_ignored_local_rule_and_plan_files_are_not_release_artifacts() -> None:
    ignore_text = _read(".gitignore")

    assert "AGENTS.md" in ignore_text
    assert "CLAUDE.md" in ignore_text
    assert not LOCAL_ONLY_FILES.intersection(PUBLIC_DOCS)


def test_env_example_contains_public_sample_values() -> None:
    text = _read(".env.example")

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


def test_public_installation_docs_describe_isolated_python_environment() -> None:
    setup_docs = [
        Path("README.md"),
        Path("CONTRIBUTING.md"),
        Path("docs/local_setup.md"),
    ]
    command_docs = [
        Path("README.md"),
        Path("CONTRIBUTING.md"),
        Path("docs/index.md"),
        Path("docs/local_setup.md"),
        Path("packages/mechagent/README.md"),
    ]

    for path in setup_docs:
        text = path.read_text(encoding="utf-8")
        assert "py -3.10 -m venv .venv" in text
        assert "conda create -n AGENT python=3.10 -y" in text
        assert 'python -m pip install -e "packages/mechagent[dev,docs]"' in text

    for path in command_docs:
        text = path.read_text(encoding="utf-8")
        assert "D:/anaconda3/envs/AGENT/python.exe" not in text

    technical = _technical_text()
    assert "安装环境使用 Python 3.10 及以上版本" in technical
    assert "`python` 指向当前虚拟环境解释器" in technical
    assert "D:/anaconda3/envs/AGENT/python.exe" in technical


def test_public_docs_describe_llm_structured_extraction() -> None:
    readme = _read("README.md")
    technical = _technical_text()
    docs_index = _read("docs/index.md")
    local_setup = _read("docs/local_setup.md")
    package_readme = _read("packages/mechagent/README.md")
    reporter_source = _read("packages/mechagent/src/mechagent/orchestrator/agents/reporter.py")

    assert "可选 OpenAI 兼容接口" in readme
    assert "LLM 工程解释章节" in readme
    assert "所有输出经过 schema、能力契约和脱敏规则处理" in readme
    assert "Planner 可让 LLM" in technical
    assert "注册能力自身的缺参诊断" in technical
    assert "缺参补齐与门禁" in technical
    assert "非关键工程审阅使用短超时和单次尝试" in technical
    assert "Designer 仍尝试 LLM 结构化补齐" in technical
    assert "本地参数优先" in technical
    assert "模型编号契约" in technical
    assert "不改变 `MechAgent.config`" in technical
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
    assert "确定性工程解读、可选 LLM 工程解释" in readme
    assert "ReporterAgent 始终基于 `TaskRunRecord` 写入确定性工程解读" in readme
    assert "结果结论、验收解释、网格与求解、模型材料、边界载荷、后处理标量和复核建议" in readme
    assert "Markdown 报告、确定性工程解读、可选 LLM 工程解释" in technical
    assert "ReporterAgent 不依赖远端 LLM 生成基础工程解释" in technical
    assert "结果结论、验收解释、网格与求解、模型材料、边界载荷、后处理标量和复核建议" in technical
    assert "Markdown 报告包含确定性工程解读" in package_readme
    assert "启用 LLM Agent 时追加 LLM 工程解释" in package_readme
    assert "_append_engineering_interpretation" in reporter_source
    assert "_engineering_interpretation_items" in reporter_source
    assert "_boundary_load_interpretation" in reporter_source
    assert "不直接覆盖 `ModelParams`" not in technical
    assert "Designer 不进行本地参数建模或 LLM 参数抽取" not in technical
    assert "文档导航" in docs_index
    assert "Agent 通信" in docs_index
    assert "LLM 接入" in docs_index


def test_package_source_has_no_local_installation_paths() -> None:
    offenders: list[str] = []
    for path in Path("packages").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in LOCAL_INSTALLATION_MARKERS:
            if marker in text:
                offenders.append(f"{path}: {marker}")

    assert offenders == []


def test_public_docs_match_current_test_and_case_counts() -> None:
    readme = _read("README.md")
    technical = _technical_text()

    assert len(STATIC_LANGUAGE_CASES) == 28
    assert len(all_examples()) == len(STATIC_LANGUAGE_CASES)
    assert [item.case_id for item in all_examples()] == [
        item.case_id for item in STATIC_LANGUAGE_CASES
    ]
    assert "测试集包含 451 个测试" in readme
    assert "完整测试范围、质量结果和清理策略见" in readme
    assert "`pytest`：451 passed" in technical
    for coverage_label in [
        "插件主结果字段推断",
        "插件数值字符串解析",
        "插件布尔字符串解析",
        "LLM provider 错误脱敏",
        "LLM 端到端 smoke 脚本",
        "LLM advisory 短超时策略",
        "trace error 脱敏",
        "报告执行链路摘要脱敏",
        "错误消息脱敏",
        "扩展字段递归脱敏",
        "映射导出脱敏",
        "advisory payload 脱敏",
        "空知识索引门禁",
        "MeshAgent 输出契约",
        "LLM 工程别名归一化",
        "LLM 中文结构化字段归一化",
        "LLM 多孔薄板孔洞归一化",
        "MeshAgent LLM 网格策略校验",
        "ReporterAgent 确定性工程解读报告",
        "ReporterAgent LLM 工程解释报告",
        "Planner LLM 字符串意图归一化",
        "LLM 单对象载荷边界归一化",
        "LLM 空数组与单对象优先级归一化",
        "LLM 几何非线性布尔归一化",
        "求解失败摘要",
        "求解失败优先验收状态",
        "摘要失败优先归一化",
    ]:
        assert coverage_label in technical
    assert "同名的数值字段" in technical
    assert "有限数值字符串" in technical
    assert "不把任意非空字符串解释为真" in technical
    assert "嵌套 LLM trace 递归转换为公开摘要" in technical
    assert "`SolverRunSummary.to_mapping()`" in technical
    assert "映射使用显式布尔解析" in technical
    assert "`ErrorRecord` 前会脱敏" in technical
    assert "LLM HTTP 后端" in technical
    assert "中文几何类型、载荷类型、边界类型、方向、尺寸字段和材料字段" in technical
    assert "Markdown 报告执行链路摘要" in technical
    assert "`Requires-Dist` 依赖元数据、CLI entry point" in technical
    assert "`scripts/run_llm_smoke.py` 通过 SDK 启用 `use_llm_agents=True`" in technical
    assert "Designer 结构化补参 trace 成功" in technical
    assert "审阅 trace 均已发起" in technical
    assert "失败状态的 `SolverRunSummary`" in technical
    assert "即使主结果与参考值完全一致，也标记为 `failed`" in technical
    assert "`success` 为失败时，`passed` 固定为 `false`" in technical
    assert "`analysis.nlgeom` 使用显式布尔语义" in technical
    assert "能力编号按注册表编号做大小写、空白和连字符归一化" in technical
    assert "缺参字段可由字符串数组或" in technical
    assert "`ModelParams.loads` 和 `ModelParams.bcs` 数组" in technical
    assert "以非空对象或非空数组作为解析源" in technical


def test_public_docs_describe_capability_tool_contract() -> None:
    readme = _read("README.md")
    technical = _technical_text()
    local_setup = _read("docs/local_setup.md")
    package_readme = _read("packages/mechagent/README.md")

    assert "能力默认工具注册契约" in readme
    assert "按注册表名称校验" in readme
    assert "规范化为工厂注册名" in readme or "归一化为工厂注册名" in readme
    assert "配置默认工具和能力默认工具均按工厂注册名称校验" in technical
    assert "能力默认工具在注册时规范化为工厂注册名" in technical
    assert "能力默认工具在注册时规范化为工厂注册名" in local_setup
    assert "能力默认工具使用工厂注册名称校验" in package_readme
    assert "规范化为工厂注册名" in package_readme


def test_public_docs_describe_langgraph_state_contract() -> None:
    readme = _read("README.md")
    technical = _technical_text()
    package_readme = _read("packages/mechagent/README.md")

    assert "LangGraph 状态契约校验" in readme
    assert "状态契约不一致时生成对应节点的" in technical
    assert "不会被 `zip()` 截断后从报告中静默消失" in technical
    assert "状态契约不一致时生成对应节点错误记录" in package_readme


def test_public_docs_describe_compound_request_handling() -> None:
    readme = _read("README.md")
    technical = _technical_text()
    package_readme = _read("packages/mechagent/README.md")

    assert "复合请求会拆分为独立任务" in readme
    assert "ambiguous_request" in readme
    assert "复合请求中的单个任务失败时" in readme
    assert "请求分段器" in technical
    assert "复合请求中的同类模型不会共享文件名" in technical
    assert "failed_records" in technical
    assert "复合请求拆分" in package_readme


def test_public_docs_describe_product_blueprint() -> None:
    readme = _read("README.md")
    docs_index = _read("docs/index.md")
    blueprint = _read("docs/product_blueprint.md")
    technical = _technical_text()
    package_readme = _read("packages/mechagent/README.md")

    assert "docs/product_blueprint.md" in readme
    assert "产品蓝图" in docs_index
    assert "3D 可视化目标" in blueprint
    assert "进度状态面板" in blueprint
    assert "Three.js" in blueprint
    assert "产品蓝图见" in technical
    assert "复合请求拆分" in package_readme
    assert "其余任务继续执行" in package_readme


def test_public_docs_describe_long_cycle_development_plan() -> None:
    readme = _read("README.md")
    docs_index = _read("docs/index.md")
    plan = _read("docs/development_plan.md")
    blueprint = _read("docs/product_blueprint.md")

    assert "docs/development_plan.md" in readme
    assert "长周期开发计划书" in docs_index
    assert "长周期开发计划书" in plan
    assert "能力成熟度模型" in plan
    assert "工具生态接入矩阵" in plan
    assert "里程碑与时间线" in plan
    assert "长周期开发计划书" in blueprint


def test_public_docs_describe_parser_safety_boundaries() -> None:
    readme = _read("README.md")
    technical = _technical_text()
    core_readme = _read("packages/mechagent-core/README.md")

    assert "梁横向载荷和实体轴向载荷需要显式方向" in readme
    assert "梁纯全局 Y 向横向弯曲" in readme
    assert "矩形板和开孔薄板纯全局 Z 向均布压力弯曲" in readme
    assert "矩形实体块纯全局 X 向端面轴向载荷" in readme
    assert "几何必需尺寸" in readme
    assert "不按内置钢/铝别名自动匹配" in readme
    assert "几何必需尺寸" in technical
    assert "几何必需尺寸" in core_readme
    assert "纯全局 Y 向端部集中力" in technical
    assert "纯全局 Z 向均布压力" in technical
    assert "纯全局 X 向端面压力" in technical
    assert "纯全局 Y 向端部集中力" in core_readme
    assert "纯全局 Z 向均布压力" in core_readme
    assert "纯全局 X 向端面压力" in core_readme
    assert "「载荷方向」或「端面载荷方向」" in technical
    assert "等效各向同性线弹性参数" in technical


def test_public_docs_describe_mesh_output_contract() -> None:
    readme = _read("README.md")
    technical = _technical_text()

    assert "成功网格结果提供 `mesh_file`" in readme
    assert "质量指标为有限数值" in readme
    assert "`mesher.min_quality` 校验 `min_*`" in readme
    assert "MeshResult.quality` 中的数值均为有限数值" in technical
    assert "`max_*` 等上界指标不使用最小质量阈值判定" in technical


def test_public_docs_describe_finite_model_parameter_contract() -> None:
    readme = _read("README.md")
    technical = _technical_text()
    core_readme = _read("packages/mechagent-core/README.md")

    assert "核心仿真 schema 拒绝非有限控制数值" in readme
    assert "尺寸必须为有限正数" in technical
    assert "载荷幅值和方向向量必须为有限数值" in technical
    assert "`mesh.seed_size` 必须为有限正数" in technical
    assert "复合铺层数值均为有限数值" in core_readme
    finite_public_models = (
        "`MeshConfig.seed_size`、`MeshConfig.min_quality` 和 `SolverResult.wall_time`"
    )
    assert finite_public_models in technical
    assert finite_public_models in core_readme
    assert "非有限 `llm.temperature`、`mesher.min_quality`、`knowledge.bm25_weight`" in technical
    assert "公开检索函数 `query_index()` 在入口处拒绝非有限" in technical


def test_ci_workflow_matches_portable_quality_gate() -> None:
    workflow = _read(".github/workflows/pr.yml")
    contributing = _read("CONTRIBUTING.md")

    required_commands = [
        "actions/setup-python@v6",
        'python-version: "3.10"',
        "actions/setup-node@v6",
        'node-version: "22"',
        "npm --prefix apps/mechagent-studio ci --no-audit --no-fund",
        "npm --prefix apps/mechagent-studio run build",
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
        Path("docs/local_setup.md"),
        Path("docs/validation.md"),
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

    validation = _read("docs/validation.md")
    quality_section = validation.split("## 质量结果", maxsplit=1)[1].split(
        "## 清理策略", maxsplit=1
    )[0]
    command_lines = [
        line.strip()
        for line in quality_section.splitlines()
        if line.startswith("python ") or line.startswith("npm ")
    ]
    assert command_lines == list(dict.fromkeys(command_lines))


def test_public_knowledge_source_is_documented_and_configured() -> None:
    config = _read("config/mechagent.yaml")
    readme = _read("README.md")
    technical = _technical_text()
    build_script = _read("scripts/build_knowledge.py")
    document_module = _read("packages/mechagent/src/mechagent/knowledge/documents.py")

    assert "raw_dir: knowledge/sources" in config
    assert KnowledgeSettings().raw_dir == Path("knowledge/sources")
    assert Path("knowledge/sources/static_structural_validation.md").exists()
    assert Path("knowledge/sources/calculix_structural_workflow.md").exists()
    assert "默认知识源为 `knowledge/sources`" in readme
    assert "`knowledge/sources/` 是公开知识源目录" in technical
    assert "默认使用配置中的 knowledge.raw_dir" in build_script
    assert 'Path("knowledge/sources")' in document_module
    assert "knowledge/raw` 下的公开知识文件" not in build_script


def test_packages_publish_pep561_type_markers() -> None:
    app_pyproject = _read("packages/mechagent/pyproject.toml")
    core_pyproject = _read("packages/mechagent-core/pyproject.toml")

    assert Path("packages/mechagent/src/mechagent/py.typed").exists()
    assert Path("packages/mechagent-core/src/mechagent/core/py.typed").exists()
    assert (
        'mechagent = ["py.typed", "ui/static/*", "ui/static/assets/*", "ui/static/brand/*"]'
        in app_pyproject
    )
    assert '"mechagent.core" = ["py.typed"]' in core_pyproject


def test_public_docs_describe_studio_surface() -> None:
    readme = _read("README.md")
    package_readme = _read("packages/mechagent/README.md")
    technical = _technical_text()
    studio_doc = _read("docs/studio_ui.md")
    local_setup = _read("docs/local_setup.md")
    docs_index = _read("docs/index.md")
    cli_source = _read("packages/mechagent/src/mechagent/cli/__init__.py")
    examples_source = _read("packages/mechagent/src/mechagent/examples.py")

    # CLI 入口在面向用户的文档中一致出现。
    for text in (package_readme, local_setup, docs_index):
        assert "python -m mechagent.cli doctor" in text
        assert "python -m mechagent.cli demo --llm-agents" in text
        assert "python -m mechagent.cli studio --open-browser" in text
        assert '--request "求解长480mm、宽280mm、厚6mm' in text
        assert "--llm-agents --view geometry --auto-run" in text
    assert "python -m mechagent.cli doctor" in readme
    assert "python -m mechagent.cli demo --llm-agents" in readme
    assert "python -m mechagent.cli studio --open-browser" in readme

    for text in (package_readme, local_setup, studio_doc):
        assert "`SC-27`" in text
        assert "--example" in text

    # README 描述新版 Studio 体验与展示图。
    assert "用智能体组织仿真流程" in readme
    assert "![MechAgent Studio 几何工作流](docs/assets/studio-geometry.png)" in readme
    assert "![MechAgent Studio 结果与报告](docs/assets/studio-workbench.png)" in readme
    assert "引导式工作流" in readme
    assert "明暗双主题" in readme
    assert "标签式检查器" in readme
    assert "界面以引导式工作流组织" in readme
    assert "工作台链接支持恢复请求、LLM 开关和视图模式" in readme
    assert (
        "CAD 支持范围为 STEP/IGES/BREP 形体摘要、包围盒几何候选和自然语言补全到结构静力参数"
        in readme
    )
    assert "当前验证范围不包含非线性材料、渐进损伤、接触和多物理场" in readme
    assert Path("docs/assets/studio-geometry.png").exists()
    assert Path("docs/assets/studio-workbench.png").exists()

    # Studio 使用指南与后端 API。
    assert "引导式工作流" in studio_doc
    assert "主题切换" in studio_doc
    assert "GET /api/health" in studio_doc
    assert "GET /api/diagnostics" in studio_doc
    assert "POST /api/run" in studio_doc
    assert "Studio 后端位于 `packages/mechagent/src/mechagent/ui/server.py`" in studio_doc

    # 技术专题保留求解可视化与质量来源描述。
    assert '`gmsh.model.mesh.getElementQualities(..., "minSICN")`' in technical
    assert "`MeshResult.quality.min_sicn`" in technical

    # 包 README 描述新版界面布局、主题与可视化。
    assert "引导式工作流" in package_readme
    assert "明暗双主题" in package_readme
    assert "标签式详情面板" in package_readme
    assert "Three.js" in package_readme
    assert "3D 场景由 Python 后处理层" in package_readme
    assert "Three.js 画布在初始化、尺寸变化、视图切换和用户交互时按需渲染" in package_readme
    for label in (
        "网格模式使用低透明单元面",
        "矩形截面分段棱柱",
        "右下角透明嵌入式 XYZ 全局坐标系",
        "默认显示 `U` 位移模量",
        "场量下拉菜单",
        "可切换 `Ux`、`Uy`、`Uz`",
        "可切换 `S Mises`",
    ):
        assert label in package_readme
    assert "Agent 链路面板读取公开摘要中的 `TaskItem`" in package_readme
    # Studio 使用指南描述视口交互。
    assert "场量" in studio_doc
    assert "视角" in studio_doc
    assert "图例" in studio_doc

    assert 'DEFAULT_SHOWCASE_EXAMPLE_ID = "SC-27"' in examples_source
    assert "def example_by_id" in examples_source
    assert "def showcase_example" in examples_source
    assert "@app.command()\ndef demo" in cli_source
    assert "--open-browser/--no-open-browser" in cli_source
    assert "--auto-run/--no-auto-run" in cli_source


def test_studio_frontend_uses_modular_themed_architecture() -> None:
    app = _read("apps/mechagent-studio/src/App.tsx")
    main = _read("apps/mechagent-studio/src/main.tsx")
    styles = _read("apps/mechagent-studio/src/styles.css")
    tokens = _read("apps/mechagent-studio/src/theme/tokens.css")
    themes = _read("apps/mechagent-studio/src/theme/themes.css")
    clipboard = _read("apps/mechagent-studio/src/lib/clipboard.ts")
    api = _read("apps/mechagent-studio/src/lib/api.ts")
    cli_lib = _read("apps/mechagent-studio/src/lib/cli.ts")
    url_lib = _read("apps/mechagent-studio/src/lib/url.ts")
    download = _read("apps/mechagent-studio/src/lib/download.ts")
    topbar = _read("apps/mechagent-studio/src/components/Topbar.tsx")
    inspector = _read("apps/mechagent-studio/src/components/Inspector.tsx")
    workspace = _read("apps/mechagent-studio/src/components/Workspace.tsx")
    three_viewport = _read("apps/mechagent-studio/src/ThreeViewport.tsx")

    # 主题层与明暗双主题。
    assert "ThemeProvider" in main
    assert "./theme/tokens.css" in main
    assert "./theme/themes.css" in main
    assert "--color-bg" in tokens or "--color-bg" in themes
    assert '[data-theme="dark"]' in themes
    assert "--color-primary" in themes
    assert "--color-viewport-bg" in themes
    assert "ThemeProvider" in _read("apps/mechagent-studio/src/theme/ThemeProvider.tsx")
    assert "prefers-color-scheme" in _read("apps/mechagent-studio/src/theme/ThemeProvider.tsx")

    # App.tsx 为编排壳，复用 hooks 与组件。
    assert "useStudioBootstrap" in app
    assert "useInspection" in app
    assert "useToast" in app
    assert "Topbar" in app
    assert "Composer" in app
    assert "SidePanel" in app
    assert "WorkflowStepper" in app
    assert "ViewportPanel" in app
    assert "ReportPanel" in app
    assert "InspectorRail" in app
    assert "copyTextToClipboard" in app
    assert "runSimulation" in app
    assert "ThreeViewport" in app

    # lib 集中副作用：fetch / 剪贴板 / 下载 / CLI / URL。
    assert 'fetch("/api/diagnostics")' in api
    assert "createJob" in api and "fetchJob" in api
    assert "legacyCopyText" in clipboard
    assert 'document.execCommand("copy")' in clipboard
    assert "reproducibleCliCommand" in cli_lib
    assert "powerShellQuote" in cli_lib
    assert '"--llm-agents"' in cli_lib
    assert "initialAutoRunFromUrl" in url_lib
    assert "applyWorkspaceQuery" in url_lib
    assert "history.replaceState" in url_lib
    assert "studioWorkspaceLink" in url_lib
    assert "downloadSummaryJson" in download
    assert "mechagent-${taskName}-${statusName}.json" in download
    assert "mechagent-${taskName}-${statusName}.md" in download

    # 顶栏主题切换与运行环境诊断。
    assert "ThemeToggle" in topbar
    assert "RuntimeDiagnosticsMenu" in topbar
    assert "diagnosticCheckDescription" in topbar
    assert "cyclePreference" in topbar

    # 检查器与工作区组件。
    assert "InspectorRail" in inspector
    assert "AgentChainPanel" in inspector
    assert "WorkflowStepper" in workspace
    assert "ViewportPanel" in workspace

    # 引导式工作流、标签式检查器、主题切换样式，令牌驱动与响应式。
    assert "var(--color-" in styles
    assert ".workflow-stepper" in styles
    assert ".theme-toggle" in styles
    assert ".inspector-tabs" in styles
    assert ".inspector-detail-panel" in styles
    assert "@media (max-width: 1279px)" in styles
    assert "@media (max-width: 899px)" in styles
    assert "toast-region" in app
    assert 'aria-live="polite"' in app

    # 3D 视口：按需渲染、场量切换、视角预设、主题感知背景。
    assert 'controls.addEventListener("change", scheduleRender)' in three_viewport
    assert "const animate = () =>" not in three_viewport
    assert "buildReferenceGrid" in three_viewport
    assert "buildSegmentedBeamBody" in three_viewport
    assert "buildAxisGizmoRoot" in three_viewport
    assert "field-switch" in three_viewport
    assert "setSelectedFieldKey(event.target.value)" in three_viewport
    assert "view-switch" in three_viewport
    assert "VIEW_PRESETS" in three_viewport
    assert "viewportClearColor" in three_viewport
    assert '"--color-viewport-bg"' in three_viewport
    assert "AxesHelper" not in three_viewport


def test_package_metadata_declares_open_source_release_fields() -> None:
    root_license = _read("LICENSE")
    app_pyproject = _read("packages/mechagent/pyproject.toml")
    core_pyproject = _read("packages/mechagent-core/pyproject.toml")
    readme = _read("README.md")

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
    app_pyproject = _read("packages/mechagent/pyproject.toml")
    check_env = _read("scripts/check_env.py")
    changelog = _read("CHANGELOG.md")
    old_backend = "".join(["lite", "llm"])

    assert '"httpx>=0.27,<1"' in app_pyproject
    assert '"httpx"' in check_env
    assert "`httpx` 直连 OpenAI 兼容 Chat Completions 接口" in changelog
    assert old_backend not in app_pyproject
    assert old_backend not in check_env
    assert old_backend not in changelog


def test_changelog_matches_current_natural_language_case_count() -> None:
    changelog = _read("CHANGELOG.md")

    assert len(STATIC_LANGUAGE_CASES) == 28
    assert "自然语言案例：二十八个独立结构静力请求真实执行并通过验收" in changelog
    assert "十三个独立结构静力请求" not in changelog


def test_clean_artifact_docs_do_not_treat_env_file_as_generated_output() -> None:
    technical = _technical_text()
    local_setup = _read("docs/local_setup.md")

    assert ".env` 是本机私密配置文件" in technical
    assert "显式进程环境变量、\n配置文件同目录 `.env`、当前工作目录 `.env`" in local_setup
    assert "不写入进程级环境变量" in local_setup


def _iter_text_files(root: Path) -> list[Path]:
    skipped_parts = {
        ".git",
        ".mypy_cache",
        "node_modules",
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

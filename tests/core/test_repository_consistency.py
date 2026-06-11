"""仓库文档与开源 CAE/FEA 多智能体定位一致性测试。"""

from __future__ import annotations

from pathlib import Path

from scripts.natural_language_cases import STATIC_LANGUAGE_CASES

from mechagent.config import KnowledgeSettings
from mechagent.examples import all_examples

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
    Path("docs/product_blueprint.md"),
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
        assert "py -3.9 -m venv .venv" in text
        assert "conda create -n mechagent python=3.9 -y" in text
        assert 'python -m pip install -e "packages/mechagent[dev,docs]"' in text

    for path in command_docs:
        text = path.read_text(encoding="utf-8")
        assert "D:/anaconda3/envs/GPT/python.exe" not in text

    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    assert "安装环境使用 Python 3.9 及以上版本" in technical_report
    assert "`python` 指向当前虚拟环境解释器" in technical_report
    assert "D:/anaconda3/envs/GPT/python.exe" in technical_report


def test_public_docs_describe_llm_structured_extraction() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    docs_index = Path("docs/index.md").read_text(encoding="utf-8")
    local_setup = Path("docs/local_setup.md").read_text(encoding="utf-8")
    package_readme = Path("packages/mechagent/README.md").read_text(encoding="utf-8")
    reporter_source = Path(
        "packages/mechagent/src/mechagent/orchestrator/agents/reporter.py"
    ).read_text(encoding="utf-8")

    assert "LLM 生成 `ModelParams`" in readme
    assert "合并能力缺参诊断" in readme
    assert "`SimulationIntent.missing_fields` 非空时" in readme
    assert "本地 `ModelParams`" in readme
    assert "`model_case_ids`" in readme
    assert "SDK 单次覆盖使用独立配置副本" in readme
    assert "Planner 可让 LLM" in technical_report
    assert "注册能力自身的缺参诊断" in technical_report
    assert "缺参补齐与门禁" in technical_report
    assert "非关键工程审阅使用短超时和单次尝试" in technical_report
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
    assert "确定性工程解读、可选 LLM 工程解释" in readme
    assert "ReporterAgent 始终基于 `TaskRunRecord` 写入确定性工程解读" in readme
    assert "结果结论、验收解释、网格与求解、模型材料、边界载荷、后处理标量和复核建议" in readme
    assert "Markdown 报告、确定性工程解读、可选 LLM 工程解释" in technical_report
    assert "ReporterAgent 不依赖远端 LLM 生成基础工程解释" in technical_report
    assert (
        "结果结论、验收解释、网格与求解、模型材料、边界载荷、后处理标量和复核建议"
        in technical_report
    )
    assert "Markdown 报告包含确定性工程解读" in package_readme
    assert "启用 LLM Agent 时追加 LLM 工程解释" in package_readme
    assert "_append_engineering_interpretation" in reporter_source
    assert "_engineering_interpretation_items" in reporter_source
    assert "_boundary_load_interpretation" in reporter_source
    assert "不直接覆盖 `ModelParams`" not in technical_report
    assert "不直接覆盖 `ModelParams`" not in local_setup
    assert "Designer 不进行本地参数建模或 LLM 参数抽取" not in technical_report
    assert "技术细节索引" in docs_index
    assert "结构化通信和错误记录" in docs_index
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

    assert len(STATIC_LANGUAGE_CASES) == 26
    assert len(all_examples()) == len(STATIC_LANGUAGE_CASES)
    assert [item.case_id for item in all_examples()] == [
        item.case_id for item in STATIC_LANGUAGE_CASES
    ]
    assert "测试集包含 407 个测试" in readme
    assert "完整测试范围、质量结果和清理策略见" in readme
    assert "`pytest`：404 passed" in technical_report
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
    assert "Markdown 报告执行链路摘要" in technical_report
    assert "`Requires-Dist` 依赖元数据、CLI entry point" in technical_report
    assert "`scripts/run_llm_smoke.py` 通过 SDK 启用 `use_llm_agents=True`" in technical_report
    assert "Designer 结构化补参 trace 成功且无错误" in technical_report
    assert "审阅 trace 已发起并记录 prompt" in technical_report
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
    assert "按注册表名称校验" in readme
    assert "规范化为工厂注册名" in readme or "归一化为工厂注册名" in readme
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


def test_public_docs_describe_product_blueprint() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    docs_index = Path("docs/index.md").read_text(encoding="utf-8")
    blueprint = Path("docs/product_blueprint.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    package_readme = Path("packages/mechagent/README.md").read_text(encoding="utf-8")

    assert "docs/product_blueprint.md" in readme
    assert "产品蓝图" in docs_index
    assert "3D 可视化目标" in blueprint
    assert "进度状态面板" in blueprint
    assert "Three.js" in blueprint
    assert "产品蓝图见" in technical_report
    assert "复合请求拆分" in package_readme
    assert "其余任务继续执行" in package_readme


def test_public_docs_describe_parser_safety_boundaries() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    core_readme = Path("packages/mechagent-core/README.md").read_text(encoding="utf-8")

    assert "梁横向载荷和实体轴向载荷需要显式方向" in readme
    assert "梁纯全局 Y 向横向弯曲" in readme
    assert "矩形板和开孔薄板纯全局 Z 向均布压力弯曲" in readme
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
        "actions/setup-python@v6",
        'python-version: "3.9"',
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
    assert 'mechagent = ["py.typed", "ui/static/*", "ui/static/assets/*"]' in app_pyproject
    assert '"mechagent.core" = ["py.typed"]' in core_pyproject


def test_public_docs_describe_studio_surface() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    package_readme = Path("packages/mechagent/README.md").read_text(encoding="utf-8")
    technical_report = Path("docs/technical_report.md").read_text(encoding="utf-8")
    local_setup = Path("docs/local_setup.md").read_text(encoding="utf-8")
    docs_index = Path("docs/index.md").read_text(encoding="utf-8")
    studio_app = Path("apps/mechagent-studio/src/App.tsx").read_text(encoding="utf-8")
    studio_styles = Path("apps/mechagent-studio/src/styles.css").read_text(encoding="utf-8")
    three_viewport = Path("apps/mechagent-studio/src/ThreeViewport.tsx").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/pr.yml").read_text(encoding="utf-8")
    cli_source = Path("packages/mechagent/src/mechagent/cli/__init__.py").read_text(
        encoding="utf-8"
    )
    examples_source = Path("packages/mechagent/src/mechagent/examples.py").read_text(
        encoding="utf-8"
    )

    for text in (readme, package_readme, local_setup, docs_index):
        assert "python -m mechagent.cli doctor" in text
        assert "python -m mechagent.cli demo --llm-agents" in text
        assert "python -m mechagent.cli studio --open-browser" in text
        assert '--request "求解长420mm、宽260mm、厚6mm' in text
        assert "--llm-agents --view geometry --auto-run" in text

    for text in (readme, package_readme, local_setup, technical_report):
        assert "`SC-23`" in text
        assert "--example" in text

    assert "FastAPI + React + TypeScript + Vite 工作台" in readme
    assert "![MechAgent Studio 几何可视化态](docs/assets/studio-geometry.png)" in readme
    assert "![MechAgent Studio 结果与工程解读态](docs/assets/studio-workbench.png)" in readme
    assert "几何可视化态展示自然语言输入、Planner 预检、偏心圆孔薄板参数化几何" in readme
    assert "结果与工程解读态展示开孔薄板 S Mises 应力云图" in readme
    assert "宽屏右侧检查区展示作业状态、验收状态、求解流程" in readme
    assert "几何模式显示 `ModelParams.loads` 与 `ModelParams.bcs` 对应的前处理符号" in readme
    assert "结果模式只显示变形、网格边、节点场、颜色图例和当前结果场" in readme
    assert "壳单元 `.frd` 派生节点场会按网格节点顺序对齐" in readme
    assert "重跑此请求" in readme
    assert "右侧承载状态" not in readme
    assert "右侧展示作业状态" not in readme
    assert Path("docs/assets/studio-geometry.png").exists()
    assert Path("docs/assets/studio-workbench.png").exists()
    assert not Path("docs/assets/studio-overview.png").exists()
    assert not Path("docs/assets/studio-result-viewport.png").exists()
    assert "studio-result-page.png" not in readme
    assert "studio-plate-case.png" not in readme
    assert "studio-beam-result.png" not in readme
    assert (
        "`docs/assets/studio-geometry.png` 和 `docs/assets/studio-workbench.png`"
        in technical_report
    )
    assert "符号直接贴合载荷面或约束边界且不带文字标注" in technical_report
    assert "结果模式只显示变形、网格边、节点场、颜色图例和当前结果场" in technical_report
    assert "Studio 后端位于 `packages/mechagent/src/mechagent/ui/server.py`" in technical_report
    assert "宽屏桌面视口展示左侧请求区、中央结果区和右侧检查区三栏布局" in technical_report
    assert "检查区：作业状态、验收状态、求解流程" in technical_report
    assert "结果视口、报告面板、验收面板、流程面板和阶段产物面板" in technical_report
    assert "doctor` 检查 Python 版本、Python 依赖、配置解析" in technical_report
    assert "GET /api/health" in technical_report
    assert "POST /api/run" in technical_report
    assert "`packages/mechagent/src/mechagent/ui/static`" in technical_report
    assert "lucide-react 和 react-markdown" in technical_report
    assert "React Flow" not in technical_report
    assert "Three.js" in package_readme
    assert "3D 场景由 Python 后处理层" in package_readme
    assert "Three.js 画布在初始化、尺寸变化、视图切换和用户交互时按需渲染" in package_readme
    assert "静止状态不运行连续 `requestAnimationFrame` 循环" in technical_report
    assert "当前 3D 画布支持 PNG 导出，SVG 用于兼容视图和静态下载" in package_readme
    for text in (readme, package_readme, technical_report):
        assert "网格模式使用低透明单元面" in text
        assert "矩形截面分段棱柱" in text
        assert "右下角透明嵌入式 XYZ 全局坐标系" in text
        assert "默认显示 `U` 位移模量" in text
        assert "场量下拉菜单" in text
        assert "可切换 `Ux`、`Uy`、`Uz`" in text
        assert "可切换 `S Mises`" in text
    assert "Markdown 报告和摘要 JSON 支持复制和下载" in package_readme
    assert "当前工作台链接复制" in package_readme
    assert "`request`、`llm` 和 `view` 查询参数" in package_readme
    assert "`run=1` 作为一次性自动运行信号" in package_readme
    assert "CLI 复现命令复制" in package_readme
    assert "带类型标签和路径复制入口的阶段产物" in package_readme
    assert "宽屏桌面视口采用左侧输入、中部结果、右侧检查器三栏布局" in readme
    assert "宽度不超过 1800px 时检查区位于主工作区下方并保持两列排布" in readme
    assert "宽屏桌面视口采用左侧输入、中部结果、右侧检查器三栏布局" in package_readme
    assert "宽度不超过 1800px 时检查区位于主工作区下方并保持两列排布" in package_readme
    assert "宽度不超过 900px" in package_readme
    assert "检查区在求解后跳到右侧" not in readme
    assert "运行前后保持左右外边距一致" in technical_report
    assert "前者展示几何模式下的偏心圆孔薄板、边界支承符号和均布压力箭头" in technical_report
    assert "后者展示开孔薄板 S Mises 应力云图" in technical_report
    assert "重跑此请求恢复几何、网格和结果视图" in technical_report
    assert "工作台链接复制" in technical_report
    assert "`request`、`llm` 和 `view` 查询参数" in technical_report
    assert "`--request`、`--llm-agents` 和 `--view geometry|mesh|result`" in technical_report
    assert "`--auto-run` 与 `--request` 同时使用" in technical_report
    assert (
        "`studio --request`、`--llm-agents`、`--view geometry|mesh|result` 和 `--auto-run`"
        in package_readme
    )
    assert "/studio?request=…&llm=1&view=…&run=1" in technical_report
    assert "`run=1` 是一次性自动运行信号" in technical_report
    assert "摘要 JSON 复制和摘要 JSON 下载" in technical_report
    assert "复制动作通过固定状态提示和 `aria-live` 区域反馈成功或失败" in technical_report
    assert "Clipboard API 和浏览器原生复制命令回退" in technical_report
    assert "复制动作带有可见状态反馈" in package_readme
    assert "重跑此请求" in package_readme
    assert "复制 CLI 复现命令" in studio_app
    assert "复制当前工作台链接" in studio_app
    assert "copyTextToClipboard" in studio_app
    assert "writeClipboardText" in studio_app
    assert "legacyCopyText" in studio_app
    assert 'document.execCommand("copy")' in studio_app
    assert "toast-region" in studio_app
    assert 'aria-live="polite"' in studio_app
    assert 'inputMode="text"' in studio_app
    assert 'className={`panel verification-panel ${result ? "has-result" : ""}`}' in studio_app
    assert "empty-action" in studio_app
    assert 'DEFAULT_SHOWCASE_EXAMPLE_ID = "SC-23"' in examples_source
    assert "def example_by_id" in examples_source
    assert "def showcase_example" in examples_source
    assert "@app.command()\ndef demo" in cli_source
    assert "--open-browser/--no-open-browser" in cli_source
    assert "--auto-run/--no-auto-run" in cli_source
    assert "minmax(0, clamp(280px, 18vw, 360px)) minmax(0, 1fr)" in studio_styles
    assert "clamp(320px, 17vw, 380px)" in studio_styles
    assert ".left-rail,\n.workspace,\n.right-rail {\n  min-width: 0;" in studio_styles
    assert ".right-rail {\n  max-width: 100%;" in studio_styles
    assert "grid-template-columns: minmax(0, 1fr);" in studio_styles
    result_right_rail_columns = ".right-rail.has-result {\n  grid-template-columns: minmax(0, 1fr);"
    assert result_right_rail_columns in studio_styles
    assert "@media (max-width: 1800px)" in studio_styles
    assert "grid-template-columns: minmax(280px, 320px) minmax(0, 1fr)" in studio_styles
    assert ".right-rail,\n  .right-rail.has-result {\n    grid-column: 1 / -1;" in studio_styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in studio_styles
    assert "grid-template-rows: auto auto minmax(150px, 1fr) auto" not in studio_styles
    assert ".verification-panel.has-result" in studio_styles
    adaptive_verification_panel = (
        ".right-rail.has-result .verification-panel.has-result {\n  height: auto;"
    )
    assert adaptive_verification_panel in studio_styles
    assert "min-height: max-content;" in studio_styles
    assert "padding-bottom: 16px" in studio_styles
    assert ".verification-list {\n  grid-template-columns: repeat(2, minmax(0, 1fr));" in (
        studio_styles
    )
    assert "min-height: 48px" in studio_styles
    assert "grid-template-columns: repeat(auto-fit, minmax(min(126px, 100%), 1fr));" in (
        studio_styles
    )
    assert "font-size: 11.5px;\n  line-height: 1.28;" in studio_styles
    assert "font-size: 13px;\n  line-height: 1.25;" in studio_styles
    assert "align-content: center" in studio_styles
    assert ".empty-action {" in studio_styles
    assert "height: 310px" not in studio_styles
    assert "overflow: visible" in studio_styles
    right_rail_style = studio_styles.split("\n.right-rail {\n")[-1].split(
        "}",
        maxsplit=1,
    )[0]
    assert "max-width: 100%" in right_rail_style
    assert "grid-template-columns: minmax(0, 1fr)" in right_rail_style
    assert "overflow-y: auto" in right_rail_style
    assert "padding-bottom: var(--layout-gutter)" in right_rail_style
    assert "scroll-padding-bottom: var(--layout-gutter)" in right_rail_style
    assert "scrollbar-gutter" not in right_rail_style
    assert "grid-auto-rows: 32px" in studio_styles
    assert "height: clamp(300px, 28vh, 312px)" in studio_styles
    assert "min-height: clamp(300px, 28vh, 312px)" in studio_styles
    result_right_rail_style = studio_styles.split(".right-rail.has-result {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "grid-template-rows: auto auto auto auto;" in result_right_rail_style
    assert ".right-rail.has-result .flow-panel {\n  grid-template-rows: auto auto;" in studio_styles
    assert "min-height: 304px" not in studio_styles
    assert "min-height: 0;\n  overflow: visible;" in studio_styles
    assert "padding: 0;\n  list-style: none;" in studio_styles
    assert 'controls.addEventListener("change", scheduleRender)' in three_viewport
    assert 'controls.removeEventListener("change", scheduleRender)' in three_viewport
    assert "const animate = () =>" not in three_viewport
    assert "controls.enableDamping = true" not in three_viewport
    assert "buildReferenceGrid" in three_viewport
    assert "位移云图" in three_viewport
    assert "应力云图" in three_viewport
    assert "真实网格" in three_viewport
    assert "示意网格" in three_viewport
    assert "buildSegmentedBeamBody" in three_viewport
    assert "buildBeamSegmentPrism" in three_viewport
    assert "buildBeamFixedMarker" in three_viewport
    assert "buildAxisGizmoRoot" in three_viewport
    assert "axis-gizmo-stage" in three_viewport
    assert "axis-gizmo-canvas" in three_viewport
    assert "AxesHelper" not in three_viewport
    assert "TubeGeometry" not in three_viewport
    assert "TorusGeometry" not in three_viewport
    assert "field-switch" in three_viewport
    assert "<select" in three_viewport
    assert "<option" in three_viewport
    assert "setSelectedFieldKey(event.target.value)" in three_viewport
    assert ".field-switch select" in studio_styles
    assert ".field-switch button" not in studio_styles
    assert ".axis-gizmo-stage" in studio_styles
    assert ".axis-gizmo-canvas" in studio_styles
    axis_gizmo_style = studio_styles.split(".axis-gizmo-stage {", maxsplit=1)[1].split(
        "}",
        maxsplit=1,
    )[0]
    assert "background:" not in axis_gizmo_style
    assert "border:" not in axis_gizmo_style
    assert "box-shadow" not in axis_gizmo_style
    assert "filter: drop-shadow" in axis_gizmo_style
    assert "strokeText(text, 64, 66)" in three_viewport
    assert "drawRoundedRect" not in three_viewport
    assert "view-switch" in three_viewport
    assert "VIEW_PRESETS" in three_viewport
    assert 'field.kind === "stress" ? 0.92 : 0.78' in three_viewport
    assert "depthTest: deformed" in three_viewport
    assert "buildBoundaryLoadOverlay" in three_viewport
    assert "buildBoundaryConditionMarker" in three_viewport
    assert "buildLoadMarker" in three_viewport
    assert "surfacePressureTargets" in three_viewport
    assert "dominantAxis" in three_viewport
    assert "distributedAxisValues" in three_viewport
    assert "isInsidePlateHole" in three_viewport
    assert "isEndFaceRegion" in three_viewport
    assert 'tokens.includes("face") && !tokens.includes("surface")' in three_viewport
    assert 'region.includes("face")' not in three_viewport
    assert "target.add(direction.clone().multiplyScalar(-tailDistance))" in three_viewport
    assert "pointArrowLength" in three_viewport
    assert "new THREE.ArrowHelper" not in three_viewport
    assert 'if (mode === "geometry")' in three_viewport
    assert "buildAnnotationLabel" not in three_viewport
    assert "简支边界" not in three_viewport
    assert "位移云图" in studio_app
    assert "场量提取" in studio_app
    assert "initialRequestFromUrl" in studio_app
    assert "initialParameterCompletionFromUrl" in studio_app
    assert "initialRenderModeIndexFromUrl" in studio_app
    assert "initialAutoRunFromUrl" in studio_app
    assert 'const AUTO_RUN_QUERY_KEY = "run"' in studio_app
    assert "autoRunRequested" in studio_app
    assert "removeAutoRunQuery" in studio_app
    assert "studioWorkspaceLink" in studio_app
    assert "history.replaceState" in studio_app
    assert "request" in studio_app
    assert "llm" in studio_app
    assert 'const VIEW_QUERY_KEY = "view"' in studio_app
    assert "url.searchParams.delete(AUTO_RUN_QUERY_KEY)" in studio_app
    assert "applyWorkspaceQuery(url, requestText, useLlmAgents, renderMode)" in studio_app
    assert "reproducibleCliCommand" in studio_app
    assert "python_executable" in studio_app
    assert "pythonLauncher" in studio_app
    assert "powerShellQuote" in studio_app
    assert '"--llm-agents"' in studio_app
    assert "下载 Markdown 工程报告" in studio_app
    assert "下载摘要 JSON" in studio_app
    assert "复制摘要 JSON" in studio_app
    assert "downloadSummaryJson" in studio_app
    assert "mechagent-${taskName}-${statusName}.json" in studio_app
    assert "复制阶段产物路径" in studio_app
    assert "mechagent-${taskName}-${statusName}.md" in studio_app
    assert "apps/mechagent-studio/node_modules/" in Path(".gitignore").read_text(encoding="utf-8")
    assert ".playwright-cli/" in Path(".gitignore").read_text(encoding="utf-8")
    assert "apps/mechagent-studio/node_modules" in Path("scripts/clean_artifacts.py").read_text(
        encoding="utf-8"
    )
    assert ".playwright-cli" in Path("scripts/clean_artifacts.py").read_text(encoding="utf-8")
    assert "actions/setup-node@v6" in workflow
    assert "clamp(320px, 17vw, 380px)" in studio_styles
    assert "clamp(300px, 20vw, 500px)" not in studio_styles
    assert "height: calc(100vh - 86px)" in studio_styles
    assert "grid-template-rows: minmax(310px, 0.78fr) minmax(330px, 1fr)" in studio_styles
    assert "height: auto" in studio_styles
    assert "height: clamp(460px, 62vh, 620px)" in studio_styles
    assert ".right-rail.has-result {\n    grid-template-columns: 1fr;" in studio_styles


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

    assert len(STATIC_LANGUAGE_CASES) == 26
    assert "自然语言案例：二十六个独立结构静力请求真实执行并通过验收" in changelog
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

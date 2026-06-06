# MechAgent

MechAgent 是面向开源 CAE/FEA 工作流的多智能体编排框架。用户用自然语言描述工程仿真需求，
框架将任务拆解为参数建模、网格划分、求解计算、后处理和 Markdown 报告生成。

项目本体负责 Agent 编排、结构化数据契约、工具适配、知识层和报告链路。求解器、网格器和
LLM 后端通过注册表与配置接入，不作为项目本体的固定实现边界。当前内置并验证的可执行能力是
结构线弹性静力分析，覆盖梁、矩形板和矩形实体块；扩展能力通过 `SimulationCapability`
注册。

## 核心能力

| 模块 | 当前实现 |
| --- | --- |
| SDK / CLI | `MechAgent` SDK 与 `python -m mechagent.cli` |
| Agent 编排 | 默认 LangGraph DAG，节点为 Planner、Designer、MeshAgent、SolverAgent、PostProcAgent、AnalystAgent、ReporterAgent；顺序工作流复用同一组 Agent |
| 能力注册 | `SimulationCapability` 声明 Planner 描述、默认网格器、默认求解器、请求分段器、解析器、执行契约、LLM 抽取契约、模型编号集合、模型归一化函数和结果评价器 |
| 自然语言解析 | 真实工程需求解析为 `ModelParams`；复合请求会拆分为独立任务，无法唯一拆分的请求记录为 `ambiguous_request` |
| LLM Agent | 默认关闭远端 LLM；启用后 Planner 可选择已注册能力并合并能力缺参诊断，Designer 可由 LLM 生成 `ModelParams` |
| 工具链 | 默认求解器为 CalculiX `ccx`，默认网格器注册名为 `calculix-inp`；矩形板路径调用 Gmsh Python API，梁和矩形实体块路径使用结构化网格 |
| 后处理与报告 | 解析 `.frd` 位移和应力标量，输出任务摘要、工程解读、错误诊断和阶段产物路径 |
| 知识库 | 默认知识源为 `knowledge/sources`，本地 JSONL 索引融合 BM25 与 TF-IDF 相似度 |

Agent 间通信使用 Pydantic v2 模型。`TaskItem.intent` 承载 `SimulationIntent`，Designer 输出
`DesignAgentOutput`，MeshAgent 输出 `MeshAgentOutput`，求解和后处理阶段输出结构化摘要。
SDK/CLI JSON 摘要只暴露脱敏 trace 元数据、错误状态和文本长度，不输出原始 prompt 或 response。
核心仿真 schema 拒绝非有限控制数值，几何尺寸、材料参数、载荷幅值/方向、边界值和网格尺寸必须为有限数值。

## 当前工程边界

内置结构静力能力经过真实 CalculiX 验证。梁横向载荷和实体轴向载荷需要显式方向；当前执行契约覆盖
梁纯全局 Y 向横向弯曲、矩形板纯全局 Z 向均布压力弯曲、矩形实体块纯全局 X 向端面轴向载荷。
几何必需尺寸、材料、载荷、边界、载荷区域和载荷方向在进入求解器前统一校验。
超出内置材料目录的材料可通过显式 `E` 和 `nu` 定义等效各向同性线弹性参数；混凝土、钢筋混凝土、
复合材料等名称不按内置钢/铝别名自动匹配。

能力默认工具注册契约要求能力默认工具按注册表名称校验，能力默认工具在注册时规范化为工厂注册名。
MeshAgent 要求成功网格结果提供 `mesh_file`，质量指标为有限数值，并按 `mesher.min_quality` 校验 `min_*`
质量指标。LangGraph 状态契约校验确保阶段产物数量与活动任务一致。
复合请求中的单个任务失败时，失败任务进入错误记录，其余任务继续执行。

## 安装

MechAgent 支持 Python 3.9 及以上版本。建议在独立虚拟环境中安装依赖，避免与系统
Python 或其他工程共享依赖。

Windows `venv`：
```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e packages/mechagent-core
python -m pip install -e "packages/mechagent[dev,docs]"
```

Conda：
```powershell
conda create -n mechagent python=3.9 -y
conda activate mechagent
python -m pip install --upgrade pip
python -m pip install -e packages/mechagent-core
python -m pip install -e "packages/mechagent[dev,docs]"
```

`config/mechagent.yaml` 使用 `${CALCULIX_CCX:-ccx}` 解析求解器路径。本机 `.env` 提供私密配置，
仓库只保留 `.env.example` 作为公开模板：

```text
URL=https://example.com/v1
API_KEY=replace-with-openai-compatible-api-key
MODEL_NAME=replace-with-model-name
CALCULIX_CCX=ccx
```

命令示例默认在已激活的虚拟环境中执行。CalculiX 可执行文件通过 `CALCULIX_CCX`
指向本机路径，也可以使用 PATH 中可直接调用的 `ccx`。

## 自然语言运行

梁静力分析：

```powershell
python -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
python -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力的静力响应" --json
```

矩形板静力分析：

```powershell
python -m mechagent.cli run "求解长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力的静力响应"
```

矩形实体块静力分析：

```powershell
python -m mechagent.cli run "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
```

启用远端 LLM Agent：

```powershell
python -m mechagent.cli run "solve a steel beam length 1000mm, section 20mm x 40mm, cantilever fixed at one end, downward 1000N tip force static analysis" --llm-agents --json
```

`orchestrator.use_llm_agents` 默认值为 `false`。SDK 单次调用可传入 `use_llm_agents=True`；
SDK 单次覆盖使用独立配置副本，不改变 `MechAgent.config` 的持久值。启用 LLM Agent 时，
`SimulationIntent.missing_fields` 非空时 Designer 仍尝试 LLM 结构化补齐。本地 parser 已生成验证通过的
本地 `ModelParams` 时，后续链路使用本地参数，LLM 输出进入 trace 审计；能力声明
`model_case_ids` 时，`ModelParams.case_id` 必须属于声明集合。

输出目录格式：

```text
mechagent_output/RUN_<timestamp>_<short_hash>/
  TASK_1/
  TASK_2/
  report.md
```

## 标准验证

```powershell
python scripts/run_benchmarks.py
python -m mechagent.cli benchmark --json
```

| 编号 | 问题 | 求解值 | 解析参考值 | 相对误差 | 阈值 |
| --- | --- | ---: | ---: | ---: | ---: |
| TC-01 | 悬臂梁端点静力，线弹性 | 14.896 mm | 14.880952 mm | 0.101120% | 1% |
| TC-02 | 四边简支矩形薄板均布载荷弯曲 | 0.155959 mm | 0.154233 mm | 1.118913% | 2% |
| TC-03 | 固支长方体端面轴向拉伸 | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% |
| TC-04 | 悬臂梁全跨均布线载荷静力弯曲 | 5.58805 mm | 5.580357 mm | 0.137856% | 2% |
| TC-05 | 固支长方体端面合力轴向拉伸 | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% |

独立自然语言案例和 LLM 全链路 smoke：

```powershell
python scripts/run_natural_language_cases.py
python scripts/run_llm_smoke.py
```

## 质量门禁

```powershell
python scripts/check_env.py
python -m ruff format packages tests scripts
python -m ruff check packages tests scripts
python -m mypy packages scripts tests
python -m pytest
python scripts/run_benchmarks.py
python scripts/run_natural_language_cases.py
python scripts/run_llm_smoke.py
python scripts/build_knowledge.py
python scripts/index_knowledge.py
python -m mechagent.cli config validate
python -m mechagent.cli config validate --llm
python -m pip check
python -m build packages/mechagent-core --no-isolation
python -m build packages/mechagent --no-isolation
python scripts/check_wheel_install.py
python -m mkdocs build --strict
python scripts/clean_artifacts.py
```

测试集包含 337 个测试，覆盖公开 API、编排、LLM、知识库、MeshAgent 输出契约、求解失败归一化、
LangGraph 状态契约校验、自然语言案例和真实 CalculiX 验证。完整测试范围、质量结果和清理策略见
`docs/technical_report.md`。

## 文档

- `docs/index.md`：文档入口和技术细节索引。
- `docs/local_setup.md`：本地 Python、CalculiX、Gmsh、LLM 和验证命令。
- `docs/technical_report.md`：架构、Agent 通信、核心 schema、LLM 契约、网格/求解适配器、
  解析参考公式、TC-01 至 TC-05、二十个自然语言案例、质量结果和清理策略。

## 目录结构

```text
packages/
  mechagent-core/   # 求解器、网格器、后处理、数据模型和解析参考
  mechagent/        # SDK、CLI、LLM、编排层、知识层
config/             # 全局运行配置
knowledge/sources/  # 可随仓库发布的公开知识源
scripts/            # 环境检查、验证、知识库构建、发布检查和清理脚本
tests/              # 单元测试、工作流测试、自然语言案例和精度验证测试
docs/               # 本地配置和技术报告
```

## 许可

项目采用 Apache License 2.0。根目录和两个可发布 Python 包均包含许可证文件。

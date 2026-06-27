# MechAgent

MechAgent 是一个面向开源 CAE/FEA 工作流的多智能体仿真框架。它提供本地 Studio 工作台、CLI 和 Python SDK，把自然语言工程需求转换为可执行、可审计、可复现的仿真任务链路。

项目关注的是“用智能体组织仿真流程”，不是重新实现一个有限元求解器。求解器、网格器、知识库和 LLM 后端通过配置与注册表接入；Agent 层负责需求理解、参数建模、网格策略、求解调用、结果提取、工程校核和报告生成。

当前发布能力聚焦结构线弹性静力分析，内置 CalculiX 与 Gmsh 适配，支持梁、薄板、圆孔/多孔/槽孔开孔薄板和实体块等参数化模型族。项目同时保留清晰的能力边界和扩展契约，便于继续接入新的几何类型、材料模型、求解器、网格器和后处理策略。

## Studio 展示

Studio 采用引导式工作流（输入 → 预检 → 运行 → 结果）、明暗双主题、自适应三栏布局和可折叠检查器。

![MechAgent Studio 几何工作流](docs/assets/studio-geometry.png)

Studio 支持从自然语言请求进入任务预检、参数建模、边界与载荷表达、求解流程跟踪和阶段产物检查。

![MechAgent Studio 结果与报告](docs/assets/studio-workbench.png)

求解完成后，Studio 展示 3D 结果场、网格、验收摘要、阶段产物、结构化摘要和 Markdown 工程报告。

顶栏主题切换支持「明 / 暗 / 跟随系统」三态，3D 视口背景随主题同步。界面使用与设计可参考 [docs/studio_ui.md](docs/studio_ui.md) 和 [docs/design_system.md](docs/design_system.md)。

## 使用场景

- 用自然语言提交结构静力仿真需求，并自动生成可复现的求解任务。
- 在浏览器中查看几何、网格、结果、流程状态、验收指标和工程报告。
- 用 CLI 在终端或 CI 中执行预检、求解、基准验证和报告生成。
- 用 Python SDK 将 MechAgent 集成到批处理、内部平台或更大的工程自动化系统。
- 通过注册表接入新的能力、工具、材料库、知识源和 LLM 后端。

## 快速开始

MechAgent 支持 Python 3.10 及以上版本。建议在独立虚拟环境中安装依赖。

Windows `venv`：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e packages/mechagent-core
python -m pip install -e "packages/mechagent[dev,docs]"
```

Conda：

```powershell
conda create -n AGENT python=3.10 -y
conda activate AGENT
python -m pip install --upgrade pip
python -m pip install -e packages/mechagent-core
python -m pip install -e "packages/mechagent[dev,docs]"
```

公开配置模板位于 `.env.example`。本地私密配置写入 `.env` 或环境变量：

```text
URL=https://example.com/v1
API_KEY=replace-with-openai-compatible-api-key
MODEL_NAME=replace-with-model-name
CALCULIX_CCX=ccx
```

`CALCULIX_CCX` 指向本机 CalculiX `ccx` 可执行文件；如果 `ccx` 已在 PATH 中可用，可保留默认值。

环境自检：

```powershell
python -m mechagent.cli doctor
python -m mechagent.cli doctor --json
python -m mechagent.cli doctor --llm
```

启动 Studio：

```powershell
python -m mechagent.cli demo --llm-agents
python -m mechagent.cli studio --open-browser
python -m mechagent.cli studio --open-browser --request "<自然语言仿真请求>" --llm-agents --view geometry --auto-run
```

终端运行：

```powershell
python -m mechagent.cli capabilities
python -m mechagent.cli examples
python -m mechagent.cli inspect "<自然语言仿真请求>" --json
python -m mechagent.cli run "<自然语言仿真请求>" --llm-agents
```

## 工作流

```text
自然语言请求
  -> Planner：任务识别、能力选择和缺项诊断
  -> Designer：参数化模型生成和 schema 校验
  -> MeshAgent：网格策略生成、网格划分和质量检查
  -> SolverAgent：求解器输入生成和求解执行
  -> PostProcAgent：结果文件解析、场量提取和摘要生成
  -> AnalystAgent：参考解、阈值和工程验收
  -> ReporterAgent：确定性报告与可选 LLM 工程解释
```

Agent 间通信使用 Pydantic v2 模型作为结构化契约。SDK/CLI 输出的 JSON 摘要只暴露脱敏 trace、状态、路径、指标和报告文本，不输出原始 LLM prompt 或 response。

## 核心契约

- 复合请求会拆分为独立任务；无法唯一拆分的请求记录为 `ambiguous_request`。复合请求中的单个任务失败时，失败任务进入错误记录，其余任务继续执行。
- 核心仿真 schema 拒绝非有限控制数值，几何、材料、载荷、边界和网格参数进入工具层前必须通过校验。
- 能力默认工具注册契约按注册表名称校验求解器、网格器和能力绑定，注册时归一化为工厂注册名。
- MeshAgent 要求成功网格结果提供 `mesh_file`，质量指标为有限数值，并按 `mesher.min_quality` 校验 `min_*` 质量指标。
- LangGraph 状态契约校验活动任务、阶段产物、错误记录和最终摘要的一致性。
- 默认知识源为 `knowledge/sources`，本地索引用于能力说明、工程规则和报告语境检索。

## 产品入口

| 入口 | 用途 |
| --- | --- |
| MechAgent Studio | 本地浏览器工作台，面向交互式建模、求解、可视化和报告检查 |
| CLI | 面向终端、脚本、CI 和批处理的预检、求解、验证和诊断入口 |
| Python SDK | 面向二次开发、平台集成、能力扩展和自动化工作流 |

Studio 默认监听 `127.0.0.1:8765`。界面以引导式工作流组织：顶栏（品牌、运行状态、运行环境诊断、明暗主题切换）、贯穿式进度（输入 → 预检 → 运行 → 结果）、左栏（自然语言请求、任务预检、参数补全开关、工况库、运行历史、模型摘要）、中区（3D 几何/网格/结果视口、任务结果矩阵、Markdown 报告）、右栏可折叠检查器（验收状态、求解流程、Agent 链路、阶段产物、摘要 JSON）。布局在宽屏/笔记本/窄屏间自适应。工作台链接支持恢复请求、LLM 开关和视图模式；报告、摘要和复现命令均可复制或下载。

## 可视化与报告

Studio 的可视化层服务于完整仿真工作流，而不是单个固定算例。几何视图用于检查参数化模型、边界条件和载荷施加；网格视图用于检查单元拓扑、节点、孔洞边界和局部网格质量；结果视图用于查看变形、位移场、可用应力场和场量范围。后处理数据来自求解摘要、网格文件和结果文件，前端只负责把结构化结果表达为可交互视图。Agent 链路面板展示各阶段结构化产物、网格质量诊断和脱敏 LLM trace 摘要，不暴露原始 prompt、response 或密钥。

报告层由 ReporterAgent 生成，包含任务摘要、模型与载荷说明、网格与求解说明、结果解释、验收结论、复核建议和阶段产物路径。Markdown 报告包含确定性工程解读、可选 LLM 工程解释和执行链路摘要。ReporterAgent 始终基于 `TaskRunRecord` 写入确定性工程解读，内容覆盖结果结论、验收解释、网格与求解、模型材料、边界载荷、后处理标量和复核建议。启用 LLM Agent 时，系统会把脱敏后的结构化 FEM 结果交给 LLM 生成工程解释，并保留本地确定性报告内容作为基线。

## 架构模块

| 模块 | 职责 |
| --- | --- |
| `mechagent-core` | 数据模型、求解器适配、网格器适配、后处理和验证基准 |
| `mechagent` | SDK、CLI、Studio 后端、LLM 接入、知识库和编排层 |
| Studio 前端 | React、TypeScript、Vite 和 3D 结果视口 |
| 能力注册 | 用 `SimulationCapability` 绑定自然语言解析器、工具、schema、模型族和评价器 |
| 编排层 | LangGraph DAG 与顺序工作流共享同一组 Agent 和数据契约 |
| 工具层 | CalculiX、Gmsh 和后续外部工具通过配置与注册表接入 |
| 知识与 LLM | 本地知识索引、OpenAI 兼容接口、结构化抽取和工程解释生成 |

## 已发布能力矩阵

| 能力域 | 当前状态 | 产物 |
| --- | --- | --- |
| 自然语言入口 | 中英文结构静力需求解析、复合请求拆分、缺参诊断、可执行性预检 | `SimulationIntent`、`TaskItem`、预检摘要 |
| 参数化建模 | 梁、矩形薄板、单孔/偏心孔/多孔/槽孔薄板、矩形实体块 | `ModelParams`、几何视图、边界与载荷符号 |
| 网格划分 | 结构化梁/实体网格、Gmsh OCC 薄板与开孔薄板网格、开孔局部尺度控制、质量指标门禁 | `.inp`、节点/单元数量、`min_sicn`、`mean_sicn` |
| 求解与后处理 | CalculiX 静力求解、`.frd` 位移/应力场解析、主结果提取 | `SolverRunSummary`、`PostProcessingSummary` |
| 工程校核 | TC-01 至 TC-05 解析参考验收，缺少参考值的工程场景标记为未验证 | 计算值、参考值、相对误差、阈值、状态 |
| 报告与可视化 | Studio 3D 几何/网格/结果视图、Markdown 工程报告、摘要 JSON | 报告文件、阶段产物、可复现命令 |
| LLM Agent | 可选 OpenAI 兼容接口，参与能力选择、参数补全、网格策略建议和工程解释 | 脱敏 trace、LLM 工程解释章节 |

## 当前边界

- 已验证能力：结构线弹性静力分析。
- 已接入工具：CalculiX 求解器、Gmsh 网格能力、本地结构化网格生成和网格质量门禁。
- 已覆盖模型族：梁、矩形薄板、圆孔/多孔/槽孔开孔薄板和矩形实体块。
- 材料模型：各向同性线弹性材料，支持内置材料别名和显式 `E`、`nu` 参数。
- LLM 使用：默认关闭；启用后参与能力选择、参数补全、网格策略建议和工程解释，所有输出经过 schema、能力契约和脱敏规则处理。
- 解析边界：梁横向载荷和实体轴向载荷需要显式方向，当前执行契约覆盖梁纯全局 Y 向横向弯曲、矩形板和开孔薄板纯全局 Z 向均布压力弯曲、矩形实体块纯全局 X 向端面轴向载荷。几何必需尺寸、载荷区域和载荷方向在进入求解器前统一校验。
- 材料边界：超出内置材料目录的材料可通过显式 `E` 和 `nu` 定义等效各向同性线弹性参数；混凝土、钢筋混凝土、复合材料等名称不按内置钢/铝别名自动匹配。
- 当前验证范围不包含非线性材料、渐进损伤、接触、多物理场和任意 CAD 导入。

完整长周期开发计划见 [docs/development_plan.md](docs/development_plan.md)；产品路线、扩展边界和技术细节见 [docs/product_blueprint.md](docs/product_blueprint.md) 与 [docs/technical_report.md](docs/technical_report.md)。

## 后续路线

| 方向 | 目标 | 验收方式 |
| --- | --- | --- |
| 复杂几何前处理 | 参数化零件库、CAD 导入、特征识别、几何修复和边界/载荷区域映射 | CAD 样例、几何修复诊断、网格质量证据、真实求解结果 |
| 智能网格策略 | 自适应网格、局部加密建议、网格收敛检查和多网格器接入 | 网格收敛曲线、质量指标、跨网格器对比 |
| 非线性与高级结构分析 | 几何非线性、材料非线性、接触、渐进损伤、屈曲和模态分析 | 参考解、工程基准、跨工具对比和报告字段 |
| 多物理场 | 热分析、热-结构耦合和瞬态动力学 | 多场量后处理、守恒量检查和端到端案例 |
| 工程协作 | 批量任务、远程工作站执行、作业队列、结果归档和审计追踪 | 队列任务验收、产物索引、可复现实验记录 |

## 验证

标准验证使用真实 CalculiX 求解结果与解析参考值对比，覆盖结构静力求解链路、网格生成、后处理、误差评价和报告输出。完整验证表和数值结果见 [docs/technical_report.md](docs/technical_report.md)。

```powershell
python scripts/run_benchmarks.py
python -m mechagent.cli benchmark --json
python scripts/run_natural_language_cases.py
python scripts/run_llm_smoke.py
```

质量门禁：

```powershell
python -m mechagent.cli doctor
python scripts/check_env.py
npm --prefix apps/mechagent-studio ci --no-audit --no-fund
npm --prefix apps/mechagent-studio run build
python -m ruff format packages tests scripts
python -m ruff check packages tests scripts
python -m mypy packages scripts tests
python -m pytest
python scripts/run_benchmarks.py
python scripts/run_natural_language_cases.py
python scripts/run_llm_smoke.py
python -m mechagent.cli config validate
python -m pip check
python -m build packages/mechagent-core --no-isolation
python -m build packages/mechagent --no-isolation
python scripts/check_wheel_install.py
python -m mkdocs build --strict
python scripts/clean_artifacts.py
```

当前测试集包含 451 个测试，覆盖公开 API、Studio 服务、编排、LLM、知识库、网格契约、求解失败归一化、LangGraph 状态契约、自然语言案例、运行前预检、CAD 几何到求解链路和真实 CalculiX 验证。完整测试范围、质量结果和清理策略见 [docs/technical_report.md](docs/technical_report.md)。

## 文档

- [docs/index.md](docs/index.md)：文档门户与导航。
- [docs/product_blueprint.md](docs/product_blueprint.md)：产品定位、能力模型、Studio 体验、路线图和扩展边界。
- [docs/development_plan.md](docs/development_plan.md)：长周期开发计划书（通用 CAE 智能体平台愿景、物理域路线图、工具生态、里程碑与治理）。
- [docs/studio_ui.md](docs/studio_ui.md)：Studio 使用指南、引导式工作流、主题切换、3D 视口交互与后端 API。
- [docs/design_system.md](docs/design_system.md)：设计令牌、配色、明暗主题、组件清单与响应式断点。
- [docs/frontend_architecture.md](docs/frontend_architecture.md)：前端目录结构、模块边界、样式约定与构建流程。
- [docs/architecture.md](docs/architecture.md)、[docs/orchestration.md](docs/orchestration.md)、[docs/capabilities.md](docs/capabilities.md)、[docs/solver_mesh.md](docs/solver_mesh.md)：系统架构、编排、能力与求解实现。
- [docs/validation.md](docs/validation.md)：标准验证、自然语言案例、质量门禁与测试覆盖。
- [docs/local_setup.md](docs/local_setup.md)：本地 Python、CalculiX、Gmsh、LLM 和验证命令。

## 目录结构

```text
packages/
  mechagent-core/   # 求解器、网格器、后处理、数据模型和解析参考
  mechagent/        # SDK、CLI、Studio 服务、LLM、编排层和知识层
apps/
  mechagent-studio/ # Studio 前端源码
config/             # 全局运行配置
knowledge/sources/  # 可随仓库发布的公开知识源
scripts/            # 环境检查、验证、知识库构建、发布检查和清理脚本
tests/              # 单元测试、工作流测试、自然语言案例和精度验证测试
docs/               # 本地配置、产品蓝图和技术报告
```

## 许可

项目采用 Apache License 2.0。根目录和两个可发布 Python 包均包含许可证文件。

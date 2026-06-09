# MechAgent 技术报告

## 项目定位

MechAgent 是面向开源 CAE/FEA 工作流的多智能体编排框架。项目本体负责自然语言任务
理解、Agent 编排、Schema 约束、工具适配、后处理和报告生成；CalculiX、Gmsh、LLM
和知识库位于后端边界。

内置执行路径覆盖结构线弹性静力分析，支持梁、矩形板和矩形实体块三类几何。标准验证算例
用于精度回归，生产入口接收真实工程仿真需求描述，不接收测试编号作为工作流任务。

## 本机环境

| 项目 | 配置 |
| --- | --- |
| 操作系统 | Windows 11 |
| Python 执行器 | `D:/anaconda3/envs/GPT/python.exe` |
| Python 版本 | 3.9.25 |
| Node.js | Studio 前端开发与构建使用 Node.js 22 及以上版本 |
| CalculiX | `config/mechagent.yaml` 使用 `${CALCULIX_CCX:-ccx}`，本机 `.env` 指向 `D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe` |
| Gmsh | Python 包 `gmsh` |
| LLM | OpenAI 兼容接口，`.env` 注入 `URL`、`API_KEY`、`MODEL_NAME` |

求解器路径由配置和本机私有环境变量共同确定，不依赖系统 PATH。Python 依赖通过 `pip check` 验证。
`MechAgent.from_config()` 展开 `${VAR:-default}` 时保留显式环境变量优先级；配置文件同目录
`.env` 优先于当前工作目录 `.env`。`.env` 内容只参与当前配置解析，不写入进程级环境变量。

安装环境使用 Python 3.9 及以上版本。用户创建独立 `venv` 或 Conda 环境，激活后通过
`python -m pip install -e packages/mechagent-core` 和
`python -m pip install -e "packages/mechagent[dev,docs]"` 安装依赖。公开命令示例中的
`python` 指向当前虚拟环境解释器。

## 包结构

```text
packages/
  mechagent-core/
    src/mechagent/core/
      models/          # Pydantic v2 仿真参数 schema
      adapters/        # CalculiX 与标准几何网格适配器
      materials.py     # 内置材料目录
      solver.py        # AbstractSolver 模板方法
      mesher.py        # AbstractMesher
      postproc.py      # PostProcessor
      validation.py    # 解析参考公式和标准验证执行函数
  mechagent/
    src/mechagent/
      cli/             # Typer CLI
      llm/             # OpenAI 兼容 Chat Completions 调用与健康检查
      knowledge/       # JSONL 混合检索与文档标准化
      orchestrator/    # LangGraph DAG、顺序工作流和 Agent 节点
      ui/              # FastAPI Studio 服务和构建后的静态资源
apps/
  mechagent-studio/    # React/TypeScript Studio 前端源码
config/                # 全局运行配置
scripts/               # 环境检查、标准验证、知识库构建、清理脚本
tests/                 # 单元测试、独立自然语言案例、精度验证测试
```

## 分层架构

```text
用户自然语言
  ↓
SDK / CLI
  ↓
Agent 编排层
  Planner -> Designer -> MeshAgent -> SolverAgent -> PostProcAgent -> AnalystAgent -> ReporterAgent
  ↓
工具与知识层
  mechagent-core / knowledge
  ↓
外部系统层
  CalculiX / Gmsh / OpenAI 兼容 LLM
```

编排层通过能力注册项和工厂函数创建求解器和网格器。core 工厂提供 `register_solver()`、
`unregister_solver()`、`register_mesher()`、`unregister_mesher()`、`create_solver()`、
`create_mesher()`，默认注册 CalculiX 求解器与 `calculix-inp` 网格器。
`SimulationCapability.solver_name` 与 `SimulationCapability.mesher_name` 可绑定能力默认工具；
未声明时使用配置中的 `solver.default` 与 `mesher.default`。配置默认工具和能力默认工具均按工厂注册名称校验；
能力默认工具在注册时规范化为工厂注册名。
`knowledge` 不反向引用 `orchestrator`。Agent 间结构化数据使用 Pydantic v2 模型。

## MechAgent Studio

MechAgent Studio 是面向用户和开发者的本地工程工作台。产品入口由 CLI 提供：

```powershell
python -m mechagent.cli studio --open-browser
```

Studio 后端位于 `packages/mechagent/src/mechagent/ui/server.py`，使用 FastAPI 和 Uvicorn。
API 入口包括：

- `GET /api/health`：返回产品名、配置文件路径和静态资源状态。
- `POST /api/run`：接收自然语言请求和 `use_llm_agents` 布尔开关，调用 `MechAgent.run()`，
  返回 `success`、Markdown `report`、SDK `summary`、结果 `visualizations` 和运行耗时。
- `GET /{full_path:path}`：服务构建后的 React 单页应用；静态资源缺失时返回构建说明页。

Studio 前端位于 `apps/mechagent-studio`，使用 React、TypeScript、Vite、React Flow、
lucide-react 和 react-markdown。Vite 构建输出到
`packages/mechagent/src/mechagent/ui/static`，并通过 `mechagent` 包数据一起发布。
前端构建命令：

```powershell
npm --prefix apps/mechagent-studio ci --no-audit --no-fund
npm --prefix apps/mechagent-studio run build
```

界面组织采用工程工作台结构：

- 左侧：自然语言仿真请求、LLM Agent 开关和工程示例。
- 中央：任务切换、结果 SVG 视口、报告阅读区和 SVG 下载。
- 右侧：Agent DAG、关键指标、阶段产物路径和摘要 JSON。

Agent DAG 由当前运行摘要和错误记录驱动，不在前端伪造工作流状态。结果 SVG 由
`packages/mechagent/src/mechagent/ui/visualization.py` 生成。可视化层优先读取求解输出中的
`.inp` 网格和 `.frd` 位移场；缺少场数据时使用 `ModelParams` 与主结果值生成等效工程视图。
当前视图模板覆盖梁变形线、矩形板位移云图和矩形实体块轴向变形外形。

Studio 不改变 Agent 通信契约。浏览器只消费 `/api/run` 返回的公开摘要和可视化列表；
仿真参数、网格、求解、后处理、校核和报告仍由 Python Agent 链路产生。

## LangGraph 编排

LangGraph 入口位于：

```text
packages/mechagent/src/mechagent/orchestrator/graph.py
```

`config/mechagent.yaml` 默认设置：

```yaml
orchestrator:
  mode: dag
```

SDK 与 CLI 调用 `MechAgent.run()` 时读取该配置；SDK 可通过 `use_llm_agents=True`
启用单次 Agent LLM trace。单次覆盖使用独立配置副本，不改变 `MechAgent.config`
的持久值。`dag` 模式使用 LangGraph `StateGraph`。
`sequential` 模式使用 `SequentialWorkflow`，两种模式共用同一组 Agent。

## Agent 通信机制

MechAgent 采用进程内结构化状态通信。

顺序工作流的数据链路：

```text
TaskItem(intent=SimulationIntent)
  -> DesignAgentOutput(model_params, designer_llm_trace)
  -> MeshAgentOutput(mesh_result, mesh_llm_trace)
  -> SolverRunSummary
  -> PostProcessingSummary
  -> analysis_text
```

LangGraph 工作流使用 `MechAgentState` 作为共享 `TypedDict`。每个节点返回状态增量，
LangGraph 合并后传给下一节点。任务、模型、网格、求解和后处理结果在图状态中保持
Pydantic 对象；SDK 摘要、报告和命令行 JSON 输出在边界处通过 `model_dump(mode="json")`
导出。SDK 摘要的每个任务包含 `case_id`、`capability_id`、`analysis_type`、`intent`、
`model_params`、`mesh_result`、`solver_result`、`post_summary`、任务级 Agent trace 和错误记录；
顶层摘要包含 `reporter_llm_trace`。

| Agent | 输入 | 输出 |
| --- | --- | --- |
| Planner | 用户自然语言 | 携带 `SimulationIntent` 的 `TaskItem` 列表 |
| Designer | `TaskItem` | `DesignAgentOutput`，包含 `ModelParams` 和 `designer_llm_trace` |
| MeshAgent | `ModelParams` | `MeshAgentOutput`，包含 `MeshResult` 和 `mesh_llm_trace` |
| SolverAgent | `TaskItem`、`ModelParams`、`MeshResult` | 按能力评价器生成 `SolverRunSummary` |
| PostProcAgent | `SolverRunSummary` | `PostProcessingSummary` |
| AnalystAgent | `TaskItem`、`PostProcessingSummary` | 工程解读文本 |
| ReporterAgent | `TaskRunRecord` 列表 | Markdown 报告和 `reporter_llm_trace` |

工作流根目录保存顶层 `report.md`。每个 `TaskItem` 使用 `TASK_N` 子目录保存网格、求解输入和求解器输出，
复合请求中的同类模型不会共享文件名或覆盖彼此产物。LangGraph 状态维护 `active_tasks`
和 `failed_records`；单个任务失败时从活跃列表移除并进入错误记录，其余任务继续通过后续节点。
每个阶段消费状态前校验 `active_tasks` 与所需阶段产物列表长度；状态契约不一致时生成对应节点的
`ErrorRecord`，任务进入 `failed_records`，不会被 `zip()` 截断后从报告中静默消失。
Reporter 生成最终记录前再次校验 `model_params_list`、`mesh_results`、`solver_results`、
`post_summaries` 和 `analysis_texts` 的长度一致性；最终状态不完整时生成 `report_failed`
错误记录。Reporter 按 Planner 原始任务顺序合并成功记录和失败记录。

每个 Agent 通过 `AgentLLMAdvisor` 生成 LLM trace。启用 LLM Agent 时，Planner 可调用
LLM 从注册能力列表中识别能力意图，并合并注册能力自身的缺参诊断；Designer 可调用 LLM 生成 `ModelParams` JSON。
结构化输出必须通过能力注册表、Pydantic schema、工程规则、执行契约和工具适配器约束后进入后续链路；
`SimulationIntent.missing_fields` 非空时，Designer 仍会尝试 LLM 结构化补齐；本地 parser 和 LLM
均无法生成可执行参数时返回结构化缺参或歧义错误。能力 parser 已生成验证通过的本地 `ModelParams`
时，后续链路使用本地参数，Designer LLM 输出进入 trace 审计；未通过校验的 LLM 输出只进入 trace 诊断。Planner trace 位于 `TaskItem.planner_llm_trace`；
Designer 和 Mesh trace 位于 `TaskRunRecord` 的显式字段；Solver、PostProc 和 Analyst trace
位于各自输出摘要；Reporter trace 位于工作流顶层摘要。
`scripts/run_llm_smoke.py` 通过 SDK 启用 `use_llm_agents=True`，校验公开摘要中
Planner、Designer、MeshAgent、SolverAgent、PostProcAgent、AnalystAgent 和 ReporterAgent
的 trace 均为实际调用且无错误，并同时校验真实求解成功、参考验收通过和报告路径生成。
顺序工作流中的任务级异常进入 `TaskRunRecord.error`，报告输出“错误诊断”章节。
DAG 工作流使用同一错误记录模型。Planner 阶段失败生成请求级 `TaskRunRecord`；Designer
及后续节点失败保留已有阶段产物并写入对应 Agent 节点名。`ErrorRecord` 包含
`node`、`code`、`message` 和 `missing_fields`，错误码覆盖空请求、标准验证入口误用、
能力范围外请求、复合请求歧义、必要仿真输入缺失、Designer 输入意图缺失以及 Mesh、Solver、PostProc、
Analyst 节点失败。SDK 以 `success=false` 返回失败结果，CLI 输出报告后返回非零退出码。

## 自然语言任务解析

Planner 通过能力注册表识别任务类型，不绑定测试案例。结构静力需求生成：

```text
SimulationIntent(capability_id="structural_static")
TaskItem(case_id="STATIC-STRUCTURAL", capability_id="structural_static")
```

`TaskItem.intent` 保存标准化意图与原始请求，`TaskItem.planner_llm_trace` 保存
Planner 识别记录。`TaskItem.case_id` 和 `TaskItem.title` 来自 `SimulationCapability`
声明。`SimulationCapability` 同时声明 Planner 描述、关键词、示例请求、默认网格器、默认求解器、请求分段器、请求匹配器、
几何识别函数、缺参诊断函数、`ModelParams` 解析器、能力执行契约、LLM 抽取补充契约、模型编号、
模型归一化函数和结果评价器。
扩展能力通过 `register_capability()` 注册，通过 `unregister_capability()` 注销，
Planner 按注册表顺序匹配用户请求；能力声明请求分段器时，Planner 先按该能力的分段器生成候选片段，
再对每个片段调用该能力的匹配器并生成多个 `TaskItem`。同一语句中出现多个几何类型且无法拆分为完整任务时，Designer 阶段返回
`ambiguous_request`，报告保留 `单一几何类型` 诊断字段。本地匹配未命中且启用 LLM Agent 时，Planner 可让 LLM
根据能力描述、关键词和示例请求在已注册能力中选择能力意图，并叠加该能力的缺参诊断。
Planner LLM 响应中的能力编号按注册表编号做大小写、空白和连字符归一化；缺参字段可由字符串数组或
以中文顿号、逗号、分号、换行分隔的字符串表达；置信度可由数字或数字字符串表达，并限制在 0 到 1。
Designer 按 `capability_id` 从注册表获取解析器，先尝试生成本地结构化草案，并在启用 LLM Agent 时
请求 LLM 生成 `ModelParams` JSON。本地结构化草案验证通过时优先进入求解参数，LLM 输出保留为审计记录；
本地 parser 无法生成参数且 LLM 输出可通过校验时，Designer 采用 LLM 结构化参数。两条路径均不可用时，
Designer 依据 `SimulationIntent.missing_fields` 返回缺参诊断。进入求解前的参数均需通过参数范围检查和能力执行契约。
能力声明了 `model_case_ids` 时，`ModelParams.case_id` 必须属于声明集合。
LLM JSON 中显式出现的工程单位由框架确定性归一化：长度转为 mm，力转为 N，
线载荷转为 N/mm，压力和弹性模量转为 MPa，密度转为 tonne/mm^3。无法识别的显式单位
会进入 Designer trace 错误，不进入求解链路。
LLM JSON 中常见工程别名会在进入 Pydantic schema 前归一化：`concentrated`、`concentrated_force`、
`point_force` 和 `tip_force` 转为 `force`，`clamped` 转为 `fixed`，自由度编号
`1..6` 转为 `ux/uy/uz/rx/ry/rz`。
Designer 在 schema 校验前将中文几何类型、载荷类型、边界类型、方向、尺寸字段和材料字段归一化为
枚举与标准字段。板的“向下/向上”按全局 Z 向解释，梁的“向下/向上”按全局 Y 向解释，
实体的“拉伸/受拉/受压/压缩”按全局 X 向解释。
单一载荷或单一边界条件可由 LLM 以对象形式输出；Designer 将 `load`、`loads`、`loadings`、
`load_condition`、`load_conditions` 以及 `bc`、`bcs`、`boundary_conditions`、
`boundary_condition`、`boundaries`、`boundary` 统一归一化为
`ModelParams.loads` 和 `ModelParams.bcs` 数组。LLM 同时输出空复数字段和有效单数字段时，
Designer 以非空对象或非空数组作为解析源。
SolverAgent 按同一 `capability_id` 获取结果评价器，将求解器输出转换为带参考值、误差
和验收状态的 `SolverRunSummary`。
解析范围：

| 几何 | 支持参数 | 载荷 | 边界 | 单元 |
| --- | --- | --- | --- | --- |
| 梁 | 长度、矩形截面、材料目录或 E/ν、横向载荷方向 | 端部集中力、全跨均布线载荷 | 一端固支 | B31 |
| 矩形板 | 长、宽、厚、材料目录或 E/ν | 均布压力 | 四边简支 | S4 |
| 矩形实体块 | 长、宽、高、材料目录或 E/ν、轴向载荷方向 | 端面压力、端面合力 | 一端固定 | C3D8R |

内置材料目录位于 `mechagent.core.materials`，包含钢和铝合金，可通过别名匹配。
材料数据以代码目录作为运行时单点来源。
混凝土、钢筋混凝土、复合材料和碳纤维等材料名称不会按内置钢/铝别名自动匹配；
这类请求需要显式给出 `E` 和 `nu` 作为等效各向同性线弹性参数，或由扩展能力提供专用材料模型。
自然语言解析支持中文尺寸名以及 `length`、`width`、`height`、`thickness`、`section`
等英文尺寸表达。
梁横向载荷和实体端面轴向载荷必须显式给出方向或拉压语义。缺失方向时，Planner/Designer
错误记录保留 `载荷方向` 或 `端面载荷方向` 缺参字段。

网格尺寸由 Designer 基于几何尺度自动给出：

- 梁：`seed_size = max(length / 100, 1.0)`。
- 板：`seed_size = max(min(length, width) / 40, 1.0)`。
- 实体块：`seed_size = max(min(length, width, height) / 2, 1.0)`。

MeshAgent 要求成功网格结果提供 `mesh_file`，并要求 `MeshResult.quality` 中的数值均为有限数值。
`MeshConfig.seed_size`、`MeshConfig.min_quality` 和 `SolverResult.wall_time` 在公共模型层拒绝非有限数值。
运行配置模型同样拒绝非有限 `llm.temperature`、`mesher.min_quality`、`knowledge.bm25_weight`
和 `knowledge.tfidf_weight`。
知识库公开检索函数 `query_index()` 在入口处拒绝非有限 BM25/TF-IDF 融合权重。
配置项 `mesher.min_quality` 只应用于网格结果中的 `min_*` 质量指标；低于阈值的网格结果进入失败状态。
`max_*` 等上界指标不使用最小质量阈值判定。工作流在 MeshAgent 阶段记录 `mesh_failed`
并停止该任务的求解。
默认网格器注册名为 `calculix-inp`。矩形板路径调用 Gmsh Python API 生成四边形壳网格；
梁路径生成 `structured_line` B31 结构化线网格；矩形实体块路径生成 `structured_hex`
C3D8R 结构化六面体网格。三类路径统一输出 CalculiX 可消费的 `.inp` 网格片段，
并在 `MeshResult.metadata` 写入 `source`、`format`、`element_type`、`node_count`
和 `element_count`。

示例请求：

```powershell
python -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
python -m mechagent.cli run "求解长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力的静力响应"
python -m mechagent.cli run "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
python -m mechagent.cli run "solve a steel beam length 1000mm, section 20mm x 40mm, cantilever fixed at one end, downward 1000N tip force static analysis" --json
```

## 核心 Schema

`ModelParams` 是仿真参数单点模型：

- `geometry`：几何类型和尺寸，长度单位为 mm；尺寸必须为有限正数。
- `material`：`E`、`nu`、`rho`，单位为 MPa、无量纲、tonne/mm^3；各向同性材料
  `nu` 的稳定范围为 `(-1, 0.5)`，材料数值必须为有限数值。
- `loads`：载荷类型、大小、作用区域和方向，载荷幅值和方向向量必须为有限数值，且载荷幅值和方向向量必须非零。
- `bcs`：边界类型、区域、自由度和值；约束值必须为有限数值。
- `mesh`：单元类型和网格种子尺寸；`mesh.seed_size` 必须为有限正数。
- `analysis`：分析类型和几何非线性开关。
- `case_id`：模型能力或标准验证案例编号，例如 `STATIC-BEAM`、`STATIC-PLATE`、`STATIC-SOLID`。
- `load_case`：载荷工况编号，例如 `cantilever_tip_force`、`cantilever_uniform_line_load`、
  `simply_supported_pressure`、`fixed_solid_axial_pressure`。
- `mesh_file`：网格阶段生成并传递给求解器的 `.inp` 文件路径。
- `metadata`：输入来源和扩展诊断信息，不作为求解控制字段。

Designer 生成 `ModelParams` 后调用 `mechagent.core.rules.ensure_parameter_ranges()`，
并调用当前 `SimulationCapability.execution_validator` 声明的能力执行契约。
内置结构静力能力绑定 `mechagent.core.rules.ensure_static_execution_contract()`；
该契约约束结构静力执行路径的分析类型、材料类型、几何必需尺寸、几何-单元组合、
边界条件、载荷区域和载荷方向。
参数范围以 `mechagent.core.rules` 作为运行时单点来源；执行契约由能力注册项显式绑定。
网格尺寸范围按参与网格划分的代表长度判断：梁使用长度，板、壳和加筋板使用面内长宽，
实体使用三维尺寸最小值。
启用 LLM Agent 时，Designer 使用当前能力的 `llm_model_contract` 和 `model_case_ids`
生成提示上下文，并在解析 `ModelParams` 后调用当前能力的 `model_normalizer`。
LLM 输出中的 `analysis.nlgeom` 使用显式布尔语义；`linear`、`linear_static`、
`geometrically_linear` 和 `small_deformation` 归一化为 `false`，不会被非空字符串规则误判为非线性。
Designer 在参数范围检查后校验 `model_case_ids`，再执行能力绑定的 `execution_validator`。

求解摘要使用 `success`、`passed` 和 `verification_status` 分离三类状态：

- `success`：求解器进程和结果提取是否成功。
- `passed`：存在参考值和阈值时，工程校核是否通过。
- `verification_status`：`passed`、`failed` 或 `unverified`。缺少参考值或阈值的工况标记为
  `unverified`，报告展示为“未验证”，不等同于工程验收通过。
- 显式 `success=false`、`success=failed` 或等价失败值的求解器结果不能通过工程验收；
  即使主结果与参考值完全一致，也标记为 `failed`。
- `SolverRunSummary.from_mapping()` 对第三方能力插件返回的矛盾状态执行失败优先归一化；
  `success` 为失败时，`passed` 固定为 `false`，`verification_status` 固定为 `failed`。
- `predicted`：主结果计算值。能力评价器未显式提供 `predicted`，但提供了与 `quantity`
  同名的数值字段时，工作流将该字段作为主结果值。
- `predicted`、`reference`、`relative_error` 和 `tolerance` 接受有限数值和有限数值字符串；
  空字符串、布尔值、非数值文本、`nan` 和 `inf` 按缺失值处理。
- `success` 和 `passed` 接受布尔值、0/1 和常见真假字符串；无法识别的文本按默认值处理，
  不把任意非空字符串解释为真。

工作流 `success` 表示从规划到报告的执行链路无错误且求解阶段成功；工程验收结论由每个任务的
`verification_status` 和 `passed` 表达。

求解阶段异常会生成失败状态的 `SolverRunSummary`，保留 `solver`、`model_case_id`、
`task_title`、`mesh_file` 和 `mesh_metadata`；错误原因通过同一任务的 `ErrorRecord`
进入报告和 JSON 摘要。

## 求解器契约

`AbstractSolver.run()` 是模板方法，固定执行：

```text
generate_input -> solve -> extract_results
```

子类实现 `generate_input()`、`solve()`、`extract_results()`，`run()` 由基类统一提供。
这一约束由 `__init_subclass__` 强制执行。

## CalculiX 适配器

`CalculiXAdapter` 支持结构线弹性静力：

- 梁：B31 单元，根部 1 至 6 自由度约束；纯全局 Y 向端部集中力或全跨均布线载荷转换为节点力。
- 矩形板：S4 四节点壳路径；四边 `U3` 简支约束；纯全局 Z 向均布压力按单元面积转换为节点力。
- 矩形实体块：C3D8R 实体单元；根部 `U1/U2/U3` 固定；纯全局 X 向端面压力或端面合力转换为端面节点力。

适配器在 `.inp` 生成前校验 `ModelParams` 的材料类型、几何非线性开关、单元类型、边界条件、载荷区域和载荷方向。
不属于上述验证物理子域的输入以 `SolverError` 结束，不生成与请求不一致的求解文件。
`solver.calculix.num_cpus` 通过 `OMP_NUM_THREADS` 传入 CalculiX 子进程；
`solver.calculix.timeout` 传入子进程超时控制。默认 `num_cpus=1` 用于小型标准验证和
自然语言验收案例的确定性执行；工程任务可在配置中提高该值。标准验证和生产求解共用这两个配置。
网格文件和求解输入文件使用 core 层统一的文件名规范化函数，`ModelParams.case_id`
不会作为路径片段写出到工作目录外。

`.frd` 解析输出：

- `tip_deflection_mm`
- `center_deflection_mm`
- `axial_displacement_mm`
- `max_displacement_mm`
- `max_abs_u1_mm`
- `max_abs_u2_mm`
- `max_abs_u3_mm`
- `max_stress_mpa`

实体轴向验证和生产评价优先使用 `axial_displacement_mm`。该字段按输入几何端面位置提取；
缺失时兼容回退到 `max_abs_u1_mm`。

## 解析参考公式

悬臂梁端部集中力：

```text
δ = P L^3 / (3 E I)
I = b h^3 / 12
```

悬臂梁全跨均布线载荷：

```text
δ = q L^4 / (8 E I)
I = b h^3 / 12
```

四边简支矩形薄板均布压力使用 Navier 双重级数：

```text
D = E h^3 / (12 (1 - ν^2))
w(a/2,b/2) = ΣΣ q_mn / [D π^4 ((m/a)^2 + (n/b)^2)^2]
```

验收计算截断阶数为 151。

矩形实体块端面轴向载荷：

```text
δ = F L / (A E)
A = b h
```

## 标准验证

标准验证由独立命令执行：

```powershell
python scripts/run_benchmarks.py
```

| 编号 | 物理量 | CalculiX | 解析参考 | 相对误差 | 阈值 | 状态 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| TC-01 | `tip_deflection` | 14.896 mm | 14.880952 mm | 0.101120% | 1% | 通过 |
| TC-02 | `center_deflection` | 0.155959 mm | 0.154233 mm | 1.118913% | 2% | 通过 |
| TC-03 | `axial_displacement` | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% | 通过 |
| TC-04 | `tip_deflection` | 5.58805 mm | 5.580357 mm | 0.137856% | 2% | 通过 |
| TC-05 | `axial_displacement` | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% | 通过 |

## 独立自然语言测试案例

自然语言测试案例位于 `scripts/natural_language_cases.py`，不进入生产 Planner。
真实执行命令：

```powershell
python scripts/run_natural_language_cases.py
```

脚本读取 SDK 摘要中的实际 `model_params` 和 `solver_result`，同时校验模型能力编号、几何类型、
载荷类型和求解误差。

| 编号 | 内容 | 期望能力 |
| --- | --- | --- |
| SC-01 | 钢悬臂梁端部集中力 | `STATIC-BEAM` + `force` |
| SC-02 | 钢悬臂梁均布线载荷 | `STATIC-BEAM` + `line_load` |
| SC-03 | 铝合金悬臂梁端部集中力 | `STATIC-BEAM` + `force` |
| SC-04 | 显式 E/ν 悬臂梁端部集中力 | `STATIC-BEAM` + `force` |
| SC-05 | 铝矩形板四边简支均布压力 | `STATIC-PLATE` + `pressure` |
| SC-06 | 钢矩形板 kPa 均布压力 | `STATIC-PLATE` + `pressure` |
| SC-07 | 钢矩形板 Pa 均布压力和 m 单位尺寸 | `STATIC-PLATE` + `pressure` |
| SC-08 | 钢矩形实体端面压力轴向拉伸 | `STATIC-SOLID` + `pressure` |
| SC-09 | 显式 E/ν 矩形实体端面合力轴向拉伸 | `STATIC-SOLID` + `force` |
| SC-10 | 显式 `N/mm²` 弹性模量和均布压力矩形板 | `STATIC-PLATE` + `pressure` |
| SC-11 | 英文钢悬臂梁端部集中力 | `STATIC-BEAM` + `force` |
| SC-12 | 英文钢矩形板四边简支均布压力 | `STATIC-PLATE` + `pressure` |
| SC-13 | 英文钢矩形实体端面合力轴向拉伸 | `STATIC-SOLID` + `force` |
| SC-14 | 英文钢悬臂梁均布线载荷与 m/cm 单位 | `STATIC-BEAM` + `line_load` |
| SC-15 | 显式 GPa/kPa 矩形板四边简支均布压力 | `STATIC-PLATE` + `pressure` |
| SC-16 | 显式 `N/mm²` 矩形实体端面合力轴向拉伸 | `STATIC-SOLID` + `force` |
| SC-17 | 不显式写“静力分析”的钢悬臂梁最大挠度报告 | `STATIC-BEAM` + `force` |
| SC-18 | `×` 截面分隔符和大写 `KN/m` 的钢悬臂梁均布线载荷 | `STATIC-BEAM` + `line_load` |
| SC-19 | 尺寸前置 `×` 写法和大写 `KPA` 的铝矩形板均布压力 | `STATIC-PLATE` + `pressure` |
| SC-20 | 尺寸前置 `×` 写法的钢长方体端面合力轴向拉伸 | `STATIC-SOLID` + `force` |

## LLM 与知识库

LLM：

- 文本生成：`httpx` 直连 OpenAI 兼容 Chat Completions JSON 接口。
- 连接健康检查：执行最小 Chat Completions 调用。
- JSON 输出：LLM 后端优先使用 Chat Completions JSON mode，请求 4096 token 输出预算；
  当后端不支持 `response_format` 时重试普通 Chat Completions。
- LLM HTTP 调用只处理 JSON 字典响应，不引入 provider 对象序列化副作用。
- 本地前置校验：空 prompt 或缺少 `base_url`、`api_key`、`model` 时不进入 provider 调用。
- 默认配置：`orchestrator.use_llm_agents: false`，生产求解使用确定性 schema 与工具链闭环。
  远端 LLM 结构化抽取与审阅通过 CLI `--llm-agents`、SDK `use_llm_agents=True`
  或配置项显式开启。
- Agent trace：Planner、Designer、MeshAgent、SolverAgent、PostProcAgent、AnalystAgent、
  ReporterAgent 均可调用 LLM。Planner 输出能力意图，Designer 输出 `ModelParams` JSON；
  其余 Agent 输出工程审阅与报告辅助信息。
- 缺参补齐与门禁：Planner 已记录必要字段缺失时，Designer 仍尝试 LLM 结构化补齐；
  本地 parser 和 LLM 均无法生成可执行参数时返回缺参诊断。
- 本地参数优先：能力 parser 生成验证通过的本地 `ModelParams` 时，Designer 不用 LLM 输出覆盖用户已解析参数。
- 模型编号契约：能力声明 `model_case_ids` 时，Designer 拒绝声明范围外的 `ModelParams.case_id`。
- SDK/CLI JSON 摘要输出 trace 元数据、错误状态和 prompt/response 字符数，不输出原始
  prompt 或 response；Markdown 报告展示通信摘要。
- 插件扩展字段和后处理标量中的嵌套 LLM trace 递归转换为公开摘要；`Path`
  类型转换为字符串，保证公开 JSON 摘要可序列化。
- `SolverRunSummary.to_mapping()` 和 `PostProcessingSummary.to_mapping()` 导出同一类公开映射，
  供后处理、插件和脚本复用。
- 后续 Agent 的 advisory payload 对已有 LLM trace 执行同样的公开摘要转换，保留
  `agent`、`used`、`error` 和字符数，不递归传递上游 prompt/response；部分 trace
  映射使用显式布尔解析，避免 `"false"` 被解释为真。
- LLM HTTP 后端、Provider 和 Agent 异常消息进入连接检查、trace 与 `ErrorRecord` 前会脱敏
  `api_key`、环境变量 `API_KEY`、Bearer token 和常见 provider token。
- SDK/CLI 公开摘要、Markdown 报告通信摘要和后续 advisory payload 中的 trace `error`
  字段使用同一脱敏规则。
- 私密字段与本机外部程序路径：`.env` 注入，不进入 Git。

知识库：

- 默认输入：`knowledge/sources` 下的公开 Markdown 种子文档。
- 可选输入：Markdown、TXT、JSON，可通过 `knowledge.raw_dir` 指向本地目录。
- 索引：本地 JSONL。
- 检索：中英文 token/ngram 切分、BM25、TF-IDF 余弦相似度、归一化融合。
- 脚本与 CLI：`scripts/build_knowledge.py`、`scripts/index_knowledge.py` 和
  `knowledge build` 均按配置执行文档标准化和 JSONL 索引构建。
- 空源门禁：知识源目录不存在、无可标准化文档或无可索引文本块时直接失败，
  不生成空索引作为有效知识库。
- 索引校验：检索时校验 JSONL 行格式、对象类型、空索引状态以及 `doc_id/source/text`
  必需字段和非空字段值。

## 质量结果

以下命令记录本机维护者完整验证所用解释器。公开用户和 CI 在激活独立 Python 环境后使用等价
`python` 命令执行同一组门禁。

```powershell
python scripts/check_env.py
python scripts/check_env.py --help
npm --prefix apps/mechagent-studio ci --no-audit --no-fund
npm --prefix apps/mechagent-studio run build
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

测试覆盖范围按职责分组记录，避免把质量证据分散在入口文档中：

- 发布与环境：公开 API、Studio 服务、Studio 可视化、PEP 561 类型标记、wheel 安装验证脚本、
  发布元数据、配置局部环境展开、环境诊断键、便携 CI 门禁、清理策略边界。
- 能力与编排：能力注册、能力级工具选择、能力默认工具注册契约、能力默认工具规范化、
  能力模型编号契约、能力级先分段后匹配、复合请求拆分、多任务工作目录、
  复合请求部分失败保留成功任务、歧义请求错误归因、LangGraph 状态契约校验。
- LLM 结构化链路：SDK 单次 LLM trace 开关、LLM HTTP 后端契约、LLM 端到端 smoke 脚本、
  Planner LLM 字符串意图归一化、LLM 工程别名归一化、LLM 中文结构化字段归一化、
  LLM 单对象载荷边界归一化、LLM 空数组与单对象优先级归一化、LLM 几何非线性布尔归一化、
  LLM 数值漂移防覆盖、LLM 缺参补齐与门禁。
- 脱敏与公开摘要：LLM provider 错误脱敏、Agent trace 脱敏、trace error 脱敏、
  报告通信摘要脱敏、错误消息脱敏、扩展字段递归脱敏、映射导出脱敏、advisory payload 脱敏。
- 求解与插件：插件主结果字段推断、插件数值字符串解析、插件布尔字符串解析、求解失败摘要、
  求解失败优先验收状态、摘要失败优先归一化、网格质量失败归因、MeshAgent 输出契约、
  求解适配器、后处理、工程解读、真实 CalculiX 精度验证。
- 知识库与材料规则：公开知识源、空知识源门禁、空知识索引门禁、知识库检索、
  材料目录、复合材料名称防误配、工程规则、结构静力执行契约、显式载荷方向缺参诊断。
- 自然语言与案例：自然语言解析、二十个独立静力输入案例、工程压力单位转换、
  工程尺寸符号解析、LLM 响应解析、CLI 结构化输出。

结果：

- `check_env.py`：通过；默认检查 Python、依赖、本机求解工具链和 `CALCULIX_CCX`
  工具路径键，`--require-llm` 对远端 LLM 凭证执行必需项检查。
- `mechagent.cli config validate --llm`：通过；OpenAI 兼容 Chat Completions 连接正常。
- `ruff format`：通过。
- `ruff check`：通过。
- `mypy --strict`：通过。
- `pytest`：344 passed。
- Studio 前端构建：Vite 构建通过；React Flow 与 Markdown 渲染依赖拆分为独立 chunk，
  主入口 gzip 约 75 KB。
- `scripts/run_llm_smoke.py`：通过；Planner、Designer、MeshAgent、
  SolverAgent、PostProcAgent、AnalystAgent 和 ReporterAgent 均记录 `used: true`，
  示例悬臂梁任务由 CalculiX 求解，端点位移 14.896 mm，相对参考误差 0.101120%。
- 发布包类型标记：`mechagent/py.typed` 与 `mechagent/core/py.typed` 已纳入包数据。
- wheel 安装验证：构建后的 `mechagent-core` 与 `mechagent` wheel 可安装到隔离目录，
  并验证导入入口、`Requires-Dist` 依赖元数据、CLI entry point、类型标记和许可证文件。
- TC-01 至 TC-05 真实 CalculiX 验证：通过。
- 二十个独立自然语言案例真实求解：通过。
- 知识库标准化和 JSONL 索引脚本：通过。
- LLM trace：配置启用且连接有效时由各 Agent 写入报告通信摘要；Planner 与 Designer 的
  结构化输出经过校验后参与自然语言工作流。
- LLM 远端连接：由本地 `.env` 私密凭证和远端授权状态决定，属于本地可选检查。
- 公开 PR 工作流使用 `scripts/check_env.py --profile portable` 和
  `pytest -m "not real_solver"`；本地质量门禁执行完整真实 CalculiX 验证和自然语言求解案例。
- `pip check`：无破损依赖。
- `mechagent-core` 与 `mechagent` wheel/sdist 构建：通过。
- MkDocs 严格构建：通过。

## 清理策略

项目可再生成产物由 `.gitignore` 与 `scripts/clean_artifacts.py` 覆盖：
清理脚本以脚本所在仓库根目录作为固定边界，删除前校验目标路径位于仓库目录内。

- `__pycache__/`
- `.pytest_cache/`
- `.mypy_cache/`
- `.ruff_cache/`
- `*.egg-info/`
- `build/`
- `dist/`
- `site/`
- `apps/mechagent-studio/node_modules/`
- `*.frd`
- `*.dat`
- `*.sta`
- `*.lck`
- `*.msg`
- `mechagent_output/`
- `knowledge/external/`
- `knowledge/index.jsonl`

`knowledge/sources/` 是公开知识源目录。`knowledge/raw/` 是本地私有输入目录，仓库忽略该目录；
清理脚本只在该目录为空时移除它。
`.env` 是本机私密配置文件，仓库忽略该文件，清理脚本不删除该文件。
CalculiX 安装目录保留在 `D:/Calculix/CalculiX-2.23.0-win-x64/`，仓库公开配置通过
`CALCULIX_CCX` 绑定本机可执行文件。

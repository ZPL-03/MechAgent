# 架构与数据契约

本文描述 MechAgent 的项目定位、分层架构、包结构、核心 Schema 与求解器契约。Agent 编排与通信见 [编排与 Agent 通信](orchestration.md)，能力与解析见 [能力与自然语言解析](capabilities.md)，求解与网格见 [求解器、网格与后处理](solver_mesh.md)。

## 依赖与扩展边界

`mechagent` 依赖 `mechagent-core`；core 不依赖编排。`knowledge` 保持独立知识层职责，不反向引用 `orchestrator`。平台围绕能力注册、工具注册和结构化状态组织任务；单一后端的专用格式由适配器封装。产品职责见[产品蓝图](product_blueprint.md)，模型与输入范围见[能力说明](capabilities.md)。

## 包结构

```text
packages/
  mechagent-core/
    src/mechagent/core/
      models/          # Pydantic v2 仿真参数 schema
      adapters/        # CalculiX、Gmsh 网格与 Gmsh CAD 适配器
      cad.py           # AbstractCADKernel 与 CAD 几何摘要/候选模型
      executor.py      # AbstractJobExecutor 与本地作业执行器
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
      runtime/         # SQLite 队列、调度、独立 worker 与进程隔离
      evidence.py      # 运行清单、原子写入与文件完整性验证
      ui/              # FastAPI Studio 服务和构建后的静态资源
apps/
  mechagent-studio/    # React/TypeScript Studio 前端源码
config/                # 全局运行配置
scripts/               # 环境检查、标准验证、知识库构建、清理脚本
tests/                 # 单元测试、独立自然语言案例、精度验证测试
```

前端目录结构与模块边界见 [前端架构](frontend_architecture.md)。

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

编排层通过能力注册项和工厂函数创建求解器和网格器。core 工厂提供 `register_solver()`、`unregister_solver()`、`register_mesher()`、`unregister_mesher()`、`create_solver()`、`create_mesher()`，默认注册 CalculiX 求解器与 `calculix-inp` 网格器。`SimulationCapability.solver_name` 与 `SimulationCapability.mesher_name` 可绑定能力默认工具；未声明时使用配置中的 `solver.default` 与 `mesher.default`。配置默认工具和能力默认工具均按工厂注册名称校验；能力默认工具在注册时规范化为工厂注册名。`knowledge` 不反向引用 `orchestrator`。Agent 间结构化数据使用 Pydantic v2 模型。

后处理使用 `PostProcessor`，材料使用内置目录；二者没有独立工厂注册 API。求解器、网格器、CAD 内核和执行器采用注册/工厂/配置模式。除求解器（`AbstractSolver`）与网格器（`AbstractMesher`）外，core 提供 CAD 内核抽象 `AbstractCADKernel`（`load -> repair -> summarize` 模板，产出 `CADGeometrySummary` 与 `CADImportResult`）和作业执行器抽象 `AbstractJobExecutor`（`submit / status / result / cancel` 契约与 `run` 模板，内置同步 `LocalCommandExecutor` 默认后端）。对应工厂为 `register_cad_kernel()`/`create_cad_kernel()` 与 `register_executor()`/`create_executor()`，配置项为 `cad.default` 与 `executor.default`（默认 `local`）。

CAD 内核内置基于 gmsh OpenCASCADE 后端的 `GmshCADKernel`（注册名 `gmsh-occ`），导入 STEP/IGES/BREP 形体并归纳包围盒、体积、表面积与实体/面/边数量；`geometry_candidate_from_summary()` 把几何摘要映射为 `GeometryCandidate`（按薄度与细长比推断几何类型、由包围盒六面派生边界/载荷区域候选、记录材料/载荷/边界缺参诊断）。`GeometryAgent` 串联 CAD 内核与该映射，输出 `GeometryAnalysis`，并可通过自然语言补全材料、载荷和边界生成结构静力 `ModelParams`。该基础链路适用于可由包围盒和薄度/细长比可靠归类的形体；通用几何修复、特征识别、装配体、自动区域语义映射和远程/HPC/容器执行器属于后续物理域与平台化能力，进入发布边界前满足成熟度门禁，详见 [长周期开发计划书](development_plan.md)。

## 核心 Schema

`ModelParams` 是仿真参数单点模型：

- `geometry`：几何类型和尺寸，长度单位为 mm；尺寸必须为有限正数。
- `material`：`E`、`nu`、`rho`，单位为 MPa、无量纲、tonne/mm^3；各向同性材料 `nu` 的稳定范围为 `(-1, 0.5)`，材料数值必须为有限数值。
- `loads`：载荷类型、大小、作用区域和方向，载荷幅值和方向向量必须为有限数值，且必须非零。
- `bcs`：边界类型、区域、自由度和值；约束值必须为有限数值。
- `mesh`：单元类型和网格种子尺寸；`mesh.seed_size` 必须为有限正数。
- `analysis`：分析类型和几何非线性开关。
- `case_id`：模型能力或标准验证案例编号，例如 `STATIC-BEAM`、`STATIC-PLATE`、`STATIC-PERFORATED-PLATE`、`STATIC-SOLID`。
- `load_case`：载荷工况编号，例如 `cantilever_tip_force`、`cantilever_uniform_line_load`、`simply_supported_pressure`、`perforated_plate_pressure`、`fixed_solid_axial_pressure`。
- `mesh_file`：网格阶段生成并传递给求解器的 `.inp` 文件路径。
- `metadata`：输入来源和扩展诊断信息，不作为求解控制字段。

跨 API、编排和工具边界使用 `SimulationCase` 作为版本化封装。它复用同一个
`ModelParams` 实例，不复制几何、材料、载荷或边界字段，并额外包含：

- `schema_version`：当前案例契约版本为 `1`；未知未来版本拒绝校验。
- `units`：显式的输入单位系统；当前支持长度 `mm`/`cm`/`m`/`in`、力 `N`/`kN`/`lbf`、应力 `MPa`/`kPa`/`Pa`/`GPa`/`psi`、密度 `tonne/mm^3`/`kg/m^3`/`g/cm^3` 和温度 `C`。`SimulationCase.to_model_params()` 将已声明的几何、材料、载荷、边界位移、网格和坐标转换为 N-mm-MPa-tonne/mm³ 基线；未声明的量不会按字段名推断单位。
- `coordinate_system`：右手坐标系名称、原点和轴名称。
- `regions`：载荷和边界区域的命名、区域类型、稳定标识及来源。
- `request`：原始用户请求、解析器名称和解析版本。
- `provenance`：几何、材料、载荷、边界、网格和分析设置的来源与置信度。
- `solver_control`：可选迭代、容差和时间步字段；具体后端未声明支持时不得自行解释。

`ModelParams.to_simulation_case()` 和 `SimulationCase.to_model_params()` 是兼容转换
入口。当前结构静力工作流在 Designer 输出后生成案例摘要，求解器仍接收兼容的
`ModelParams`；这保证旧工具接口稳定，同时让 API、报告和证据可以逐步迁移到统一案例契约。

Designer 生成 `ModelParams` 后调用 `mechagent.core.rules.ensure_parameter_ranges()`，并调用当前 `SimulationCapability.execution_validator` 声明的能力执行契约。内置结构静力能力绑定 `mechagent.core.rules.ensure_static_execution_contract()`；该契约约束结构静力执行路径的分析类型、材料类型、几何必需尺寸、几何-单元组合、边界条件、载荷区域和载荷方向。参数范围以 `mechagent.core.rules` 作为运行时单点来源；执行契约由能力注册项显式绑定。网格尺寸范围按参与网格划分的代表长度判断：梁使用长度，板、壳和加筋板使用面内长宽，实体使用三维尺寸最小值。

### 求解摘要状态

求解摘要使用 `success`、`passed` 和 `verification_status` 分离三类状态：

- `success`：求解器进程和结果提取是否成功。
- `passed`：存在参考值和阈值时，工程校核是否通过。
- `verification_status`：`passed`、`failed` 或 `unverified`。缺少参考值或阈值的工况标记为 `unverified`，报告展示为「未验证」，不等同于工程验收通过。
- 显式 `success=false`、`success=failed` 或等价失败值的求解器结果不能通过工程验收；即使主结果与参考值完全一致，也标记为 `failed`。
- `SolverRunSummary.from_mapping()` 对第三方能力插件返回的矛盾状态执行失败优先归一化；`success` 为失败时，`passed` 固定为 `false`，`verification_status` 固定为 `failed`。
- `predicted`：主结果计算值。能力评价器未显式提供 `predicted`，但提供了与 `quantity` 同名的数值字段时，工作流将该字段作为主结果值。
- `predicted`、`reference`、`relative_error` 和 `tolerance` 接受有限数值和有限数值字符串；空字符串、布尔值、非数值文本、`nan` 和 `inf` 按缺失值处理。
- `success` 和 `passed` 接受布尔值、0/1 和常见真假字符串；无法识别的文本按默认值处理，不把任意非空字符串解释为真。

工作流 `success` 表示从规划到报告的执行链路无错误且求解阶段成功；工程验收结论由每个任务的 `verification_status` 和 `passed` 表达。求解阶段异常会生成失败状态的 `SolverRunSummary`，保留 `solver`、`model_case_id`、`task_title`、`mesh_file` 和 `mesh_metadata`；错误原因通过同一任务的 `ErrorRecord` 进入报告和 JSON 摘要。

## 求解器契约

`AbstractSolver.run()` 是模板方法，固定执行：

```text
generate_input -> solve -> extract_results
```

子类实现 `generate_input()`、`solve()`、`extract_results()`，`run()` 由基类统一提供。这一约束由 `__init_subclass__` 强制执行。CalculiX 适配器实现见 [求解器、网格与后处理](solver_mesh.md)。

## 持久执行与证据

Studio 的运行层位于应用包 `runtime/`，不替代 core 的工具执行器契约。HTTP 提交、同步兼容入口和显式重试共用 SQLite 队列。`BEGIN IMMEDIATE` 事务串行化领取、取消和终态提交，并在数据库层限制活动 worker 数量；FastAPI 生命周期仅管理调度线程，每个任务由独立 Python 进程调用 SDK。SDK 和 CLI 直接运行不经过 Studio 队列。

状态依次为 `queued → starting → running → succeeded/failed`，取消经过 `cancelling → cancelled`；未登记或失联的执行进程为 `interrupted`。取消先于结果提交时，worker 不得覆盖取消状态。进程身份使用 PID 与创建时间核验；Windows worker 先加入带 `KILL_ON_JOB_CLOSE` 的 Job Object，再登记身份和执行工作，隔离失败不开始求解。Windows 下 worker 异常退出会终止其后代。POSIX 使用独立进程组处理主动取消；worker 被外部单独强杀后的孤儿回收尚无平台验证，不作完整进程树恢复承诺。

`studio` 配置定义数据库路径、并发、排队、启动登记、心跳和总执行时限。多个服务共享同一个数据库时须使用相同调度配置；SQLite 文件限本机文件系统，不能据此推导网络文件系统或多机调度支持。数据库 schema 版本为 2。v1 队列结构可在事务内迁移到 v2；v2 使用 `schema_migrations` 记录已应用版本，并为历史作业补充配置哈希字段。缺少原配置文件的历史作业保留未验证哈希，worker 会拒绝执行并要求显式重新提交。未知未来版本拒绝打开。队列和结果没有自动删除策略；归档由维护者管理。

每个 Studio 作业使用数据库同目录下的 `jobs/<job_id>/`，其中 `runs/` 保存 SDK 运行、`result.json` 保存公开响应、`manifest.json` 保存清单。原始 `worker.log` 仅作本地故障诊断，不通过 API 公开，也不纳入清单；日志目录仍应按工程数据管理。队列保存请求、配置路径及其源文件哈希，不保存展开后的密钥。worker 执行前校验配置文件哈希，配置变化导致显式失败；`.env` 与进程环境在 worker 启动时解析，环境变更不在源文件哈希覆盖范围内。

SDK 的运行清单包含 schema、Python/操作系统、包版本、脱敏有效配置、请求、公开摘要、产物相对路径、大小与 SHA-256。工具版本无法确定时明确为 `unknown`，不把包版本当作求解器二进制版本。异常、取消和中断保存已有产物；哈希不跟随目录外的符号链接。清单按临时文件、刷盘和原子替换写入，校验可发现清单列出的文件缺失与内容变化；该机制不是数字签名，不提供作者身份或物理正确性证明。数值复现依赖相同模型、工具和验收容差，不承诺文件逐字节一致。

数据库和 `jobs/` 必须一起保留。冷备份要求所有任务终态并停止服务，完整复制数据库目录及其运行文件；不得在活动事务期间仅复制主 `.sqlite3` 文件而忽略 WAL。服务恢复提供状态与结果查询，不提供求解器内部断点续算或无声重算。

# MechAgent 技术报告

## 产品范围

MechAgent 是开源 CAE/FEA 多智能体编排框架。它把自然语言工程请求转换为结构化仿真案例，经过能力门禁、网格、求解、结果提取、工程评价和报告输出，保存可复核的运行证据。LLM 只负责意图识别、结构化候选和解释；数值结果来自已注册的网格器、求解器和后处理器。

发布基线聚焦结构线弹性静力，模型族包括悬臂梁、四边简支矩形薄板、圆孔/多孔/长圆槽孔薄板和矩形实体块。内置工具链为 Gmsh、CalculiX 和本地作业执行器。Abaqus 具备独立本机几何、网格、静力和 ODB 检查脚本，尚未注册为平台生产后端。

## 分层架构

`mechagent-core` 提供 Pydantic 数据模型、材料目录、CAD 内核、网格器、求解器、后处理器、执行器、验证基准和工具工厂。`mechagent` 提供 SDK、CLI、Studio 服务、Planner/Designer/Mesh/Solver/PostProc/Analyst/Reporter 编排链路、LLM 接入和知识层。React/TypeScript Studio 位于 `apps/mechagent-studio`，构建产物随 `mechagent` 包发布。

求解器、网格器、CAD 内核、后处理器和执行器通过注册名、工厂函数、适配器契约和能力声明接入。跨层结构化数据使用 Pydantic v2 模型；`SimulationCase` schema v1 作为 API、编排、工具和证据边界的版本化封装，兼容转换保留旧 `ModelParams` 调用方。

## 执行契约

`SimulationCase` 明确声明单位、右手坐标系、载荷/边界区域、请求来源、字段来源和求解控制。`to_model_params()` 只执行案例声明的单位换算，不根据字段名称或自然语言推断单位。

进入网格和求解前，`SimulationCase.execution_readiness()` 检查几何、材料、载荷、边界、网格、分析六类来源以及全部载荷/边界区域来源的置信度。默认门槛为 `0.80`。缺失或低于门槛的旧兼容案例可以读取和迁移，但 `ensure_execution_ready()` 会阻断执行并生成 `execution_not_ready` 错误。参数范围、能力执行契约和工具注册检查在同一执行链路中生效。

执行状态与工程验收分开表达：`success` 表示进程和结果提取完成，`verification_status` 表示参考验收状态，`passed` 表示在存在参考值和阈值时通过工程校核。缺少参考值的结果标记为 `unverified`，不等同于工程验收通过。

## 接口与运行层

Studio 稳定 HTTP 入口为 `/api/v1`，旧 `/api` 路径仅用于兼容已有本地集成并带弃用响应头。Studio 使用 SQLite 作业记录、独立 worker、幂等提交、取消、重启查询、并发限制和运行清单校验；服务仍是本机单用户队列，不提供认证、项目隔离、RBAC 或集群调度。

SDK、CLI 和 Studio 使用同一编排模型及公开摘要。公开响应保留任务、状态、错误、结果、产物和审计元数据，不输出原始 prompt、LLM response 或密钥。运行目录中的输入、网格、求解输出、报告和 manifest 按文件校验和保存，文件完整性与工程参考验收分别判断。

## 验证证据

维护基线包括 5 个 CalculiX 标准验证算例、28 个自然语言案例和 15 项 LLM smoke 检查。Python 测试收集 522 项，便携测试和 18 项真实 CalculiX 回归均通过；Ruff、mypy、MkDocs strict、两个包的 wheel/sdist 构建、隔离 wheel 安装烟测和 `pip check` 通过。前端测试、TypeScript/Vite 构建、生产依赖审计、SBOM、发布清单、构建 provenance 和 Python 运行时依赖审计由质量门禁统一检查。

验证命令、算例误差、环境边界、依赖审计和清理策略见[验证与质量门禁](validation.md)。标准算例和自然语言案例的具体范围见[能力与自然语言解析](capabilities.md)及[求解器、网格与后处理](solver_mesh.md)。

## 发布条件

公开发布前仍需完成身份认证、项目隔离、RBAC、审计主体、资源配额、对象存储、备份恢复、灾难演练、可观测性、许可证人工审计、签名 provenance、签名发布、CAD 拓扑和区域语义映射、网格质量与收敛闭环、Abaqus 注册适配器及同输入双后端对比。非线性、接触、屈曲、动力学、多物理场和优化能力必须分别完成输入契约、真实工具产物、独立验证证据和失败路径后才能进入公开能力目录。

发布门禁要求代码、配置、API、CLI、Studio、包元数据和文档一致；安装后导入、数据库迁移、真实求解、证据校验、安全检查和回滚依据齐全；发布范围内不存在未解释的数值差异、未验证能力或高严重度安全问题。长周期依赖关系和阶段完成条件以[长周期开发计划书](development_plan.md)为准。

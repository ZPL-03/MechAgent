# Changelog

## 0.1.0

- Monorepo 工程结构：`packages/mechagent-core` 与 `packages/mechagent`。
- `mechagent-core`：Pydantic v2 数据模型、`AbstractSolver`、`AbstractMesher`、
  `PostProcessor`、CalculiX 适配器、Gmsh 网格器和标准验证算例。
- `mechagent`：SDK、Typer CLI、配置模型、LLM 后端、知识库索引和 Agent 编排层。
- 多 Agent 编排：顺序工作流与 LangGraph DAG，节点为 Planner、Designer、
  MeshAgent、SolverAgent、PostProcAgent、AnalystAgent、ReporterAgent。
- 能力注册表：Planner 生成标准化 `SimulationIntent`，`TaskItem` 携带结构化意图，
  Designer 按 `capability_id` 调用解析器，SolverAgent 按 `capability_id` 调用结果评价器。
- 工具注册工厂：core 层提供求解器和网格器注册/注销 API，配置默认工具按注册表校验。
- Agent LLM trace：七个 Agent 均可调用 LLM 生成审阅意见，报告输出通信摘要。
- SDK 摘要：每个任务导出 `intent`、`model_params`、`mesh_result`、`solver_result`、
  `post_summary`、Agent trace 和错误记录。
- 自然语言案例：二十个独立结构静力请求真实执行并通过验收。
- 材料目录：`mechagent-core` 提供钢和铝合金内置材料别名匹配。
- 标准验证：TC-01 至 TC-05 均使用真实 CalculiX 求解并通过解析参考验收。
- 本机配置：公开配置使用 `${CALCULIX_CCX:-ccx}`，本机 `.env` 将 `CALCULIX_CCX`
  指向 `D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe`，无需系统 PATH。
- LLM：`httpx` 直连 OpenAI 兼容 Chat Completions 接口，`.env` 注入 URL、API_KEY、MODEL_NAME。
- 环境检查：`check_env.py` 校验 Python 执行器、配置解析后的 CalculiX 路径、依赖包和
  `.env` 三个 LLM 键。
- 工程质量：`ruff check`、`mypy --strict`、`pytest`、真实标准验证、自然语言案例、
  知识库脚本、`pip check`、包构建和文档构建全部通过。

# Changelog

## 0.1.0

- Monorepo 工程结构：`packages/mechagent-core` 与 `packages/mechagent`。
- `mechagent-core`：Pydantic v2 数据模型、`AbstractSolver`、`AbstractMesher`、
  `PostProcessor`、CalculiX 适配器、Gmsh 网格器和标准验证算例。
- `mechagent`：SDK、Typer CLI、配置模型、LLM 后端、知识库索引和 Agent 编排层。
- MechAgent Studio：FastAPI 本地服务、React/TypeScript/Vite 前端工作台、Agent DAG、
  Three.js 几何/网格/结果视口、SVG 兼容输出、运行前预检、指标、阶段产物、摘要 JSON 和 Markdown 报告。
- Studio 检查区：验收状态、求解流程、Agent 链路、阶段产物和摘要 JSON 使用公开摘要驱动，宽屏、窄屏和结果态保持响应式布局。
- 3D 可视化坐标与场图：梁保持横向弯曲视角；矩形板和矩形实体块将求解 `Z` 轴映射为 Three.js 竖向轴；结果模式提供单元面、网格边、节点标量颜色、位移/应力场量切换、快捷视角和图例。
- 开孔薄板：支持单孔、偏心孔和多孔参数化薄板，Gmsh OCC 布尔建模，外边界简支、孔边自由、均布压力、真实求解和结果场展示。
- 网格质量：Gmsh 路径提取 `min_sicn` 与 `mean_sicn`，MeshAgent 按 `mesher.min_quality` 对 `min_*` 指标执行质量门禁。
- 多 Agent 编排：顺序工作流与 LangGraph DAG，节点为 Planner、Designer、
  MeshAgent、SolverAgent、PostProcAgent、AnalystAgent、ReporterAgent。
- 能力注册表：Planner 生成标准化 `SimulationIntent`，`TaskItem` 携带结构化意图，
  Designer 按 `capability_id` 调用解析器，SolverAgent 按 `capability_id` 调用结果评价器。
- 工具注册工厂：core 层提供求解器和网格器注册/注销 API，配置默认工具按注册表校验。
- Agent LLM trace：七个 Agent 均可调用 LLM，ReporterAgent 基于 FEM 求解摘要生成工程解释，报告输出通信摘要。
- SDK 摘要：每个任务导出 `intent`、`model_params`、`mesh_result`、`solver_result`、
  `post_summary`、Agent trace 和错误记录。
- 运行前预检：`MechAgent.inspect()`、`python -m mechagent.cli inspect` 和 `/api/inspect`
  提供任务识别、缺项诊断、能力编号、几何类型和可执行状态。
- 自然语言案例：二十六个独立结构静力请求真实执行并通过验收。
- 材料目录：`mechagent-core` 提供钢和铝合金内置材料别名匹配。
- 标准验证：TC-01 至 TC-05 均使用真实 CalculiX 求解并通过解析参考验收。
- 本机配置：公开配置使用 `${CALCULIX_CCX:-ccx}`，本机 `.env` 将 `CALCULIX_CCX`
  指向 `D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe`，无需系统 PATH。
- LLM：`httpx` 直连 OpenAI 兼容 Chat Completions 接口，`.env` 注入 URL、API_KEY、MODEL_NAME。
- Studio 前端构建：`apps/mechagent-studio` 使用 Node.js 构建，静态资源随 `mechagent` 包发布。
- 环境检查：`check_env.py` 校验 Python 执行器、配置解析后的 CalculiX 路径、依赖包和
  `.env` 三个 LLM 键。
- 工程质量：`ruff check`、`mypy --strict`、`pytest`、真实标准验证、自然语言案例、
  知识库脚本、`pip check`、包构建和文档构建全部通过。

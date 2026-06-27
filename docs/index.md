# MechAgent 文档

MechAgent 提供自然语言到开源 CAE/FEA 工作流的多智能体编排闭环。文档覆盖产品定位、Studio 使用、设计系统、前端架构、系统架构、编排、能力、求解、验证与本地环境。

## 文档导航

### 产品与使用

- [产品蓝图](product_blueprint.md)：产品定位、能力模型、3D 可视化目标、进度状态、路线图。
- [长周期开发计划书](development_plan.md)：面向通用 CAE 智能体平台的愿景、架构演进、物理域路线图（P1–P8）、工具生态、验证体系、里程碑与治理。
- [Studio 使用指南](studio_ui.md)：启动、界面布局、引导式工作流、主题切换、3D 视口交互、导出与复现、后端 API。

### 设计与前端

- [设计系统规范](design_system.md)：设计令牌、配色、明暗主题、排版、组件清单、状态规范、响应式断点。
- [前端架构](frontend_architecture.md)：目录结构、模块边界、样式约定、数据契约、构建流程。

### 系统架构与实现

- [架构与数据契约](architecture.md)：分层架构、包结构、核心 Schema、求解器契约。
- [编排与 Agent 通信](orchestration.md)：LangGraph DAG、顺序工作流、Agent 通信、错误记录。
- [能力与自然语言解析](capabilities.md)：能力注册、自然语言解析、LLM 接入、知识库。
- [求解器、网格与后处理](solver_mesh.md)：网格质量、CalculiX 适配、`.frd` 后处理、解析参考公式。

### 验证与开发

- [验证与质量门禁](validation.md)：标准验证、自然语言案例、质量门禁、测试覆盖、清理策略。
- [本地开发配置](local_setup.md)：Python、CalculiX、Gmsh、LLM 和验证命令。
- [技术报告（索引）](technical_report.md)：技术专题汇总入口。

## 能力状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| 结构线弹性静力分析 | 已发布 | 梁、矩形薄板、圆孔/多孔/槽孔开孔薄板和矩形实体块完成自然语言到求解、后处理、可视化和报告闭环 |
| 复杂参数化前处理 | 已接入基础能力 | 开孔薄板支持单孔、偏心孔、多孔和水平长圆槽孔布尔建模；CAD 导入和几何修复属于后续能力 |
| LLM Agent | 可选启用 | OpenAI 兼容接口参与能力选择、参数补全、网格策略建议和工程解释，公开摘要只保留脱敏 trace |
| 非线性、多物理场、接触和损伤 | 路线规划 | 进入发布边界前需要真实求解、参考或工程基准、可视化和文档证据 |

## 快速入口

```powershell
python -m mechagent.cli doctor
python -m mechagent.cli demo --llm-agents
python -m mechagent.cli studio --open-browser
python -m mechagent.cli studio --open-browser --request "求解长480mm、宽280mm、厚6mm、材料钢的长圆槽孔薄板，槽孔中心x=240mm、槽孔中心y=140mm、槽长160mm、槽宽40mm，四边简支，承受0.003MPa向下均布压力的静力响应" --llm-agents --view geometry --auto-run
python -m mechagent.cli inspect "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力静力分析"
python -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
python -m mechagent.cli run "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
python scripts/run_llm_smoke.py
```

## 工作流编排图

```text
Planner -> Designer -> MeshAgent -> SolverAgent -> PostProcAgent -> AnalystAgent -> ReporterAgent
```

`config/mechagent.yaml` 的 `orchestrator.mode: dag` 使 SDK 与 CLI 默认使用 `packages/mechagent/src/mechagent/orchestrator/graph.py` 中的 LangGraph `StateGraph`。顺序工作流使用同一组编排节点、同一套 Pydantic schema 和同一求解配置。详见 [编排与 Agent 通信](orchestration.md)。

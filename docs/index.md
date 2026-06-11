# MechAgent 文档

MechAgent 提供自然语言到开源 CAE/FEA 工作流的多智能体编排闭环。文档覆盖 Studio 工作台、CLI、SDK、Agent 通信、能力注册、工具接入、验证算例、LLM 链路、本地环境和发布质量门禁。

## 文档页面

- [本地开发配置](local_setup.md)：Python 环境、项目包、Studio 前端、CalculiX、Gmsh、LLM 和验证命令。
- [产品蓝图](product_blueprint.md)：产品定位、系统分层、Agent 协作、3D 可视化目标、进度状态面板、质量门槛和路线图。
- [技术报告](technical_report.md)：实现架构、核心契约、验证证据、质量结果和清理策略。

## 能力状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| 结构线弹性静力分析 | 已发布 | 梁、矩形薄板、开孔薄板和矩形实体块完成自然语言到求解、后处理、可视化和报告闭环 |
| 复杂参数化前处理 | 已接入基础能力 | 开孔薄板支持单孔、偏心孔和多孔布尔建模；CAD 导入和几何修复属于后续能力 |
| LLM Agent | 可选启用 | OpenAI 兼容接口参与能力选择、参数补全、网格策略建议和工程解释，公开摘要只保留脱敏 trace |
| 非线性、多物理场、接触和损伤 | 路线规划 | 进入发布边界前需要真实求解、参考或工程基准、可视化和文档证据 |

## 快速入口

```powershell
python -m mechagent.cli demo --llm-agents
python -m mechagent.cli studio --open-browser
python -m mechagent.cli studio --open-browser --request "求解长420mm、宽260mm、厚6mm、孔中心x=180mm、孔中心y=105mm、孔径50mm、材料钢的偏心圆孔薄板，四边简支，承受0.003MPa向下均布压力的静力响应" --llm-agents --view geometry --auto-run
python -m mechagent.cli inspect "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力静力分析"
python -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
python -m mechagent.cli run "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
python scripts/run_llm_smoke.py
```

## 技术细节索引

- 产品目标、用户入口、Studio 体验、能力路线和 3D 可视化目标见“产品蓝图”。
- 包结构、分层架构、运行前预检、FastAPI Studio 服务、React/Vite 前端和可视化数据生成见“技术报告”的“项目定位”“包结构”“MechAgent Studio”。
- LangGraph DAG、顺序工作流、结构化通信和错误记录见“技术报告”的“LangGraph 编排”“Agent 通信机制”。
- 自然语言解析、能力注册、LLM 结构化抽取和插件扩展契约见“技术报告”的“自然语言任务解析”“LLM 与知识库”。
- `ModelParams`、求解摘要状态、后处理摘要和失败优先规则见“技术报告”的“核心 Schema”。
- CalculiX、Gmsh、网格质量、`.frd` 后处理、带孔薄板网格和解析参考公式见“技术报告”的“CalculiX 适配器”“解析参考公式”。
- TC-01 至 TC-05、二十六个独立自然语言案例、质量门禁和清理范围见“技术报告”的“标准验证”“独立自然语言测试案例”“质量结果”“清理策略”。

## 工作流编排图

```text
Planner -> Designer -> MeshAgent -> SolverAgent -> PostProcAgent -> AnalystAgent -> ReporterAgent
```

`config/mechagent.yaml` 的 `orchestrator.mode: dag` 使 SDK 与 CLI 默认使用 `packages/mechagent/src/mechagent/orchestrator/graph.py` 中的 LangGraph `StateGraph`。顺序工作流使用同一组编排节点、同一套 Pydantic schema 和同一求解配置。

## 标准验证

```powershell
python scripts/run_benchmarks.py
```

| 编号 | 问题 | 后端 | 验收标准 |
| --- | --- | --- | --- |
| TC-01 | 悬臂梁端点静力，线弹性 | CalculiX B31 | vs. Euler-Bernoulli，误差 < 1% |
| TC-02 | 四边简支矩形薄板均布载荷弯曲 | CalculiX S4 | vs. Navier 薄板级数，误差 < 2% |
| TC-03 | 固支长方体端面轴向拉伸 | CalculiX C3D8R | vs. 轴向杆闭式解，误差 < 8% |
| TC-04 | 悬臂梁全跨均布线载荷静力弯曲 | CalculiX B31 | vs. Euler-Bernoulli，误差 < 2% |
| TC-05 | 固支长方体端面合力轴向拉伸 | CalculiX C3D8R | vs. 轴向杆闭式解，误差 < 8% |

## 质量门禁

```powershell
python -m mechagent.cli doctor
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
python -m mechagent.cli inspect "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力静力分析" --json
python -m mechagent.cli config validate
python -m pip check
python -m build packages/mechagent-core --no-isolation
python -m build packages/mechagent --no-isolation
python scripts/check_wheel_install.py
python -m mkdocs build --strict
python scripts/clean_artifacts.py
```

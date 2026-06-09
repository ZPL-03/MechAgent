# MechAgent 文档

MechAgent 提供自然语言到开源 CAE/FEA 工作流的多智能体编排闭环。文档覆盖本机配置、
Studio 工作台、运行方式、Agent 通信、标准验证和工程质量门禁。

## 文档页面

- [本地开发配置](local_setup.md)
- [技术报告](technical_report.md)

## 技术细节索引

完整技术细节集中在技术报告中：

- 项目定位、包结构和分层架构见“项目定位”“包结构”“分层架构”。
- LangGraph 与顺序工作流、Agent 间通信和错误记录见“LangGraph 编排”“Agent 通信机制”。
- Studio UI、FastAPI 服务、React/Vite 前端和结果可视化见“MechAgent Studio”。
- 自然语言解析、能力注册、LLM 结构化抽取和插件扩展契约见“自然语言任务解析”。
- `ModelParams`、求解摘要状态、后处理摘要和失败优先规则见“核心 Schema”。
- CalculiX、Gmsh、网格质量、`.frd` 后处理和解析参考公式见“CalculiX 适配器”“解析参考公式”。
- TC-01 至 TC-05、二十个自然语言案例、质量门禁和清理范围见“标准验证”“独立自然语言测试案例”“质量结果”“清理策略”。

## 自然语言工作流

```powershell
python -m mechagent.cli studio --open-browser
python -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
python -m mechagent.cli run "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
```

## Agent DAG

```text
Planner -> Designer -> MeshAgent -> SolverAgent -> PostProcAgent -> AnalystAgent -> ReporterAgent
```

`config/mechagent.yaml` 的 `orchestrator.mode: dag` 使 SDK 与 CLI 默认使用
`packages/mechagent/src/mechagent/orchestrator/graph.py` 中的 LangGraph `StateGraph`。
顺序工作流使用同一组 Agent、同一套 Pydantic schema 和同一求解配置。

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
python -m pip check
python -m build packages/mechagent-core --no-isolation
python -m build packages/mechagent --no-isolation
python scripts/check_wheel_install.py
python -m mkdocs build --strict
python scripts/clean_artifacts.py
```

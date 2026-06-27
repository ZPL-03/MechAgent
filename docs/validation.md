# 验证与质量门禁

本文记录标准验证算例、独立自然语言测试案例、质量门禁命令、测试覆盖范围与清理策略。

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

解析参考公式见 [求解器、网格与后处理](solver_mesh.md)。

## 独立自然语言测试案例

自然语言测试案例位于 `scripts/natural_language_cases.py`，不进入生产 Planner。真实执行命令：

```powershell
python scripts/run_natural_language_cases.py
```

脚本读取 SDK 摘要中的实际 `model_params` 和 `solver_result`，同时校验模型能力编号、几何类型、载荷类型、求解成功状态和有参考值工况的求解误差。无解析参考的工程场景以 `success=true` 和 `verification_status=unverified` 表示真实求解完成，报告展示为未参考校核。

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
| SC-10 | 显式 `N/mm2` 弹性模量和均布压力矩形板 | `STATIC-PLATE` + `pressure` |
| SC-11 | 英文钢悬臂梁端部集中力 | `STATIC-BEAM` + `force` |
| SC-12 | 英文钢矩形板四边简支均布压力 | `STATIC-PLATE` + `pressure` |
| SC-13 | 英文钢矩形实体端面合力轴向拉伸 | `STATIC-SOLID` + `force` |
| SC-14 | 英文钢悬臂梁均布线载荷与 m/cm 单位 | `STATIC-BEAM` + `line_load` |
| SC-15 | 显式 GPa/kPa 矩形板四边简支均布压力 | `STATIC-PLATE` + `pressure` |
| SC-16 | 显式 `N/mm2` 矩形实体端面合力轴向拉伸 | `STATIC-SOLID` + `force` |
| SC-17 | 不显式写「静力分析」的钢悬臂梁最大挠度报告 | `STATIC-BEAM` + `force` |
| SC-18 | `×` 截面分隔符和大写 `KN/m` 的钢悬臂梁均布线载荷 | `STATIC-BEAM` + `line_load` |
| SC-19 | 尺寸前置 `×` 写法和大写 `KPA` 的铝矩形板均布压力 | `STATIC-PLATE` + `pressure` |
| SC-20 | 尺寸前置 `×` 写法的钢长方体端面合力轴向拉伸 | `STATIC-SOLID` + `force` |
| SC-21 | 中文中心圆孔钢开孔薄板均布压力 | `STATIC-PERFORATED-PLATE` + `pressure` |
| SC-22 | 英文中心圆孔钢开孔薄板均布压力 | `STATIC-PERFORATED-PLATE` + `pressure` |
| SC-23 | 中文偏心圆孔钢开孔薄板均布压力 | `STATIC-PERFORATED-PLATE` + `pressure` |
| SC-24 | 英文偏心圆孔钢开孔薄板均布压力 | `STATIC-PERFORATED-PLATE` + `pressure` |
| SC-25 | 中文三孔钢开孔薄板均布压力 | `STATIC-PERFORATED-PLATE` + `pressure` |
| SC-26 | 英文三孔钢开孔薄板均布压力 | `STATIC-PERFORATED-PLATE` + `pressure` |
| SC-27 | 中文长圆槽孔钢开孔薄板均布压力 | `STATIC-PERFORATED-PLATE` + `pressure` |
| SC-28 | 英文长圆槽孔钢开孔薄板均布压力 | `STATIC-PERFORATED-PLATE` + `pressure` |

## 质量门禁

以下命令记录本机维护者完整验证所用解释器。公开用户和 CI 在激活独立 Python 环境后使用等价 `python` 命令执行同一组门禁。

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
python -m mechagent.cli config validate --llm
python -m pip check
python -m build packages/mechagent-core --no-isolation
python -m build packages/mechagent --no-isolation
python scripts/check_wheel_install.py
python -m mkdocs build --strict
python scripts/clean_artifacts.py
```

## 测试覆盖范围

测试覆盖范围按职责分组记录，避免把质量证据分散在入口文档中：

- 发布与环境：公开 API、Studio 服务、Studio 可视化、运行前预检、PEP 561 类型标记、wheel 安装验证脚本、发布元数据、配置局部环境展开、环境诊断键、便携 CI 门禁、清理策略边界。
- 能力与编排：能力注册、能力级工具选择、能力默认工具注册契约、能力默认工具规范化、能力模型编号契约、能力级先分段后匹配、复合请求拆分、多任务工作目录、复合请求部分失败保留成功任务、歧义请求错误归因、LangGraph 状态契约校验。
- LLM 结构化链路：SDK 单次 LLM trace 开关、LLM HTTP 后端契约、LLM 端到端 smoke 脚本、Planner LLM 字符串意图归一化、LLM 工程别名归一化、LLM 中文结构化字段归一化、LLM 多孔薄板孔洞归一化、LLM 槽孔薄板开孔归一化、MeshAgent LLM 网格策略校验、ReporterAgent 确定性工程解读报告、ReporterAgent LLM 工程解释报告、LLM 单对象载荷边界归一化、LLM 空数组与单对象优先级归一化、LLM 几何非线性布尔归一化、LLM 数值漂移防覆盖、LLM 缺参补齐与门禁、LLM advisory 短超时策略。
- 脱敏与公开摘要：LLM provider 错误脱敏、Agent trace 脱敏、trace error 脱敏、报告执行链路摘要脱敏、错误消息脱敏、扩展字段递归脱敏、映射导出脱敏、advisory payload 脱敏。
- 求解与插件：插件主结果字段推断、插件数值字符串解析、插件布尔字符串解析、求解失败摘要、求解失败优先验收状态、摘要失败优先归一化、网格质量失败归因、MeshAgent 输出契约、求解适配器、后处理、工程解读、真实 CalculiX 精度验证。
- 知识库与材料规则：公开知识源、空知识源门禁、空知识索引门禁、知识库检索、材料目录、复合材料名称防误配、工程规则、结构静力执行契约、显式载荷方向缺参诊断。
- 自然语言与案例：自然语言解析、运行前预检、二十八个独立静力输入案例、工程压力单位转换、工程尺寸符号解析、LLM 响应解析、CLI 结构化输出。

## 质量结果

- `check_env.py`：通过；默认检查 Python、依赖、本机求解工具链和 `CALCULIX_CCX` 工具路径键，`--require-llm` 对远端 LLM 凭证执行必需项检查。
- `mechagent.cli config validate --llm`：通过；OpenAI 兼容 Chat Completions 连接正常。
- `ruff format`：通过。
- `ruff check`：通过。
- `mypy --strict`：通过。
- `pytest`：451 passed。
- Studio 前端构建：Vite 构建通过；Markdown 渲染依赖拆分为独立 chunk。
- `scripts/run_llm_smoke.py`：通过；Designer 结构化补参 trace 成功，Planner、MeshAgent、SolverAgent、PostProcAgent、AnalystAgent 和 ReporterAgent 审阅 trace 均已发起，示例悬臂梁任务由 CalculiX 求解，端点位移 14.896 mm，相对参考误差 0.101120%，Markdown 报告包含确定性工程解读和基于 FEM 结果生成的「LLM 工程解释」章节。
- 发布包类型标记：`mechagent/py.typed` 与 `mechagent/core/py.typed` 已纳入包数据。
- wheel 安装验证：构建后的 `mechagent-core` 与 `mechagent` wheel 可安装到隔离目录，并验证导入入口、`Requires-Dist` 依赖元数据、CLI entry point、类型标记和许可证文件。
- TC-01 至 TC-05 真实 CalculiX 验证：通过。
- 二十八个独立自然语言案例真实求解：通过；其中中心圆孔、偏心圆孔、多孔薄板和槽孔薄板案例为真实求解成功且未配置解析参考。
- 知识库标准化和 JSONL 索引脚本：通过。
- 公开 PR 工作流使用 `scripts/check_env.py --profile portable` 和 `pytest -m "not real_solver"`；本地质量门禁执行完整真实 CalculiX 验证和自然语言求解案例。
- `pip check`：无破损依赖。
- `mechagent-core` 与 `mechagent` wheel/sdist 构建：通过。
- MkDocs 严格构建：通过。

## 清理策略

项目可再生成产物由 `.gitignore` 与 `scripts/clean_artifacts.py` 覆盖：清理脚本以脚本所在仓库根目录作为固定边界，删除前校验目标路径位于仓库目录内。

- `__pycache__/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`
- `*.egg-info/`、`build/`、`dist/`、`site/`
- `apps/mechagent-studio/node_modules/`
- `*.frd`、`*.dat`、`*.sta`、`*.lck`、`*.msg`
- `mechagent_output/`
- `knowledge/external/`、`knowledge/index.jsonl`

`knowledge/sources/` 是公开知识源目录。`knowledge/raw/` 是本地私有输入目录，仓库忽略该目录；清理脚本只在该目录为空时移除它。`.env` 是本机私密配置文件，仓库忽略该文件，清理脚本不删除该文件。CalculiX 安装目录保留在 `D:/Calculix/CalculiX-2.23.0-win-x64/`，仓库公开配置通过 `CALCULIX_CCX` 绑定本机可执行文件。

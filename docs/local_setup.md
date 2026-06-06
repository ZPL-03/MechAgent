# 本地开发配置

## Python

主流程统一使用：

```powershell
D:/anaconda3/envs/GPT/python.exe
```

## 项目包

```powershell
D:/anaconda3/envs/GPT/python.exe -m pip install -e packages/mechagent-core
D:/anaconda3/envs/GPT/python.exe -m pip install -e "packages/mechagent[dev,docs]"
```

## 外部程序

| 程序 | 路径或来源 | 状态 |
| --- | --- | --- |
| CalculiX | `D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe` | 已配置 |
| Gmsh | Python 包 `gmsh` | 已安装 |

`config/mechagent.yaml` 使用 `${CALCULIX_CCX:-ccx}`。本机 `.env` 提供
`CALCULIX_CCX=D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe`，不依赖系统 PATH。
SDK 通过 `MechAgent.from_config()` 加载配置时按以下优先级展开环境变量：显式进程环境变量、
配置文件同目录 `.env`、当前工作目录 `.env`。`.env` 内容只参与当前配置解析，不写入进程级环境变量。

## LLM

`.env.example` 提供公开模板；本机 `.env` 包含：

```text
URL=OpenAI 兼容接口地址
API_KEY=接口密钥
MODEL_NAME=模型名称
CALCULIX_CCX=CalculiX ccx 可执行文件路径
```

本地 LLM 远端连接检查：

```powershell
D:/anaconda3/envs/GPT/python.exe -m mechagent.cli config validate --llm
```

该命令依赖 `.env` 中的私密凭证和远端授权状态。开源质量门禁使用本地配置校验：

```powershell
D:/anaconda3/envs/GPT/python.exe -m mechagent.cli config validate
```

`config/mechagent.yaml` 默认 `orchestrator.use_llm_agents: false`。远端 LLM 结构化抽取与
审阅可通过 `--llm-agents` 启用；Planner 的能力识别使用当前能力声明的描述、关键词和示例请求，
并合并当前能力的缺参诊断。Designer 的 `ModelParams` 输出按当前能力声明的 LLM 抽取契约、注册表、Pydantic schema、
工程规则、执行契约和工具链约束进入后续链路。Planner 已记录缺失字段时，Designer 仍会尝试 LLM
结构化补齐；本地 parser 和 LLM 均无法生成可执行参数时返回缺参诊断；能力 parser 已生成验证通过的本地
`ModelParams` 时，后续链路使用本地参数，LLM 输出进入 trace 审计；能力声明 `model_case_ids` 时，
`ModelParams.case_id` 必须属于声明集合。
SDK 单次调用可使用
`use_llm_agents=True`。SDK 单次覆盖使用独立配置副本，不改变 `MechAgent.config` 的持久值。
远端 LLM Agent 闭环验收使用 `scripts/run_llm_smoke.py`，该脚本校验所有 Agent trace、
真实 CalculiX 求解、参考误差验收和报告路径。

`scripts/check_env.py` 默认检查 Python、依赖和配置解析后的 CalculiX 可执行文件。
`--config` 可指定运行配置文件；`--require-llm` 要求 `.env` 或环境变量中
`URL`、`API_KEY`、`MODEL_NAME` 均已配置。环境摘要同时报告 `CALCULIX_CCX`
工具路径键是否存在。
`--profile portable` 用于公开 CI 和跨机器环境，校验 Python 版本与 Python 依赖，不要求本机
`.env` 和 CalculiX 可执行文件存在。

## 自然语言仿真

```powershell
D:/anaconda3/envs/GPT/python.exe -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
D:/anaconda3/envs/GPT/python.exe -m mechagent.cli run "求解长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力的静力响应"
D:/anaconda3/envs/GPT/python.exe -m mechagent.cli run "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
D:/anaconda3/envs/GPT/python.exe -m mechagent.cli run "solve a steel beam length 1000mm, section 20mm x 40mm, cantilever fixed at one end, downward 1000N tip force static analysis" --llm-agents --json
D:/anaconda3/envs/GPT/python.exe scripts/run_llm_smoke.py
```

## 验证命令

```powershell
D:/anaconda3/envs/GPT/python.exe scripts/check_env.py
D:/anaconda3/envs/GPT/python.exe scripts/check_env.py --help
D:/anaconda3/envs/GPT/python.exe -m ruff format packages tests scripts
D:/anaconda3/envs/GPT/python.exe -m ruff check packages tests scripts
D:/anaconda3/envs/GPT/python.exe -m mypy packages scripts tests
D:/anaconda3/envs/GPT/python.exe -m pytest
D:/anaconda3/envs/GPT/python.exe scripts/run_benchmarks.py
D:/anaconda3/envs/GPT/python.exe scripts/run_natural_language_cases.py
D:/anaconda3/envs/GPT/python.exe scripts/run_llm_smoke.py
D:/anaconda3/envs/GPT/python.exe scripts/build_knowledge.py
D:/anaconda3/envs/GPT/python.exe scripts/index_knowledge.py
D:/anaconda3/envs/GPT/python.exe -m mechagent.cli config validate
D:/anaconda3/envs/GPT/python.exe -m mechagent.cli benchmark --json
D:/anaconda3/envs/GPT/python.exe -m pip check
D:/anaconda3/envs/GPT/python.exe -m build packages/mechagent-core --no-isolation
D:/anaconda3/envs/GPT/python.exe -m build packages/mechagent --no-isolation
D:/anaconda3/envs/GPT/python.exe scripts/check_wheel_install.py
D:/anaconda3/envs/GPT/python.exe -m mkdocs build --strict
D:/anaconda3/envs/GPT/python.exe scripts/clean_artifacts.py
```

配置默认工具和能力默认工具均使用工厂注册名称校验；能力默认工具在注册时规范化为工厂注册名。

## 标准算例结果

| 编号 | 物理量 | CalculiX | 解析参考 | 相对误差 | 阈值 |
| --- | --- | ---: | ---: | ---: | ---: |
| TC-01 | `tip_deflection` | 14.896 mm | 14.880952 mm | 0.101120% | 1% |
| TC-02 | `center_deflection` | 0.155959 mm | 0.154233 mm | 1.118913% | 2% |
| TC-03 | `axial_displacement` | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% |
| TC-04 | `tip_deflection` | 5.58805 mm | 5.580357 mm | 0.137856% | 2% |
| TC-05 | `axial_displacement` | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% |

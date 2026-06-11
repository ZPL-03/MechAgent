# 本地开发配置

## Python

MechAgent 支持 Python 3.9 及以上版本。开发和运行建议使用独立虚拟环境。

Windows `venv`：

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Conda：

```powershell
conda create -n mechagent python=3.9 -y
conda activate mechagent
python -m pip install --upgrade pip
```

命令示例默认在已激活的虚拟环境中执行。

## 项目包

```powershell
python -m pip install -e packages/mechagent-core
python -m pip install -e "packages/mechagent[dev,docs]"
```

## Studio 前端

MechAgent Studio 的后端入口由 Python 包提供。Node.js 只用于构建 `apps/mechagent-studio`
下的 React/TypeScript 前端源码。

```powershell
npm --prefix apps/mechagent-studio ci --no-audit --no-fund
npm --prefix apps/mechagent-studio run build
```

构建产物写入 `packages/mechagent/src/mechagent/ui/static`，随 `mechagent` 包一起发布。

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
python -m mechagent.cli config validate --llm
```

该命令依赖 `.env` 中的私密凭证和远端授权状态。开源质量门禁使用本地配置校验：

```powershell
python -m mechagent.cli config validate
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
远端 LLM Agent 闭环验收使用 `scripts/run_llm_smoke.py`，该脚本校验 Designer 结构化补参 trace、
非关键审阅 trace 发起记录、真实 CalculiX 求解、参考误差验收、报告路径和报告正文中的
“LLM 工程解释”章节。

几何建模、网格划分、结果场和进度状态的统一工作台目标见 [产品蓝图](product_blueprint.md)。

本机运行环境自检：

```powershell
python -m mechagent.cli doctor
python -m mechagent.cli doctor --json
python -m mechagent.cli doctor --llm
```

`doctor` 检查 Python 版本、Python 依赖、配置解析、CalculiX 路径、求解器/网格器/能力注册表、Studio 静态资源、可选前端开发工具和 Git；`--llm` 使用当前 `.env` 或环境变量调用远端 OpenAI 兼容接口做连接检查。

`scripts/check_env.py` 默认检查 Python、依赖和配置解析后的 CalculiX 可执行文件。
`--config` 可指定运行配置文件；`--require-llm` 要求 `.env` 或环境变量中
`URL`、`API_KEY`、`MODEL_NAME` 均已配置。环境摘要同时报告 `CALCULIX_CCX`
工具路径键是否存在。
`--profile portable` 用于公开 CI 和跨机器环境，校验 Python 版本与 Python 依赖，并跳过本机
`.env` 与 CalculiX 可执行文件存在性检查。

## 自然语言仿真

```powershell
python -m mechagent.cli demo --llm-agents
python -m mechagent.cli studio --open-browser
python -m mechagent.cli studio --open-browser --request "求解长420mm、宽260mm、厚6mm、孔中心x=180mm、孔中心y=105mm、孔径50mm、材料钢的偏心圆孔薄板，四边简支，承受0.003MPa向下均布压力的静力响应" --llm-agents --view geometry --auto-run
python -m mechagent.cli inspect "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力静力分析"
python -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
python -m mechagent.cli run "求解长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力的静力响应"
python -m mechagent.cli run "求解长400mm、宽240mm、厚6mm、中心圆孔孔径60mm、材料钢的开孔薄板，四边简支，承受0.004MPa向下均布压力的静力响应"
python -m mechagent.cli run "求解长420mm、宽260mm、厚6mm、孔中心x=180mm、孔中心y=105mm、孔径50mm、材料钢的偏心圆孔薄板，四边简支，承受0.003MPa向下均布压力的静力响应"
python -m mechagent.cli run "求解长520mm、宽320mm、厚8mm、材料钢的多孔薄板，孔1中心x=130mm、中心y=110mm、孔径44mm，孔2中心x=260mm、中心y=210mm、孔径54mm，孔3中心x=410mm、中心y=120mm、孔径40mm，四边简支，承受0.0025MPa向下均布压力的静力响应"
python -m mechagent.cli run "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
python -m mechagent.cli run "solve a steel beam length 1000mm, section 20mm x 40mm, cantilever fixed at one end, downward 1000N tip force static analysis" --llm-agents --json
python scripts/run_llm_smoke.py
```

Studio 命令输出服务监听地址和浏览器入口。`demo` 使用示例库默认工况 `SC-23`，打开 Studio 并自动提交偏心圆孔薄板静力请求；`--example SC-25` 切换为多孔薄板工况。`--open-browser` 打开浏览器入口；监听地址为 `0.0.0.0` 或 `::` 时，浏览器入口使用 `127.0.0.1`。`--request`、`--llm-agents` 和 `--view geometry|mesh|result` 生成带自然语言请求、参数补全状态和初始视图的可复现工作台入口。`--auto-run` 与 `--request` 同时使用时，工作台页面加载后自动提交当前请求。

## 验证命令

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
python -m mechagent.cli benchmark --json
python -m pip check
python -m build packages/mechagent-core --no-isolation
python -m build packages/mechagent --no-isolation
python scripts/check_wheel_install.py
python -m mkdocs build --strict
python scripts/clean_artifacts.py
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

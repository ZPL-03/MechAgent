# mechagent

`mechagent` 是 MechAgent 的多智能体主框架包，提供 SDK、CLI、LLM 后端、知识库、
Agent 编排层和 MechAgent Studio 本地工程工作台。它负责把自然语言 CAE/FEA 需求编排为
参数建模、网格划分、求解计算、后处理、校核、可视化和报告生成链路。

更完整的产品蓝图、总体架构、3D 可视化目标、进度展示边界和能力路线见 [docs/product_blueprint.md](../../docs/product_blueprint.md)。

## 命令

```powershell
python -m mechagent.cli doctor
python -m mechagent.cli demo --llm-agents
python -m mechagent.cli studio --open-browser
python -m mechagent.cli studio --open-browser --request "求解长420mm、宽260mm、厚6mm、孔中心x=180mm、孔中心y=105mm、孔径50mm、材料钢的偏心圆孔薄板，四边简支，承受0.003MPa向下均布压力的静力响应" --llm-agents --view geometry --auto-run
python -m mechagent.cli capabilities
python -m mechagent.cli examples
python -m mechagent.cli examples --geometry plate --model-case STATIC-PERFORATED-PLATE
python -m mechagent.cli inspect "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力静力分析"
python -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
python -m mechagent.cli run "求解长400mm、宽240mm、厚6mm、中心圆孔孔径60mm、材料钢的开孔薄板，四边简支，承受0.004MPa向下均布压力的静力响应"
python -m mechagent.cli run "求解长420mm、宽260mm、厚6mm、孔中心x=180mm、孔中心y=105mm、孔径50mm、材料钢的偏心圆孔薄板，四边简支，承受0.003MPa向下均布压力的静力响应"
python -m mechagent.cli run "求解长520mm、宽320mm、厚8mm、材料钢的多孔薄板，孔1中心x=130mm、中心y=110mm、孔径44mm，孔2中心x=260mm、中心y=210mm、孔径54mm，孔3中心x=410mm、中心y=120mm、孔径40mm，四边简支，承受0.0025MPa向下均布压力的静力响应"
python -m mechagent.cli run "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
python -m mechagent.cli run "solve a steel beam length 1000mm, section 20mm x 40mm, cantilever fixed at one end, downward 1000N tip force static analysis" --json
python -m mechagent.cli run "solve a steel beam length 1000mm, section 20mm x 40mm, cantilever fixed at one end, downward 1000N tip force static analysis" --llm-agents --json
```

## 编排节点

```text
Planner -> Designer -> MeshAgent -> SolverAgent -> PostProcAgent -> AnalystAgent -> ReporterAgent
```

默认 `dag` 模式使用 LangGraph `StateGraph`。`sequential` 模式使用同一组 Agent 和
同一套 Pydantic schema。

Planner 按 `SimulationCapability` 注册表生成 `SimulationIntent` 和 `TaskItem`，并通过
`TaskItem.intent` 传递结构化意图；能力声明提供 Planner 描述、关键词、示例请求、
默认网格器、默认求解器和请求分段器，用于 LLM 能力选择上下文、工具选择和复合请求拆分。
能力默认工具使用工厂注册名称校验，并在注册时规范化为工厂注册名。扩展能力通过
`register_capability()` 注册，通过 `unregister_capability()` 注销。Designer 按能力注册表生成 `DesignAgentOutput`，
使用当前能力声明的 LLM 抽取契约和模型归一化函数，并调用当前能力声明的执行契约。
MeshAgent 按能力或全局配置生成 `MeshAgentOutput`，SolverAgent 按能力或全局配置选择求解器并调用结果评价器。
启用 LLM Agent 时，MeshAgent 基于 `ModelParams` 生成并校验网格策略建议；ReporterAgent 始终基于 `TaskRunRecord` 输出确定性工程解读，启用 LLM Agent 时追加 LLM 工程解释。
ReporterAgent 的 LLM 工程解释上下文递归剥离执行链路 trace 审计字段；七个 Agent 均具备 LLM trace，报告输出执行链路摘要。
失败结果通过 `ErrorRecord(node, code, message, missing_fields)` 进入 SDK 摘要和报告。
多个完整仿真任务在同一请求中出现时，Planner 输出多个 `TaskItem`；工作流按 `TASK_N`
子目录隔离网格、求解输入和输出文件。
复合请求中单个任务失败时，失败任务进入 `ErrorRecord`，其余任务继续执行并保留求解结果。
LangGraph 阶段校验 `active_tasks` 与阶段产物列表长度；状态契约不一致时生成对应节点错误记录。

公开配置默认关闭远端 LLM 调用；CLI 单次运行使用 `--llm-agents`，SDK 单次调用使用
`use_llm_agents=True`，也可设置 `orchestrator.use_llm_agents: true`。
SDK 单次覆盖使用独立配置副本，不改变 `MechAgent.config` 的持久值。启用后，Planner 可调用 LLM 识别已注册能力并合并能力缺参诊断，Designer 可调用
LLM 生成 `ModelParams` JSON；结构化输出通过注册表、Pydantic schema、工程规则和执行契约校验后进入
后续网格与求解链路。`SimulationIntent.missing_fields` 非空时，Designer 仍会尝试 LLM 结构化补齐；
本地 parser 和 LLM 均无法生成可执行参数时返回缺参诊断；能力 parser 已生成验证通过的本地
`ModelParams` 时，后续链路使用本地参数，LLM 输出进入 trace 审计；能力声明 `model_case_ids` 时，
`ModelParams.case_id` 必须属于声明集合。LLM 输出的单一 `load`、`load_condition`、`bc`
或 `boundary_condition` 对象会在 schema 校验前归一化为 `ModelParams.loads`
和 `ModelParams.bcs` 数组；空复数字段和有效单数字段同时存在时使用非空输入。
Designer 在 schema 校验前归一化中文几何类型、载荷类型、边界类型、方向、尺寸字段和材料字段。
Agent trace 会记录远端响应或脱敏后的调用错误。
SDK/CLI JSON 摘要只输出 trace 元数据、错误状态和 prompt/response 字符数，不输出原始
prompt 或 response。

## Studio

Studio 后端使用 FastAPI 与 Uvicorn，由 `python -m mechagent.cli studio` 启动；`python -m mechagent.cli demo` 从示例库读取 `SC-23` 作为默认展示工况，打开 Studio 并自动提交偏心圆孔薄板静力请求，`--example` 可选择其他示例编号。
启动命令输出服务监听地址和浏览器入口；监听地址为 `0.0.0.0` 或 `::` 时，浏览器入口使用 `127.0.0.1`。
前端使用 React、TypeScript、Vite、Three.js 和 Markdown 渲染组件，构建后的静态资源位于
`mechagent/ui/static` 并随包发布。宽屏桌面视口采用左侧输入、中部结果、右侧检查器三栏布局；宽度不超过 1800px 时检查区位于主工作区下方并保持两列排布，宽度不超过 900px 时整体切换为单列布局。宽屏检查区使用整列滚动，验收指标面板按内容自适应高度，避免指标卡被内部滚动容器裁切。初始态、运行态和结果态保持固定响应式断点和面板尺寸约束，避免 3D 画布、报告或检查区造成浏览器横向溢出。界面展示自然语言请求、可展开运行环境面板、运行前预检、参数补全开关、示例库、当前工作台链接复制、基于当前 Python 执行器的 CLI 复现命令复制、运行历史、后端作业状态、求解流程、Agent 链路、验收指标、
任务结果矩阵、带类型标签和路径复制入口的阶段产物、3D 几何/网格/结果视图、摘要 JSON 和 Markdown 报告。运行历史保留自然语言请求、紧凑摘要和限长 Markdown 报告文本；选中历史项后可重跑此请求恢复几何、网格和结果视图，3D 场景本身不写入浏览器存储。Markdown 报告包含确定性工程解读，并在启用 LLM Agent 时包含 LLM 工程解释；Markdown 报告和摘要 JSON 支持复制和下载。CLI 复现命令、工作台链接、报告正文、阶段产物路径和摘要 JSON 的复制动作带有可见状态反馈。`studio --request`、`--llm-agents`、`--view geometry|mesh|result` 和 `--auto-run` 生成可复现工作台入口；工作台链接通过 `request`、`llm` 和 `view` 查询参数恢复自然语言请求、参数补全状态和 3D 视图模式，`run=1` 作为一次性自动运行信号。Studio 使用 `/api/inspect` 读取 Planner 预检结果，使用 `/api/jobs` 创建作业并轮询
`/api/jobs/{job_id}` 获取状态、阶段事件和最终结果；`/api/diagnostics` 返回与 CLI `doctor` 共用的运行环境诊断摘要，顶栏运行环境面板展示 Python、配置、依赖、静态资源、注册表、求解器、LLM、前端工具和 Git 状态，页面加载默认不触发远端 LLM 连接检查；`/api/examples` 返回与 CLI `examples` 共用的自然语言示例库。Agent 链路面板读取公开摘要中的 `TaskItem`、`ModelParams`、`MeshResult`、`SolverRunSummary`、`PostProcessingSummary` 和 Reporter trace，展示结构化产物、网格质量诊断和脱敏 LLM trace 摘要。3D 场景由 Python 后处理层根据
`ModelParams`、`.inp` 网格、`.frd` 位移/应力场和求解摘要生成；浏览器端按几何类型映射求解坐标，梁保持横向弯曲视角，矩形板、开孔薄板和矩形实体块将求解 `Z` 轴映射为 Three.js 竖向轴；几何模式显示 `ModelParams.loads` 与 `ModelParams.bcs` 对应的前处理符号，包含集中力箭头、线载荷箭头、均布压力箭头、端面载荷、固定端夹持和边界支承；符号直接贴合载荷面或约束边界，不带文字标注。网格模式使用低透明单元面、高对比单元边和节点表达真实 `.inp` 拓扑，梁网格以矩形截面分段棱柱表达 B31 单元拓扑；结果模式只显示变形、网格边、节点场、颜色图例和当前结果场，默认显示 `U` 位移模量，场量下拉菜单可切换 `Ux`、`Uy`、`Uz` 位移分量；`.frd` 存在应力场时可切换 `S Mises`、`Sxx`、`Syy`、`Szz`、`Sxy`、`Syz` 和 `Sxz`。壳单元 `.frd` 派生节点场会按真实网格节点顺序对齐。结果视口提供等轴、俯视、前视和右视快捷视角，右下角透明嵌入式 XYZ 全局坐标系跟随主相机旋转，颜色图例随当前场量同步。开孔薄板的几何视图来自单孔或多孔参数化孔洞轮廓，网格和结果视图来自 Gmsh 生成的真实 `.inp` 单元。参照底网按当前几何或结果包围盒居中并留出视图边距。Three.js 画布在初始化、尺寸变化、视图切换和用户交互时按需渲染，静止状态不运行连续动画循环。当前 3D 画布支持 PNG 导出，SVG 用于兼容视图和静态下载。

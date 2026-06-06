# mechagent

`mechagent` 是 MechAgent 的多智能体主框架包，提供 SDK、CLI、LLM 后端、知识库和
Agent 编排层。

## 命令

```powershell
python -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
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
MeshAgent 按能力或全局配置生成 `MeshAgentOutput`，SolverAgent 按能力或全局配置选择求解器并调用结果评价器。七个 Agent
均具备 LLM trace，报告输出通信摘要。
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

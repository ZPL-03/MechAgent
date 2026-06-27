# 编排与 Agent 通信

本文描述 LangGraph DAG 与顺序工作流、Agent 间结构化通信、错误记录与状态契约。整体架构见 [架构与数据契约](architecture.md)。

## LangGraph 编排

LangGraph 入口位于：

```text
packages/mechagent/src/mechagent/orchestrator/graph.py
```

`config/mechagent.yaml` 默认设置：

```yaml
orchestrator:
  mode: dag
```

SDK 与 CLI 调用 `MechAgent.run()` 时读取该配置；SDK 可通过 `use_llm_agents=True` 启用单次 Agent LLM trace。单次覆盖使用独立配置副本，不改变 `MechAgent.config` 的持久值。`dag` 模式使用 LangGraph `StateGraph`，`sequential` 模式使用 `SequentialWorkflow`，两种模式共用同一组 Agent。

## Agent 通信机制

MechAgent 采用进程内结构化状态通信。

顺序工作流的数据链路：

```text
TaskItem(intent=SimulationIntent)
  -> DesignAgentOutput(model_params, designer_llm_trace)
  -> MeshAgentOutput(mesh_result, mesh_llm_trace)
  -> SolverRunSummary
  -> PostProcessingSummary
  -> analysis_text
```

LangGraph 工作流使用 `MechAgentState` 作为共享 `TypedDict`。每个节点返回状态增量，LangGraph 合并后传给下一节点。任务、模型、网格、求解和后处理结果在图状态中保持 Pydantic 对象；SDK 摘要、报告和命令行 JSON 输出在边界处通过 `model_dump(mode="json")` 导出。SDK 摘要的每个任务包含 `case_id`、`capability_id`、`analysis_type`、`intent`、`model_params`、`mesh_result`、`solver_result`、`post_summary`、任务级 Agent trace 和错误记录；顶层摘要包含 `reporter_llm_trace`。

| Agent | 输入 | 输出 |
| --- | --- | --- |
| Planner | 用户自然语言 | 携带 `SimulationIntent` 的 `TaskItem` 列表 |
| Designer | `TaskItem` | `DesignAgentOutput`，包含 `ModelParams` 和 `designer_llm_trace` |
| MeshAgent | `ModelParams` | `MeshAgentOutput`，包含 `MeshResult` 和 `mesh_llm_trace` |
| SolverAgent | `TaskItem`、`ModelParams`、`MeshResult` | 按能力评价器生成 `SolverRunSummary` |
| PostProcAgent | `SolverRunSummary` | `PostProcessingSummary` |
| AnalystAgent | `TaskItem`、`PostProcessingSummary` | 工程解读文本 |
| ReporterAgent | `TaskRunRecord` 列表 | Markdown 报告、确定性工程解读、可选 LLM 工程解释和 `reporter_llm_trace` |

## 复合请求与错误隔离

工作流根目录保存顶层 `report.md`。每个 `TaskItem` 使用 `TASK_N` 子目录保存网格、求解输入和求解器输出，复合请求中的同类模型不会共享文件名或覆盖彼此产物。LangGraph 状态维护 `active_tasks` 和 `failed_records`；单个任务失败时从活跃列表移除并进入错误记录，其余任务继续通过后续节点。

每个阶段消费状态前校验 `active_tasks` 与所需阶段产物列表长度；状态契约不一致时生成对应节点的 `ErrorRecord`，任务进入 `failed_records`，不会被 `zip()` 截断后从报告中静默消失。Reporter 生成最终记录前再次校验 `model_params_list`、`mesh_results`、`solver_results`、`post_summaries` 和 `analysis_texts` 的长度一致性；最终状态不完整时生成 `report_failed` 错误记录。Reporter 按 Planner 原始任务顺序合并成功记录和失败记录。

## Agent LLM trace

每个 Agent 通过 `AgentLLMAdvisor` 生成 LLM trace。启用 LLM Agent 时，Planner 可调用 LLM 从注册能力列表中识别能力意图，并合并注册能力自身的缺参诊断；Designer 可调用 LLM 生成 `ModelParams` JSON。结构化输出必须通过能力注册表、Pydantic schema、工程规则、执行契约和工具适配器约束后进入后续链路；`SimulationIntent.missing_fields` 非空时，Designer 仍会尝试 LLM 结构化补齐；本地 parser 和 LLM 均无法生成可执行参数时返回结构化缺参或歧义错误。能力 parser 已生成验证通过的本地 `ModelParams` 时，后续链路使用本地参数，Designer LLM 输出进入 trace 审计；未通过校验的 LLM 输出只进入 trace 诊断。

Planner trace 位于 `TaskItem.planner_llm_trace`；Designer 和 Mesh trace 位于 `TaskRunRecord` 的显式字段；Solver、PostProc 和 Analyst trace 位于各自输出摘要；Reporter trace 位于工作流顶层摘要。

Planner 在能力注册表无法直接命中时使用主路径 LLM HTTP 策略进行结构化能力选择；Designer 的结构化补参使用主路径 LLM HTTP 策略。MeshAgent 可调用 LLM 生成 `seed_size` 与 `element_type` 网格策略建议，建议通过 JSON 解析、几何兼容性和网格尺寸范围校验后进入网格器；SolverAgent、PostProcAgent、AnalystAgent 和 ReporterAgent 的工程审阅不改变求解、后处理或报告主结果，审阅调用使用短超时和单次尝试；远端响应慢或失败时记录脱敏 trace error，主求解链路继续按结构化数据执行。

ReporterAgent 不依赖远端 LLM 生成基础工程解释；报告固定包含基于 `TaskRunRecord` 的结果结论、验收解释、网格与求解、模型材料、边界载荷、后处理标量和复核建议。启用 LLM Agent 时，ReporterAgent 额外把求解摘要、后处理标量、网格元数据、载荷和边界条件发送给 LLM，递归剥离执行链路 trace 审计字段后输出「LLM 工程解释」章节，解释结果含义、可信度、局限和复核建议。

`scripts/run_llm_smoke.py` 通过 SDK 启用 `use_llm_agents=True`，校验公开摘要中 Designer 结构化补参 trace 成功且无错误，Planner、MeshAgent、SolverAgent、PostProcAgent、AnalystAgent 和 ReporterAgent 的审阅 trace 已发起并记录 prompt，同时校验真实求解成功、参考验收通过、报告路径生成和报告正文包含「LLM 工程解释」章节。

## 错误记录模型

顺序工作流中的任务级异常进入 `TaskRunRecord.error`，报告输出「错误诊断」章节。DAG 工作流使用同一错误记录模型。Planner 阶段失败生成请求级 `TaskRunRecord`；Designer 及后续节点失败保留已有阶段产物并写入对应 Agent 节点名。`ErrorRecord` 包含 `node`、`code`、`message` 和 `missing_fields`，错误码覆盖空请求、标准验证入口误用、能力范围外请求、复合请求歧义、必要仿真输入缺失、Designer 输入意图缺失以及 Mesh、Solver、PostProc、Analyst 节点失败。SDK 以 `success=false` 返回失败结果，CLI 输出报告后返回非零退出码。

LLM 接入与脱敏规则、知识库见 [能力与自然语言解析](capabilities.md)。

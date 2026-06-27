# 能力与自然语言解析

本文描述能力注册、自然语言任务解析、LLM 抽取契约与知识库。编排与通信见 [编排与 Agent 通信](orchestration.md)，求解与网格见 [求解器、网格与后处理](solver_mesh.md)。

## 自然语言任务解析

Planner 通过能力注册表识别任务类型，不绑定测试案例。结构静力需求生成：

```text
SimulationIntent(capability_id="structural_static")
TaskItem(case_id="STATIC-STRUCTURAL", capability_id="structural_static")
```

`TaskItem.intent` 保存标准化意图与原始请求，`TaskItem.planner_llm_trace` 保存 Planner 识别记录。`TaskItem.case_id` 和 `TaskItem.title` 来自 `SimulationCapability` 声明。`SimulationCapability` 同时声明 Planner 描述、关键词、示例请求、默认网格器、默认求解器、请求分段器、请求匹配器、几何识别函数、缺参诊断函数、`ModelParams` 解析器、能力执行契约、LLM 抽取补充契约、模型编号、模型归一化函数和结果评价器。

扩展能力通过 `register_capability()` 注册，通过 `unregister_capability()` 注销，Planner 按注册表顺序匹配用户请求；能力声明请求分段器时，Planner 先按该能力的分段器生成候选片段，再对每个片段调用该能力的匹配器并生成多个 `TaskItem`。同一语句中出现多个几何类型且无法拆分为完整任务时，Designer 阶段返回 `ambiguous_request`，报告保留「单一几何类型」诊断字段。本地匹配未命中且启用 LLM Agent 时，Planner 可让 LLM 根据能力描述、关键词和示例请求在已注册能力中选择能力意图，并叠加该能力的缺参诊断。

Planner LLM 响应中的能力编号按注册表编号做大小写、空白和连字符归一化；缺参字段可由字符串数组或以中文顿号、逗号、分号、换行分隔的字符串表达；置信度可由数字或数字字符串表达，并限制在 0 到 1。

Designer 按 `capability_id` 从注册表获取解析器，先尝试生成本地结构化草案，并在启用 LLM Agent 时请求 LLM 生成 `ModelParams` JSON。本地结构化草案验证通过时优先进入求解参数，LLM 输出保留为审计记录；本地 parser 无法生成参数且 LLM 输出可通过校验时，Designer 采用 LLM 结构化参数。两条路径均不可用时，Designer 依据 `SimulationIntent.missing_fields` 返回缺参诊断。进入求解前的参数均需通过参数范围检查和能力执行契约。能力声明了 `model_case_ids` 时，`ModelParams.case_id` 必须属于声明集合。

### 单位与别名归一化

LLM JSON 中显式出现的工程单位由框架确定性归一化：长度转为 mm，力转为 N，线载荷转为 N/mm，压力和弹性模量转为 MPa，密度转为 tonne/mm^3。无法识别的显式单位会进入 Designer trace 错误，不进入求解链路。

LLM JSON 中常见工程别名会在进入 Pydantic schema 前归一化：`concentrated`、`concentrated_force`、`point_force` 和 `tip_force` 转为 `force`，`clamped` 转为 `fixed`，自由度编号 `1..6` 转为 `ux/uy/uz/rx/ry/rz`。

Designer 在 schema 校验前将中文几何类型、载荷类型、边界类型、方向、尺寸字段和材料字段归一化为枚举与标准字段。板的「向下/向上」按全局 Z 向解释，梁的「向下/向上」按全局 Y 向解释，实体的「拉伸/受拉/受压/压缩」按全局 X 向解释。LLM 输出中的 `analysis.nlgeom` 使用显式布尔语义；`linear`、`linear_static`、`geometrically_linear` 和 `small_deformation` 归一化为 `false`，不会被非空字符串规则误判为非线性。单一载荷或单一边界条件可由 LLM 以对象形式输出；Designer 将 `load`、`loads`、`loadings`、`load_condition`、`load_conditions` 以及 `bc`、`bcs`、`boundary_conditions`、`boundary_condition`、`boundaries`、`boundary` 统一归一化为 `ModelParams.loads` 和 `ModelParams.bcs` 数组。LLM 同时输出空复数字段和有效单数字段时，Designer 以非空对象或非空数组作为解析源。

SolverAgent 按同一 `capability_id` 获取结果评价器，将求解器输出转换为带参考值、误差和验收状态的 `SolverRunSummary`。

### 解析范围

| 几何 | 支持参数 | 载荷 | 边界 | 单元 |
| --- | --- | --- | --- | --- |
| 梁 | 长度、矩形截面、材料目录或 E/ν、横向载荷方向 | 端部集中力、全跨均布线载荷 | 一端固支 | B31 |
| 矩形板 | 长、宽、厚、材料目录或 E/ν | 均布压力 | 四边简支 | S4 |
| 开孔薄板 | 长、宽、厚、圆孔半径/孔径、孔心坐标、槽孔长度、槽孔宽度、槽孔中心、材料目录或 E/ν | 均布压力 | 外边界四边简支，开孔边界自由 | S3/S4 |
| 矩形实体块 | 长、宽、高、材料目录或 E/ν、轴向载荷方向 | 端面压力、端面合力 | 一端固定 | C3D8R |

开孔薄板使用统一的 `ModelParams.geometry.dimensions` 字段：圆孔使用 `hole_count`、`hole_radius`、`hole_center_x/y` 与编号字段；槽孔使用 `slot_count`、`slot_length`、`slot_width`、`slot_center_x/y` 与编号字段。本地自然语言解析支持“槽长/槽宽”“槽孔长/槽孔宽”“长圆槽孔长/长圆槽孔宽”等工程表达。LLM JSON 可使用 `hole`、`holes`、`opening`、`openings`、`slot`、`slots`、`slotted_hole` 或 `obround_slot`，Designer 在进入 Pydantic schema 前归一到同一字段集合。

内置材料目录位于 `mechagent.core.materials`，包含钢和铝合金，可通过别名匹配。材料数据以代码目录作为运行时单点来源。混凝土、钢筋混凝土、复合材料和碳纤维等材料名称不会按内置钢/铝别名自动匹配；这类请求需要显式给出 `E` 和 `nu` 作为等效各向同性线弹性参数，或由扩展能力提供专用材料模型。自然语言解析支持中文尺寸名以及 `length`、`width`、`height`、`thickness`、`section` 等英文尺寸表达。梁横向载荷和实体端面轴向载荷必须显式给出方向或拉压语义。缺失方向时，Planner/Designer 错误记录保留「载荷方向」或「端面载荷方向」缺参字段。

示例请求：

```powershell
python -m mechagent.cli run "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应"
python -m mechagent.cli run "求解长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力的静力响应"
python -m mechagent.cli run "求解长400mm、宽240mm、厚6mm、中心圆孔孔径60mm、材料钢的开孔薄板，四边简支，承受0.004MPa向下均布压力的静力响应"
python -m mechagent.cli run "求解长480mm、宽280mm、厚6mm、材料钢的长圆槽孔薄板，槽孔中心x=240mm、槽孔中心y=140mm、槽长160mm、槽宽40mm，四边简支，承受0.003MPa向下均布压力的静力响应"
python -m mechagent.cli run "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
python -m mechagent.cli run "solve a steel beam length 1000mm, section 20mm x 40mm, cantilever fixed at one end, downward 1000N tip force static analysis" --json
```

模型归一化、参数范围与执行契约的 Schema 细节见 [架构与数据契约](architecture.md)。

## CAD 几何到求解

除纯自然语言入口外，能力解析支持从 CAD 形体获取几何、由自然语言补全材料、载荷与边界，打通「CAD 文件 → 求解」链路。`GeometryAgent` 调用 CAD 内核导入 STEP/IGES/BREP 并产出 `GeometryCandidate`（几何类型、包围盒尺寸、区域候选）；`parse_static_model_params_from_geometry(candidate, completion)` 把几何候选的包围盒尺寸按几何类型重新解释（梁取最长边为长度、其余两边为截面，板取最薄边为厚度，实体取长宽高），与描述材料、载荷与边界的自然语言补全合成完整请求，复用既有结构静力解析器生成 `ModelParams`，`metadata.geometry_source` 标记为 `cad`。生成的参数与自然语言解析结果同构，经同一网格、求解、后处理与校核链路求解。几何类型由包围盒按薄度与细长比推断，可能与用户意图不一致（如细长块体被推断为梁），后续由特征识别与载荷语义协同细化。

## LLM 接入

- 文本生成：`httpx` 直连 OpenAI 兼容 Chat Completions JSON 接口。
- 连接健康检查：执行最小 Chat Completions 调用。
- JSON 输出：LLM 后端优先使用 Chat Completions JSON mode，请求 4096 token 输出预算；当后端不支持 `response_format` 时重试普通 Chat Completions。
- LLM HTTP 调用只处理 JSON 字典响应，不引入 provider 对象序列化副作用。
- 本地前置校验：空 prompt 或缺少 `base_url`、`api_key`、`model` 时不进入 provider 调用。
- 默认配置：`orchestrator.use_llm_agents: false`，生产求解使用确定性 schema 与工具链闭环。远端 LLM 结构化抽取与审阅通过 CLI `--llm-agents`、SDK `use_llm_agents=True` 或配置项显式开启。
- 调用策略：Planner 和 Designer 的结构化输出保留默认 HTTP 超时和重试；非关键工程审阅使用短超时和单次尝试，远端慢响应不会长时间阻塞网格、求解、后处理和报告主链路。
- 缺参补齐与门禁：Planner 已记录必要字段缺失时，Designer 仍尝试 LLM 结构化补齐；本地 parser 和 LLM 均无法生成可执行参数时返回缺参诊断。
- 本地参数优先：能力 parser 生成验证通过的本地 `ModelParams` 时，Designer 不用 LLM 输出覆盖用户已解析参数。
- 模型编号契约：能力声明 `model_case_ids` 时，Designer 拒绝声明范围外的 `ModelParams.case_id`。

### 脱敏与公开摘要

- SDK/CLI JSON 摘要输出 trace 元数据、错误状态和 prompt/response 字符数，不输出原始 prompt 或 response；Markdown 报告展示执行链路摘要和可解析的 LLM 工程解释。
- 插件扩展字段和后处理标量中的嵌套 LLM trace 递归转换为公开摘要；Reporter 工程解释上下文在进入 LLM 前递归剥离 `*_llm_trace` 审计字段，`Path` 类型转换为字符串，保证公开 JSON 摘要可序列化。
- `SolverRunSummary.to_mapping()` 和 `PostProcessingSummary.to_mapping()` 导出同一类公开映射，供后处理、插件和脚本复用。
- 后续 Agent 的 advisory payload 对已有 LLM trace 执行同样的公开摘要转换，保留 `agent`、`used`、`error` 和字符数，不递归传递上游 prompt/response；部分 trace 映射使用显式布尔解析，避免 `"false"` 被解释为真。
- LLM HTTP 后端、Provider 和 Agent 异常消息进入连接检查、trace 与 `ErrorRecord` 前会脱敏 `api_key`、环境变量 `API_KEY`、Bearer token 和常见 provider token。
- SDK/CLI 公开摘要、Markdown 报告执行链路摘要和后续 advisory payload 中的 trace `error` 字段使用同一脱敏规则。
- 私密字段与本机外部程序路径：`.env` 注入，不进入 Git。

## 知识库

- 默认输入：`knowledge/sources` 下的公开 Markdown 种子文档。
- 可选输入：Markdown、TXT、JSON，可通过 `knowledge.raw_dir` 指向本地目录。
- 索引：本地 JSONL。
- 检索：中英文 token/ngram 切分、BM25、TF-IDF 余弦相似度、归一化融合。
- 脚本与 CLI：`scripts/build_knowledge.py`、`scripts/index_knowledge.py` 和 `knowledge build` 均按配置执行文档标准化和 JSONL 索引构建。
- 空源门禁：知识源目录不存在、无可标准化文档或无可索引文本块时直接失败，不生成空索引作为有效知识库。
- 索引校验：检索时校验 JSONL 行格式、对象类型、空索引状态以及 `doc_id/source/text` 必需字段和非空字段值。

知识库公开检索函数 `query_index()` 在入口处拒绝非有限 BM25/TF-IDF 融合权重。

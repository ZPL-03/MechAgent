# 求解器、网格与后处理

本文描述网格生成与质量门禁、CalculiX 适配器、`.frd` 后处理与解析参考公式。能力解析见 [能力与自然语言解析](capabilities.md)，求解摘要状态见 [架构与数据契约](architecture.md)。

## 网格生成与质量门禁

网格尺寸由 Designer 基于几何尺度自动给出：

- 梁：`seed_size = max(length / 100, 1.0)`。
- 板：`seed_size = max(min(length, width) / 40, 1.0)`。
- 实体块：`seed_size = max(min(length, width, height) / 2, 1.0)`。

启用 LLM Agent 时，MeshAgent 在调用网格器前把 `ModelParams`、当前网格设置和网格策略规则发送给 LLM，并解析 `seed_size`、`element_type` 和 `rationale`。`seed_size` 必须是有限正数，且位于当前结构化网格尺寸 `1/5` 至 `5` 倍范围内；`element_type` 必须与几何类型兼容。未通过校验的 LLM 网格策略只进入 `mesh_llm_trace.error`，不改变网格生成参数。

MeshAgent 要求成功网格结果提供 `mesh_file`，并要求 `MeshResult.quality` 中的数值均为有限数值。`MeshConfig.seed_size`、`MeshConfig.min_quality` 和 `SolverResult.wall_time` 在公共模型层拒绝非有限数值。运行配置模型同样拒绝非有限 `llm.temperature`、`mesher.min_quality`、`knowledge.bm25_weight` 和 `knowledge.tfidf_weight`。

配置项 `mesher.min_quality` 只应用于网格结果中的 `min_*` 质量指标；低于阈值的网格结果进入失败状态。`max_*` 等上界指标不使用最小质量阈值判定。工作流在 MeshAgent 阶段记录 `mesh_failed` 并停止该任务的求解。

默认网格器注册名为 `calculix-inp`。矩形板路径调用 Gmsh Python API 生成四边形壳网格；开孔薄板路径调用 Gmsh OCC 布尔建模生成圆孔、多圆孔或水平长圆槽孔壳网格，并按最小开孔特征使用更小网格尺度；梁路径生成 `structured_line` B31 结构化线网格；矩形实体块路径生成 `structured_hex` C3D8R 结构化六面体网格。四类路径统一输出 CalculiX 可消费的 `.inp` 网格片段，并在 `MeshResult.metadata` 写入 `source`、`format`、`element_type`、`node_count`、`element_count`、`opening_count` 以及开孔参数摘要。Gmsh 路径使用 `gmsh.model.mesh.getElementQualities(..., "minSICN")` 提取单元质量，写入 `MeshResult.quality.min_sicn` 和 `MeshResult.quality.mean_sicn`；`MeshResult.metadata.quality_source` 记录为 `gmsh_minSICN`。结构化梁和实体网格保持确定性质量指标。

## CalculiX 适配器

`CalculiXAdapter` 支持结构线弹性静力：

- 梁：B31 单元，根部 1 至 6 自由度约束；纯全局 Y 向端部集中力或全跨均布线载荷转换为节点力。
- 矩形板：S4 四节点壳路径；四边 `U3` 简支约束；纯全局 Z 向均布压力按单元面积转换为节点力。
- 开孔薄板：Gmsh 圆孔、多圆孔或长圆槽孔壳网格，支持 S3/S4 壳单元读取；外框 `U3` 简支约束，开孔边界保持自由；纯全局 Z 向均布压力按三角形或四边形单元面积转换为节点力。
- 矩形实体块：C3D8R 实体单元；根部 `U1/U2/U3` 固定；纯全局 X 向端面压力或端面合力转换为端面节点力。

适配器在 `.inp` 生成前校验 `ModelParams` 的材料类型、几何非线性开关、单元类型、边界条件、载荷区域和载荷方向。不属于上述验证物理子域的输入以 `SolverError` 结束，不生成与请求不一致的求解文件。CalculiX 的 `ccx` 进程调用经作业执行器抽象 `AbstractJobExecutor` 执行：适配器构造 `JobSpec` 并由执行器运行，默认使用同步本地执行器 `LocalCommandExecutor`，可注入远程/HPC/容器执行器在不改求解逻辑的前提下切换执行后端（见 [架构与数据契约](architecture.md)）。`solver.calculix.num_cpus` 通过 `OMP_NUM_THREADS` 传入 CalculiX 子进程；`solver.calculix.timeout` 传入子进程超时控制。默认 `num_cpus=1` 用于小型标准验证和自然语言验收案例的确定性执行；工程任务可在配置中提高该值。标准验证和生产求解共用这两个配置。网格文件和求解输入文件使用 core 层统一的文件名规范化函数，`ModelParams.case_id` 不会作为路径片段写出到工作目录外。

## `.frd` 后处理

`.frd` 解析输出：

- `tip_deflection_mm`
- `center_deflection_mm`
- `axial_displacement_mm`
- `max_displacement_mm`
- `max_abs_u1_mm`
- `max_abs_u2_mm`
- `max_abs_u3_mm`
- `max_stress_mpa`

实体轴向验证和生产评价优先使用 `axial_displacement_mm`。该字段按输入几何端面位置提取；缺失时兼容回退到 `max_abs_u1_mm`。

## 解析参考公式

悬臂梁端部集中力：

```text
delta = P L^3 / (3 E I)
I = b h^3 / 12
```

悬臂梁全跨均布线载荷：

```text
delta = q L^4 / (8 E I)
I = b h^3 / 12
```

四边简支矩形薄板均布压力使用 Navier 双重级数：

```text
D = E h^3 / (12 (1 - nu^2))
w(a/2,b/2) = sum_m sum_n q_mn / [D pi^4 ((m/a)^2 + (n/b)^2)^2]
```

验收计算截断阶数为 151。

矩形实体块端面轴向载荷：

```text
delta = F L / (A E)
A = b h
```

标准验证数值见 [验证与质量门禁](validation.md)。

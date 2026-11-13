# 求解器、网格与后处理

本文描述网格生成与质量门禁、CalculiX 适配器、`.frd` 后处理与解析参考公式。能力解析见 [能力与自然语言解析](capabilities.md)，几何建模和 CAD 网格边界见 [几何建模与网格边界](geometry_ai.md)，求解摘要状态见 [架构与数据契约](architecture.md)。

## 网格生成与质量门禁

网格尺寸由 Designer 基于几何尺度自动给出：

- 梁：`seed_size = max(length / 100, 1.0)`。
- 板：`seed_size = max(min(length, width) / 40, 1.0)`。
- 实体块：`seed_size = max(min(length, width, height) / 2, 1.0)`。

`MeshSpec.local_size_fields` 可为 CAD 拓扑区域声明局部尺寸场。每项包含 `region`、`size` 和
`distance`：`size` 是区域附近的目标单元尺寸，`distance` 是向全局 `seed_size` 过渡的最大距离，
单位均为 mm。`size` 必须为正数且不大于全局尺寸，`distance` 不得小于 `size`，区域名称在同一
案例中不能重复。案例的单位转换同时缩放这三个长度值。

`gmsh-cad-inp` 仅接受已映射且置信度不低于 0.80 的 CAD 面或边区域。适配器在三维网格生成前
将区域的稳定拓扑 ID解析为当前 Gmsh 实体，创建 Distance/Threshold 尺寸场，并将多个区域场
按最小尺寸合并。区域缺失、拓扑 ID 不存在、绑定置信度不足、区域含三维实体或拓扑摘要不一致
都会阻断网格生成并返回具体诊断；不会使用包围盒或其他未绑定区域替代。成功结果的
`metadata.local_size_fields` 和 `MeshResult.provenance.local_size_fields` 记录实际绑定的拓扑 ID、
维度、目标尺寸和影响距离；来源摘要还校验区域别名、拓扑 ID、拓扑维度和全局尺寸之间的一致性。
该能力当前只覆盖 `gmsh-cad-inp` 的三维 C3D4 网格，参数化梁、板和
实体网格仍使用全局尺寸及其既有特征尺寸规则。

`calculix-inp` 收到局部尺寸场时直接失败并返回适配器诊断，避免把未执行的局部约束当作全局
尺寸结果继续使用。

启用 LLM Agent 时，MeshAgent 在调用网格器前把 `ModelParams`、当前网格设置和网格策略规则发送给 LLM，并解析 `seed_size`、`element_type` 和 `rationale`。`seed_size` 必须是有限正数，且位于当前结构化网格尺寸 `1/5` 至 `5` 倍范围内；`element_type` 必须与几何类型兼容。未通过校验的 LLM 网格策略只进入 `mesh_llm_trace.error`，不改变网格生成参数。

MeshAgent 要求成功网格结果提供存在的 `mesh_file`，并在结果元数据中记录该文件的 `mesh_sha256`；同时生成版本化 `MeshResult.provenance`，记录案例、几何、网格器、尺寸、单元类型、质量门禁、区域名称、实体数量、零件 ID、连接语义和可用 CAD 摘要。多实体检查网格的连接语义为 `unconnected_parts`，不表示存在接触或连接关系。SolverAgent 在启动求解器前重新读取文件并校验摘要，并将该来源对象放入求解摘要。文件缺失、摘要缺失或摘要不一致会阻断求解。`MeshResult.quality` 中的数值必须为有限数值。`MeshConfig.seed_size`、`MeshConfig.min_quality` 和 `SolverResult.wall_time` 在公共模型层拒绝非有限数值。运行配置模型同样拒绝非有限 `llm.temperature`、`mesher.min_quality`、`knowledge.bm25_weight` 和 `knowledge.tfidf_weight`。

配置项 `mesher.min_quality` 只应用于网格结果中的 `min_*` 质量指标；低于阈值的网格结果进入失败状态。`max_*` 等上界指标不使用最小质量阈值判定。工作流在 MeshAgent 阶段记录 `mesh_failed` 并停止该任务的求解。

参数化网格器注册名为 `calculix-inp`。矩形板路径调用 Gmsh Python API 生成四边形壳网格；开孔薄板路径调用 Gmsh OCC 布尔建模生成圆孔、多圆孔或水平长圆槽孔壳网格，并按最小开孔特征使用更小网格尺度；梁路径生成 `structured_line` B31 结构化线网格；矩形实体块路径生成 `structured_hex` C3D8R 结构化六面体网格。具备受控 CAD 源摘要的三维实体使用 `gmsh-cad-inp`，通过 Gmsh OpenCASCADE 直接导入 STEP/IGES/BREP，生成一阶 C3D4 四面体网格，并将当前摘要内可复现的拓扑面/边转换为节点集合；区域无法唯一映射时直接失败。各路径统一输出 CalculiX 可消费的 `.inp` 网格片段，并在 `MeshResult.metadata` 写入与该路径相关的 `source`、`format`、`element_type`、`node_count`、`element_count` 和 `quality_metric`；开孔薄板路径额外写入 `opening_count` 与开孔参数摘要。Gmsh 路径使用 `gmsh.model.mesh.getElementQualities(..., "minSICN")` 提取单元质量，写入 `MeshResult.quality.min_sicn` 和 `MeshResult.quality.mean_sicn`，并将 `quality_metric` 设为 `min_sicn`；`MeshResult.metadata.quality_source` 记录为 `gmsh_minSICN`。结构化梁使用 `min_jacobian`，结构化实体使用 `min_edge_ratio` 和 `max_aspect_ratio`。MeshAgent 在 `metadata.quality_gate` 记录阈值、参与判定的 `min_*` 指标及 `passed`/`failed` 状态；上界指标只作为质量结果保留，不参与 `min_quality` 判定。

## CalculiX 适配器

`CalculiXAdapter` 支持结构线弹性静力：

- 梁：B31 单元，根部 1 至 6 自由度约束；纯全局 Y 向端部集中力或全跨均布线载荷转换为节点力。
- 矩形板：S4 四节点壳路径；四边 `U3` 简支约束；纯全局 Z 向均布压力按单元面积转换为节点力。
- 开孔薄板：Gmsh 圆孔、多圆孔或长圆槽孔壳网格，支持 S3/S4 壳单元读取；外框 `U3` 简支约束，开孔边界保持自由；纯全局 Z 向均布压力按三角形或四边形单元面积转换为节点力。
- 矩形实体块：C3D8R 实体单元；根部 `U1/U2/U3` 固定；纯全局 X 向端面压力或端面合力转换为端面节点力。

适配器在 `.inp` 生成前校验 `ModelParams` 的材料类型、几何非线性开关、单元类型、边界条件、载荷区域和载荷方向。不属于上述验证物理子域的输入以 `SolverError` 结束，不生成与请求不一致的求解文件。CalculiX 的 `ccx` 进程调用经作业执行器抽象 `AbstractJobExecutor` 执行：适配器构造 `JobSpec` 并由执行器运行，默认使用同步本地执行器 `LocalCommandExecutor`，可注入远程/HPC/容器执行器在不改求解逻辑的前提下切换执行后端（见 [架构与数据契约](architecture.md)）。`solver.calculix.num_cpus` 通过 `OMP_NUM_THREADS` 传入 CalculiX 子进程；`solver.calculix.timeout` 传入子进程超时控制。默认 `num_cpus=1` 用于小型标准验证和自然语言验收案例的确定性执行；工程任务可在配置中提高该值。标准验证和生产求解共用这两个配置。网格文件和求解输入文件使用 core 层统一的文件名规范化函数，`ModelParams.case_id` 不会作为路径片段写出到工作目录外。

`CalculiXAdapter.run_case()` 支持 `SimulationCase` 的多个线性静力 `LoadStepSpec`。每个步骤的载荷比例、增量和输出间隔进入同一个输入文件。FRD 解析按分析步编号和字段类别内的输出顺序合并 `field_history`，字段缺失会保留在对应帧而不会借用相邻分析步的值；统一结果选择器据此生成 `requested_fields`、逐步 `step_results` 和兼容别名 `result_steps`，必需字段缺失时作业失败。旧 `run(ModelParams)` 入口仍保持单步兼容语义。

`.frd` 后处理请求应力、应变、体积、反力和能量输出；CalculiX 的 `TOSTRAIN` 记录归一为 `strain`，实体输入网格按节点坐标重建原始 `volume`，`ENER` 同时保留原始 `energy` 字段和单位为 `N/mm^2` 的 `strain_energy_density` 别名。实体体积重建只覆盖 C3D8/C3D4 网格；梁、壳和无法识别的单元不会生成原始体积字段。结果解析同时保留网格节点、单元连接和单元质心；统一结果层可根据梁截面尺寸和单元轴向长度生成带明确限制的 `mapped_fields.volume`。选定字段、单元映射字段和统一语义字段保留位置、单位、来源、推导和映射方式；`mapped_fields` 还记录 `source_count`、`target_count`、`mapped_count`、`coverage`、`complete`、`source_location` 和具体映射方法。多步结果从 `field_history` 生成 `mapped_step_fields`，每个分析步保留逐帧映射结果和最后一帧的字段索引。`ResultFieldSpec.unit` 非空时必须与后端单位完全一致，不能用请求标签掩盖单位冲突。后端位置不同的原始场只能通过统一单元质心字段或统一语义摘要比较。

每个成功适配器结果还保留 `input_sha256` 和 `artifacts`。`artifacts` 只记录求解工作目录内文件的相对路径、大小和 SHA-256，供运行清单、备份和跨后端证据定位同一份输入或输出；该完整性记录不替代参考解、网格收敛或工程适用性校核。

## 反力平衡校核

结构静力评价器在求解结果中写入 `equilibrium`。集中力、梁全跨线载荷以及参数化板和实体的已知受载面压力可以计算外加载荷合力，并与支撑边界的 `reaction_force` 合力比较。报告保留载荷类型、外加载荷合力、支撑反力合力、三方向残差、最大绝对误差、最大相对误差、阈值和状态。`passed` 表示误差满足绝对或相对阈值；`failed` 表示结果已提取但误差超限；`unverified` 表示缺少 `success=true`、节点坐标、支撑反力、受载面积或当前契约不支持的载荷类型。反力平衡状态独立于主结果参考值验收，不能用求解进程成功或主结果误差替代。

CalculiX 的 `FORC` 原始记录包含节点外载荷和支撑作用。适配器对自身生成的 `*CLOAD` 按输入节点与 FRD 节点坐标对应并扣除，统一结果中的 `reaction_force` 表示支撑反力；壳单元中面节点展开到两侧时按对应 FRD 节点平均分配。外部输入文件未提供可恢复的 `*CLOAD` 分配时保留原始 `FORC` 字段，不声明已完成的纯支撑反力转换。

## Abaqus/Standard 适配器

`AbaqusAdapter` 已通过 `core.factory` 注册名 `abaqus`。适配器覆盖当前梁、矩形板和矩形实体结构静力输入模板，使用 Abaqus 原生 `*OUTPUT`、`*NODE OUTPUT`、`*ELEMENT OUTPUT` 和历史能量输出请求结果场；`run_case()` 支持线性静力多步，调用 `abaqus python` 读取 ODB 的所有输出帧，并将 `U`、`S`、`E`、`EVOL`、`SENER`、`RF` 和 `ENER` 归一到统一结果字段名称。积分点字段使用元素标签、积分点和截面点组成稳定键，避免不同积分点互相覆盖；节点坐标、单元连接、单元质心、逐帧场量和 `ALLIE/ALLSE/ALLWK/ALLPD` 历史能量同时保留。结果字段选择器随后按 `ResultFieldSpec` 计算分量、位移幅值和应力不变量；必需字段缺失、单位或位置不一致以及字段值为空时执行失败，统一结果层根据单元连接和坐标生成 `mapped_fields`。

适配器检查 launcher、进程返回状态、ODB 文件、锁文件和 ODB 提取脚本结果。`SolverConfig` 或
`solver.abaqus` 配置可提供本地并发槽位和只读许可证探针；探针失败或槽位等待超时会明确返回
失败状态；该任务保持在 Abaqus 适配器路径。Abaqus 许可证、版本和工作目录由本机安装负责；便携 CI 不执行商业工具。`scripts/run_abaqus_smoke.py` 验证独立工具链，适配器真实多步运行证据由平台路径单独记录。
`scripts/run_abaqus_multistep.py` 在同一 `SimulationCase` 上运行两个线性静力步，并在
`manifest.json` 中验证步数、帧数、节点数、积分点场、能量场和逐步结果字段；该清单只有所有
检查通过时才标记 `passed`。

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

## Abaqus 独立工具检查

`scripts/run_abaqus_smoke.py` 调用 `scripts/abaqus/linear_static_smoke.py.tmpl`，在唯一运行目录执行 Abaqus/CAE 建模、C3D8R 网格、Abaqus/Standard 静力与 ODB 提取。模型为 100 × 10 × 10 mm 实体，E=210000 MPa、nu=0.3、端面拉应力 1 MPa；约束消除刚体运动并允许泊松收缩。

位移参考为 `pL/E=0.000476190476 mm`，应力参考为 1 MPa。检查要求体积 10000 mm³、正节点/单元数、求解器 `.sta` 明确成功、ODB 解锁且位移与应力相对误差均不大于 1%。成功判定同时记录 CAE `job.status` 与求解器完成来源，并检查启动器退出码。

结果保存为运行目录中的 `result.json`，并保留 INP、ODB 与日志。该清单覆盖独立 Abaqus 工具链；平台适配器验收和跨工具工程比较分别记录。各适配器结果保留 `case_digest`、`mesh_digest`、单位、坐标系、原始字段、逐步 `steps` 与逐帧场；比较器拒绝案例指纹不一致或缺失的结果。`mechagent.core.compare.compare_backend_results()` 与 `scripts/compare_backends.py` 支持 `requested_fields`、原始 `fields`、统一单元质心 `mapped_fields` 和统一语义 `comparison_fields`；`compare_backend_step_fields()` 对多步 `mapped_step_fields` 按分析步和帧逐一比较，缺步或缺帧不允许整体通过。跨工具比较还必须保存同一案例摘要、单位、边界、网格、单元、求解控制和各工具运行证据。`element` 和 `integration_point` 原始场只有在 `mesh_digest` 一致且字段键对应时才按键比较，位置或离散方式不一致时标记为 `unverified`；统一单元质心字段表示明确的单元连接/坐标聚合，统一语义字段用于跨工具物理量门禁。Abaqus 适配器可通过 `solver.abaqus.license_queue_path` 使用共享 SQLite 租约队列，在同一可用文件系统上的多个 Python 进程之间限制许可证槽位；该队列与 FLEXnet 或集群许可证服务分别管理。商业工具的安装与许可由使用者维护。

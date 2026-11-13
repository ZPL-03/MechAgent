# 脚本职责目录

`scripts/` 保存可复现的环境检查、证据生成、知识库构建、运维和发布辅助命令。`scripts/registry.json` 是根目录 Python 脚本的机器可读注册表；本页说明职责边界和清理规则。`scripts/abaqus/linear_static_smoke.py.tmpl` 是由独立 smoke 脚本读取的输入模板。脚本的发布门禁由工作流、测试和文档共同决定。脚本输出目录必须使用新的空目录，正式运行证据保存在独立目录。

## 职责矩阵

| 类别 | 脚本 | 职责和边界 |
| --- | --- | --- |
| 环境 | `check_env.py` | 检查解释器、依赖、Gmsh、CalculiX/Abaqus 配置；真实求解状态由运行证据记录 |
| 环境 | `audit_python_dependencies.py` | 生成 Python 运行时依赖审计；许可证状态由独立审计记录 |
| 知识库 | `build_knowledge.py` | 将原始公开知识源标准化为外部文档产物 |
| 知识库 | `index_knowledge.py` | 将标准化文档写成 JSONL 检索索引 |
| 标准案例 | `natural_language_cases.py` | 提供自然语言案例数据和测试导入，不单独执行求解 |
| 标准案例 | `run_natural_language_cases.py` | 在新的空目录运行自然语言案例，检查解析、求解和参考验收并写入结果清单 |
| 标准案例 | `run_benchmarks.py` | 在独立证据目录运行 core 标准验证和参考公式检查并写入结果清单 |
| LLM | `run_llm_smoke.py` | 在显式配置 LLM 后验证结构化 trace；数值正确性由求解和参考验收记录 |
| 网格 | `run_mesh_convergence.py` | 使用真实 CalculiX 运行多尺寸网格并评估收敛；输出是独立证据 |
| CAD | `run_cad_topology_case.py` | 生成或导入 CAD，检查拓扑、区域、C3D4 网格和 CalculiX 链路 |
| 求解器 | `run_abaqus_smoke.py` | 独立 Abaqus 工具基准；适配器验收单独记录 |
| 求解器 | `run_abaqus_multistep.py` | 验证同一 `SimulationCase` 的 Abaqus 多步输入和 ODB 字段 |
| 求解器 | `run_calculix_multistep.py` | 验证 CalculiX 多步输入和 FRD 位移、应力、应变、体积、反力、能量字段 |
| 跨工具比较 | `compare_backends.py` | 读取已有 JSON 结果并比较指定字段，不执行求解 |
| 跨工具比较 | `run_backend_comparison.py` | 运行选定适配器、保存结果并生成比较清单 |
| Studio | `studio_http_smoke.py` | 验证 Studio HTTP API、队列和公开摘要 |
| 运维 | `backup_studio.py` | 备份 Studio SQLite 与对象清单 |
| 运维 | `restore_studio.py` | 校验备份并恢复到明确目标目录 |
| 运维 | `drill_studio_recovery.py` | 在临时目标执行备份/恢复演练，检查完整性和产物一致性 |
| 运维 | `prune_artifacts.py` | 按对象存储引用和年龄清理孤立对象；需要显式应用参数 |
| 清理 | `clean_artifacts.py` | 清理可再生成缓存和构建产物；`--include-runs` 才涉及运行证据 |
| 对象存储 | `check_s3_storage.py` | 对配置的 S3 兼容存储执行写入、读取、列举、删除和可选生命周期探针；可输出脱敏证据清单；没有外部服务时不属于便携 CI |
| 发布 | `build_release_manifest.py` | 生成版本、文件摘要和发布清单 |
| 发布 | `generate_sbom.py` | 生成 SBOM |
| 发布 | `check_wheel_install.py` | 在隔离目标中安装当前 wheel 并检查公开包导入 |
| 发布 | `check_release_tag.py` | 校验 tag 与版本号一致 |
| 发布 | `sign_release.py` | 在受控 CI 中使用密钥或 OIDC keyless 签名；密钥只存在于受控运行时 |
| 发布 | `verify_release.py` | 独立校验清单、摘要、签名或 attestation |
| 许可证 | `audit_abaqus_license.py` | 记录本机 Abaqus/FlexNet 只读审计结果；集群许可证服务容量单独验收 |

## 容易误删的相似脚本

- `natural_language_cases.py` 与 `run_natural_language_cases.py` 是数据定义和运行器两层，前者被测试和运行器导入。
- `compare_backends.py` 与 `run_backend_comparison.py` 分别负责结果比较和运行后比较；命令职责保持分离。
- `build_knowledge.py` 与 `index_knowledge.py` 是标准化和索引两个可独立失败的阶段；CI 需要分别暴露失败。
- `run_abaqus_smoke.py` 与 `run_abaqus_multistep.py` 分别覆盖独立工具基准和适配器多步字段，验收记录分别保存。
- `run_abaqus_multistep.py` 与 `run_calculix_multistep.py` 分别覆盖 ODB 和 FRD 的多步字段提取；两种后端的原生场位置由各自案例契约明确记录。
- `backup_studio.py`、`restore_studio.py` 和 `drill_studio_recovery.py` 分别执行备份、恢复和演练，运维流程按对应阶段执行。
- `prune_artifacts.py` 面向对象存储引用，`clean_artifacts.py` 面向仓库缓存和运行目录；两者的保护规则不同。

## 清理规则

删除脚本前必须同时满足：没有 CLI、CI、测试、文档或包入口引用；职责没有被另一个命令完整覆盖；没有正式证据目录依赖；删除后不需要改变公开验证流程。未满足条件的脚本保留，并通过本目录说明职责。

脚本应做到：

- 所有路径通过参数或项目配置得到，不读取密钥并不打印密钥；
- 默认拒绝覆盖已有证据目录；
- 失败时返回非零退出码并保存诊断；
- 输出清单记录版本、输入摘要、工具版本和产物哈希；
- 真实求解、商业许可证、外部对象存储和签名工具明确标记为环境相关验证。

## 与 Python API 的关系

脚本可以调用 `mechagent.core` 和 `mechagent` 的公开契约；测试编号分支、硬编码参考结果和吞异常均不属于有效验证。稳定的用户功能应进入 SDK/CLI 或适配器；一次性研究脚本只有在具备可复现输入输出后才进入发布门禁。

# 验证与质量门禁

本文记录标准验证算例、独立自然语言测试案例、质量门禁命令、测试覆盖范围与清理策略。

## 标准验证

标准验证由独立命令执行：

```powershell
python scripts/run_benchmarks.py --work-dir mechagent_output/benchmarks/RUN-YYYYMMDD
```

| 编号 | 物理量 | CalculiX | 解析参考 | 相对误差 | 阈值 | 状态 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| TC-01 | `tip_deflection` | 14.896 mm | 14.880952 mm | 0.101120% | 1% | 通过 |
| TC-02 | `center_deflection` | 0.155959 mm | 0.154233 mm | 1.118913% | 2% | 通过 |
| TC-03 | `axial_displacement` | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% | 通过 |
| TC-04 | `tip_deflection` | 5.58805 mm | 5.580357 mm | 0.137856% | 2% | 通过 |
| TC-05 | `axial_displacement` | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% | 通过 |

解析参考公式见 [求解器、网格与后处理](solver_mesh.md)。

本机标准算例的当前运行结果保存在 `mechagent_output/benchmark_results.json`，求解中间产物位于
`mechagent_output/benchmarks/`，对应清单为 `mechagent_output/benchmarks/manifest.json`。Abaqus
多步、双后端和 CAD 拓扑证据分别使用各自目录下的 `manifest.json`。这些清单都使用相对路径、文件大小
和 SHA-256；统一校验命令如下：

```powershell
python -m mechagent.cli verify-evidence mechagent_output/benchmarks/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/abaqus-multistep-evidence/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/backend-comparison-current/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/cad-topology-evidence/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/cad-hole-topology-evidence/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/studio-recovery-evidence/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/mesh-convergence-tc01/manifest.json
```

校验通过只证明文件完整性和清单一致性，不证明物理结果正确；物理结论仍以本节的参考误差、字段检查和适配器边界为准。

## 自然语言与 LLM

案例定义位于 `scripts/natural_language_cases.py`，不进入生产 Planner。`scripts/run_natural_language_cases.py` 校验能力、几何、载荷、求解状态和参考误差：SC-01 至 SC-20 有参考验收；SC-21 至 SC-28 覆盖中心孔、偏心孔、多孔和槽孔，仅确认真实求解成功，状态为 `unverified`。

`scripts/run_llm_smoke.py` 检查结构化补参、Agent 调用记录、真实梁求解及报告中的工程解释。远端模型响应和可用性具有时效性，该检查需要本机凭据，便携 CI 不执行。

## Abaqus 独立工具检查

```powershell
python scripts/run_abaqus_smoke.py --abaqus D:/Abaqus2023/Commands/abaqus.bat
```

模型、约束、字段与验收条件见[求解器与网格](solver_mesh.md)。脚本在独立目录保留 CAE 日志、INP、ODB 和结果 JSON，参考值由外层固定模型核验。

Abaqus 2023 本机检查获得 189 个节点、80 个单元，位移 0.000476190471 mm，相对误差约 1.071×10⁻⁸，平均 S11=1 MPa。完成判定使用 STA 成功标记、锁文件释放和有效 ODB 字段；CAE 的 `job.status` 在该环境返回 `None`。这项证据不代表 Abaqus 平台适配器，也不构成不同边界模型之间的求解器对比。外层超时返回失败；启动器可能派生子进程，应核实本机作业状态后清理目录。

## 质量门禁

输入契约门禁同时检查 `SimulationCase` 的版本、单位、坐标、区域和来源字段，检查
`SimulationCase.execution_readiness()` 对六类字段来源和区域置信度的执行阻断，检查
`ModelParams` 与案例契约之间的兼容转换，以及未知未来 schema 的拒绝行为。运行层门禁
检查 v1 至 v7 数据库迁移、迁移记录、旧作业读取、组织字段和未来数据库版本拒绝；API 门禁检查 `/api/v1`
路由与旧 `/api` 兼容入口的弃用响应头；指标门禁检查 `/api/v1/metrics` 的项目范围、admin
全局范围、脱敏输出、数据库重启后的统计一致性以及结果大小和证据清单完整性计数。

CAD 区域门禁检查源文件摘要、稳定拓扑实体和六向区域候选是否随 `GeometryCandidate` 进入
`ModelParams.metadata.cad_geometry`；案例提升只接受唯一、已映射且置信度不低于 0.80 的
面/边拓扑 ID。`ambiguous`、`unresolved` 或缺少拓扑 ID 的区域必须生成 `unknown` 区域并使
`SimulationCase.execution_ready` 为 `False`。该门禁验证区域语义传递和失败行为，不替代
直接 CAD 网格、网格集合映射、网格质量或收敛验收。

实体 CAD 直接网格的本机证据使用以下命令生成。两个清单均要求源文件摘要、拓扑区域节点集合、
C3D4 单元、最小 `min_sicn`、CalculiX 结果和位移、应力、反力、能量字段全部有效；带孔案例还
验证了圆柱内壁和端面存在于同一直接导入实体中。

```powershell
python scripts/run_cad_topology_case.py --generate-box --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe --output-dir mechagent_output/cad-topology-evidence
python scripts/run_cad_topology_case.py --generate-hole-box --seed-size 8 --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe --output-dir mechagent_output/cad-hole-topology-evidence
```

网格独立性使用同一案例、递减 seed size 和同一求解器重复运行；收敛状态同时检查终点相邻网格变化和解析参考误差。当前 TC-01 的四级真实运行证据为 `mechagent_output/mesh-convergence-tc01/manifest.json`，seed size 为 40、20、10、5 mm，终点节点/单元数为 201/200，终点相邻网格相对变化为 2.014e-5，解析参考相对误差为 0.1031%，清单状态为 `passed`。该证据只覆盖参数化 B31 梁；CAD 实体、多区域映射、其他单元族和自动网格质量统一模型仍需独立验收。

```powershell
python scripts/run_mesh_convergence.py `
  --case-id TC-01 `
  --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe `
  --output-dir mechagent_output/mesh-convergence-YYYYMMDD
```

输出目录必须为空；脚本拒绝覆盖既有证据。`convergence.json` 的 `status=passed` 且清单校验退出码为 0，才算该案例收敛门禁通过。只有网格结果稳定而没有参考解时，状态为 `unverified`，不替代工程验收。

以下命令记录本机维护者完整验证所用解释器。公开用户和 CI 在激活独立 Python 环境后使用等价 `python` 命令执行同一组门禁。

```powershell
python -m mechagent.cli doctor
python scripts/check_env.py
npm --prefix apps/mechagent-studio ci --no-audit --no-fund
npm --prefix apps/mechagent-studio test
npm --prefix apps/mechagent-studio run build
npm --prefix apps/mechagent-studio audit --omit=dev --audit-level=high
python -m ruff format --check packages tests scripts
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
python scripts/generate_sbom.py --output dist/mechagent-sbom.spdx.json
python scripts/build_release_manifest.py --output dist/mechagent-release-manifest.json
# 只有发布环境已配置 cosign 和签名密钥时执行；命令会立即验证签名
python scripts/sign_release.py --manifest dist/mechagent-release-manifest.json --signature dist/mechagent-release-manifest.sig --key path/to/cosign.key
# GitHub OIDC keyless 模式
python scripts/sign_release.py --manifest dist/mechagent-release-manifest.json --bundle dist/mechagent-release-manifest.sigstore.json --certificate-identity "https://github.com/ORG/REPO/.github/workflows/release.yml@refs/tags/vX.Y.Z"
# 两个后端结果均来自同一 SimulationCase 且请求字段一致时执行
python scripts/compare_backends.py --left calculix-result.json --right abaqus-result.json --left-backend calculix --right-backend abaqus --output dist/backend-comparison.json
# 在本机真实运行同一案例并保存输入摘要、两个后端结果和比较清单
python scripts/run_backend_comparison.py --case-id TC-01 --case-id TC-03 --case-id TC-04 --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe --abaqus D:/Abaqus2023/Commands/abaqus.bat --relative 0.03 --absolute 0.005 --output-dir mechagent_output/backend-comparison
# 在同一 SimulationCase 上验证 Abaqus 多步执行、完整场量和逐步结果字段
python scripts/run_abaqus_multistep.py --abaqus D:/Abaqus2023/Commands/abaqus.bat --output-dir mechagent_output/abaqus-multistep
python scripts/check_wheel_install.py
python -m mkdocs build --strict
python scripts/clean_artifacts.py
```

## 验证范围与结果

测试覆盖数据契约、解析与单位、能力及工具工厂、编排和错误归因、LLM 响应与脱敏、SDK/CLI/Studio API、求解与后处理、知识索引、安装包、文档链接、主题和翻译。前端测试检查翻译插值、动态摘要、占位符一致性、标签键盘切换、作业状态和幂等提交；浏览器检查覆盖真实求解、场量、报告、历史、语言、主题和窄屏布局。

当前维护基线包括五个标准算例、28 个自然语言案例以及 15 项 LLM smoke 检查。标准算例均满足上表阈值；自然语言案例按是否有参考分别报告。Python 测试收集 591 项并全部通过，便携测试以最终门禁输出为准；测试环境有 2 条第三方弃用告警。前端 19 项测试、TypeScript/Vite 构建、生产依赖 `npm audit --omit=dev --audit-level=high`、Python 运行时外部依赖审计（`scripts/audit_python_dependencies.py --runtime-only`）、Ruff、mypy、隔离 wheel 安装、依赖一致性及严格文档构建通过。`scripts/audit_python_dependencies.py` 从两个包的 `pyproject.toml` 收集运行、开发和文档依赖，排除仓库内未发布到 PyPI 的本地发行包，再调用 `pip-audit`；网络或漏洞服务不可用时审计失败，不得解释为无漏洞。CI 使用 `scripts/check_env.py --profile portable` 和 `pytest -m "not real_solver"`，不替代本机真实求解验证。

`scripts/generate_sbom.py` 生成 SPDX 2.3 JSON，包含当前 Python 环境和 `package-lock.json` 中的依赖及 purl。依赖缺少许可证元数据时保留 `NOASSERTION`；该清单可作为发布前许可证审计输入，不替代许可证人工确认。

`scripts/build_release_manifest.py` 要求两个包各有一个当前版本的 wheel 和 sdist，并记录 Git 提交、UTC 时间、相对路径、大小、媒体类型、SHA-256 和构建上下文 provenance。provenance 包含源提交状态、Python/Node/平台版本和 `SOURCE_DATE_EPOCH`；它不提供签名、作者身份或可信构建服务证明。`scripts/sign_release.py` 支持受控密钥签名和 GitHub OIDC keyless 签名，签名后立即执行 `verify-blob`；发布清单必须声明干净 Git 源状态。缺少签名工具、密钥或 OIDC 证书身份时以失败结束。

`scripts/compare_backends.py` 比较两个结果中已经提取并声明的 `requested_fields`；优先按节点坐标建立一一对应，梁类一维网格按主轴位置聚合，无法对应时才使用字段摘要。对于位移幅值，梁类映射从原始位移向量按轴向位置平均重建中心线值，避免把截面转动造成的展开节点位移与中心线节点混比。输出对齐方式、缺失字段、绝对误差和相对误差。缺少可比较字段时状态为 `unverified`；字段或误差超出阈值时状态为 `failed`。该工具不证明两个输入模型、网格、边界和求解控制完全相同；`scripts/run_backend_comparison.py` 负责在同一 `SimulationCase` 上运行两个后端并保存案例摘要、结果和比较清单。

本机 Abaqus 2023 与 CalculiX 2.23 的真实适配器运行中，TC-01、TC-03、TC-04 的位移场逐点比较均通过。清单分别记录 `line-coordinate-centerline`、`node-coordinate` 和 `line-coordinate-centerline` 对齐方式；阈值为相对误差 3% 或绝对误差 0.005 mm，最大绝对误差分别为 0.003084 mm、0.0002334 mm 和 0.001560 mm。TC-03 的最大相对误差出现在接近零的节点，仍由绝对误差阈值约束。该证据验证三个案例的位移字段适配器闭环，不代表应力、反力、能量、其他单元、其他网格或其他物理域均可跨后端比较。

适配器测试覆盖许可证探针非零返回、许可证槽位等待超时和配置校验；这些是注入执行器的失败路径证据，不能替代 Abaqus 实际许可证不可用时的本机审计记录。

`scripts/run_abaqus_multistep.py` 的本机验证清单为 `mechagent_output/abaqus-multistep-evidence/manifest.json`，状态为 `passed`。该运行包含 2 个分析步、每步 2 个 ODB 帧、101 个节点、400 个积分点应力和应变值、100 个单元体积值、400 个应变能密度值、101 个节点反力值、全局 `ALLIE` 能量值以及 4 个逐帧结果记录。两个步骤均保留 `ALLIE`、`ALLSE`、`ALLWK` 和 `ALLPD` 历史能量；`requested_fields` 与 `step_results` 均包含位移、应力分量、应变、体积和能量字段。该证据验证 Abaqus 适配器的本机多步执行与场提取路径，不扩大到非线性、接触或其他单元族。

Studio 备份必须在调度器停止且没有活动作业时创建；清单覆盖数据库、作业目录和本地对象，恢复目标必须为空目录。

Studio 本机磁盘配额通过 `studio.max_storage_bytes` 配置。配额统计数据库父目录及本地 `artifact_root` 内的普通文件，提交前和成功结果写入后检查；超额提交返回 HTTP 507，超额结果记录 `storage_quota_exceeded`，不保留公开结果引用。`null` 表示不启用配额，S3 远端对象不计入本机目录用量。`tests/core/test_artifacts_backup.py` 覆盖提交前超额、结果写入后超额、外置本地对象目录和指标状态，`tests/core/test_studio.py` 覆盖 HTTP 507 映射。

```powershell
python scripts/backup_studio.py create --database mechagent_output/.studio/jobs.sqlite3 --destination mechagent_output/studio-backup
python scripts/restore_studio.py --backup mechagent_output/studio-backup --destination mechagent_output/studio-restore
python scripts/restore_studio.py --backup mechagent_output/studio-backup --destination mechagent_output/studio-restore --verify-only
```

灾难恢复演练使用独立的空 workspace，不覆盖既有备份或恢复目录。脚本记录源数据库和恢复数据库的完整性、作业数量、备份/恢复耗时、RPO 丢失作业数和总 RTO，并按显式目标判定退出码。RPO 基准是演练开始时可见的作业 ID；RTO 从演练开始计时到恢复数据库完成完整性检查。当前机器的实际 Studio 数据库演练证据为 `mechagent_output/studio-recovery-evidence/manifest.json`，源库含 1 个终态作业，恢复后作业 ID 丢失数为 0，RTO 约 0.089 秒，目标为 60 秒，清单状态为 `passed`。该证据只能证明指定机器、数据库、对象目录和目标阈值，不代表跨主机或 S3 部署已验收。

```powershell
python scripts/drill_studio_recovery.py `
  --database mechagent_output/.studio/jobs.sqlite3 `
  --workspace mechagent_output/recovery-drill-YYYYMMDD `
  --rto-target-seconds 60 `
  --rpo-max-lost-jobs 0
```

退出码为 0 且 `recovery-drill.json` 的 `status` 为 `passed` 才算该环境的演练通过。目标目录已存在、数据库含活动作业、备份清单不完整、作业 ID 丢失或 RTO 超限均保留失败状态；不要删除失败证据后重跑。

S3 兼容对象存储通过 `pip install "mechagent[s3]"` 和 `studio.artifact_backend=s3` 启用；
访问密钥由 boto3 标准凭据链提供。当前仓库包含客户端、摘要校验和恢复接口，远端桶权限、跨主机
备份保留和灾难恢复时间指标需要部署环境单独验收。

结果对象保留清理按数据库中的 `result_hash` 引用保护对象，并拒绝在存在未终态作业时执行。默认
只列出超过年龄阈值且无引用的对象；只有显式加入 `--apply` 才会删除。文件系统和 S3 使用同一
清理契约，S3 实际部署还需要对象前缀的 list 权限和删除权限：

```powershell
python scripts/prune_artifacts.py `
  --database mechagent_output/.studio/jobs.sqlite3 `
  --older-than-days 30
python scripts/prune_artifacts.py `
  --database mechagent_output/.studio/jobs.sqlite3 `
  --older-than-days 30 `
  --apply
```

使用 S3 时增加 `--backend s3 --bucket <bucket> --prefix <prefix>`；桶权限和跨主机保留周期仍需在
部署环境中执行真实验收。

Python 运行时依赖审计的 JSON 报告作为发布证据上传；报告缺失或漏洞服务不可用时，审计门禁失败，发布清单不会伪造审计结果。

## 作业故障与证据校验

`tests/core/test_runtime.py` 使用真实独立进程验证取消、心跳丢失、执行超时、进程身份与子进程终止，使用数据库并发验证幂等键、排队容量和领取上限。API 测试通过真实 worker 产生失败报告，并在应用生命周期重启后查询相同作业；不依靠同进程 monkeypatch 代替 worker 求解。SDK、结果文件和清单测试覆盖配置脱敏、源配置变化、文件缺失与内容篡改。

```powershell
python -m pytest tests/core/test_runtime.py tests/core/test_studio.py
python -m mechagent.cli verify-evidence path/to/run/manifest.json
```

文件校验通过返回退出码 0，不匹配返回 1；校验不替代工程参考比较。Windows Job Object 进程树终止具有本机与 Windows CI 行为测试；其他操作系统的进程边界仍需独立验收。运行层不提供求解器内部断点续算。

身份目录门禁使用组织管理员创建主体、验证项目和组织范围、轮换并停用 API key；数据库只保留
SHA-256 摘要，创建和轮换响应中的明文 key 不会写入主体表。跨组织管理员可读取和管理全部组织，
普通管理员只能操作所属组织。指标接口的最小检查使用已配置的 Bearer API key；不携带项目范围时只有 admin 可以读取本组织统计：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/v1/metrics?project_id=default -Headers @{Authorization="Bearer <key>"}
```

响应只包含作业状态计数、队列等待、执行时长、失败代码、结果对象大小、证据完整性计数、本机工作目录字节数与配额、数据库文件系统容量以及 worker 和可见子进程的 CPU 时间与峰值常驻内存，不包含请求正文、凭据、文件路径或原始 worker 诊断。资源或文件系统字段可能为空，表示边界内没有可读取的采样，不代表零消耗；本机工作目录配额和文件系统指标不等同于 S3 容量或集中 telemetry。

## 清理策略

```powershell
python scripts/clean_artifacts.py
python scripts/clean_artifacts.py --include-studio-runtime
python scripts/clean_artifacts.py --include-runs
```

默认清理 Python、pytest、Ruff、mypy、通用工具和 Vite 缓存、覆盖率文件、包构建目录、前端依赖、文档站点、浏览器临时输出、备份/恢复临时目录和可再生成知识索引，保留 `mechagent_output/` 与 FEM 运行文件。`--include-studio-runtime` 仅删除 `mechagent_output/.studio` 的本地 Studio 运行时数据库、作业目录和对象目录，保留正式证据目录；`--include-runs` 同时删除运行证据和 `.frd/.dat/.sta/.msg`。使用后两个选项前应将需要保留的报告、ODB、输入和发布包移出清理目标，并确认没有活动作业。脚本在任何删除前检查路径边界；Git 跟踪文件及其父目录受到保护，相关目录存在 `.lck` 或作业数据库存在排队/启动/运行/取消中任务时拒绝运行证据清理。

若默认清理后仍有一次性文件，使用以下命令列出未跟踪文件并逐项确认：

```powershell
git status --short --untracked-files=all
Get-ChildItem -Force -Recurse -File .tmp, .pytest_cache, .mypy_cache, .ruff_cache, apps/mechagent-studio/node_modules -ErrorAction SilentlyContinue
```

仅在确认其中不包含运行证据、正式 FEM、报告或用户文件后，再执行：

```powershell
python scripts/clean_artifacts.py --include-studio-runtime
python scripts/clean_artifacts.py --include-runs
```

脚本拒绝删除活动作业、求解锁、Git 跟踪文件和仓库外路径；拒绝项由维护者按上面的列举命令逐项处理，不通过扩大删除范围绕过保护。

`.env`、`knowledge/sources/` 和非空 `knowledge/raw/` 不属于清理目标。外部求解器和 Python 安装目录由维护者管理。

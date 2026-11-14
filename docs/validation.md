# 验证与质量门禁

本文记录标准验证算例、独立自然语言测试案例、质量门禁命令、测试覆盖范围与清理策略。

## 标准验证

标准验证由独立命令执行：

```powershell
python scripts/run_benchmarks.py --work-dir mechagent_output/benchmarks-YYYYMMDD/runs --output-dir mechagent_output/benchmarks-YYYYMMDD
```

| 编号 | 物理量 | CalculiX | 解析参考 | 相对误差 | 阈值 | 状态 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| TC-01 | `tip_deflection` | 14.896 mm | 14.880952 mm | 0.101120% | 1% | 通过 |
| TC-02 | `center_deflection` | 0.155959 mm | 0.154233 mm | 1.118913% | 2% | 通过 |
| TC-03 | `axial_displacement` | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% | 通过 |
| TC-04 | `tip_deflection` | 5.58805 mm | 5.580357 mm | 0.137856% | 2% | 通过 |
| TC-05 | `axial_displacement` | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% | 通过 |

解析参考公式见 [求解器、网格与后处理](solver_mesh.md)。

标准基准结果清单同时记录 `equilibrium`。该字段校核当前载荷契约能够计算的外加载荷合力与支撑反力合力；清单状态只有在主结果参考误差和反力平衡均为 `passed` 时才为 `passed`。缺少反力或区域证据时保留 `unverified`，不以求解进程成功代替平衡校核。

本机标准算例的当前运行结果保存在 `mechagent_output/benchmarks-current/benchmark_results.json`，求解中间产物位于
`mechagent_output/benchmarks-current/runs/`，对应清单为 `mechagent_output/benchmarks-current/manifest.json`。Abaqus
多步、跨工具比较和 CAD 拓扑证据分别使用各自目录下的 `manifest.json`。这些清单都使用相对路径、文件大小
和 SHA-256，并记录 `mechagent.evidence-provenance.v1` provenance。provenance 包含源提交与脏状态、
Python 运行时、已安装包版本、显式配置文件摘要和工具版本；未知值使用 `unknown` 或 `unavailable`。
版本探测不会启动求解器或商业工具，无法通过无副作用接口确认的版本保持 `unavailable`。
`verify-evidence` 同时校验 provenance 结构和文件摘要。统一校验命令如下：

```powershell
python -m mechagent.cli verify-evidence mechagent_output/benchmarks-current/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/abaqus-multistep-evidence/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/backend-comparison-current/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/cad-topology-evidence/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/cad-hole-topology-evidence/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/studio-recovery-evidence/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/mesh-convergence-tc01/manifest.json
python -m mechagent.cli verify-evidence mechagent_output/cad-mesh-convergence-local-size/manifest.json
```

校验通过只证明文件完整性、provenance 结构和清单一致性，不证明物理结果正确；物理结论仍以本节的参考误差、字段检查和适配器边界为准。对发布门禁使用 `python -m mechagent.cli verify-evidence --require-provenance path/to/manifest.json`，缺少 provenance 的清单直接失败。

## 自然语言与 LLM

案例定义位于 `scripts/natural_language_cases.py`，不进入生产 Planner。`scripts/run_natural_language_cases.py` 要求新的空输出目录，校验能力、几何、载荷、求解状态和参考误差，并写入 `results.json` 与 `manifest.json`；SC-01 至 SC-20 有参考验收；SC-21 至 SC-28 覆盖中心孔、偏心孔、多孔和槽孔，仅确认真实求解成功，状态为 `unverified`。任何单个案例异常都会保留错误字段并使整体命令返回非零状态。

`scripts/run_llm_smoke.py` 检查结构化补参、Agent 调用记录、真实梁求解及报告中的工程解释。远端模型响应和可用性具有时效性，该检查需要本机凭据，便携 CI 不执行。

## Abaqus 独立工具检查

```powershell
python scripts/run_abaqus_smoke.py --abaqus D:/Abaqus2023/Commands/abaqus.bat
```

模型、约束、字段与验收条件见[求解器与网格](solver_mesh.md)。脚本在独立目录保留 CAE 日志、INP、ODB 和结果 JSON，参考值由外层固定模型核验。

Abaqus 2023 本机检查获得 189 个节点、80 个单元，位移 0.000476190471 mm，相对误差约 1.071×10⁻⁸，平均 S11=1 MPa。完成判定使用 STA 成功标记、锁文件释放和有效 ODB 字段；CAE 的 `job.status` 在该环境返回 `None`。该清单记录独立 Abaqus 工具链的几何、网格、求解和 ODB 提取结果；平台适配器验收和不同边界模型的结果比较分别执行。外层超时返回失败；启动器可能派生子进程，应核实本机作业状态后清理目录。

许可证服务审计使用 Abaqus launcher 的只读 FlexNet 查询：

```powershell
python scripts/audit_abaqus_license.py --abaqus D:/Abaqus2023/Commands/abaqus.bat --output mechagent_output/abaqus-license-audit/manifest.json
```

清单只保存探针返回码、服务状态检查、耗时、输出长度和摘要哈希，不保存许可证服务器地址、许可证文件路径或原始诊断。本机清单 `mechagent_output/abaqus-license-audit/manifest.json` 的 `status` 为 `passed`，`process_succeeded`、`license_server_up`、`vendor_daemon_up` 和 `feature_usage_observed` 均为 `true`。该证据范围为本机 FlexNet 服务和 Abaqus vendor daemon；集群许可证容量、跨主机高可用和长期可用性属于部署验收项目。

## 质量门禁

### Studio 浏览器质量门禁

浏览器门禁使用生产构建和本地预览服务运行 Chromium。脚本通过固定的 `/api/v1` 公开响应验证界面契约，不把夹具数据作为求解证据。检查范围包括：

- 初始中文语言、跳转到工作台的首个键盘焦点和英文切换；
- 浅色、深色、跟随系统主题的循环和 `data-theme-preference` 持久化状态；
- 预检可执行态、通过、未验证和失败结果，以及报告和失败诊断的显示；
- 服务器作业列表读取、1440×1000 与 390×844 视口的横向溢出和单列布局。

本地运行需要已安装 Chromium 或可执行的系统浏览器：

```powershell
npm --prefix apps/mechagent-studio ci --no-audit --no-fund
npx --prefix apps/mechagent-studio playwright install chromium
npm --prefix apps/mechagent-studio run build
npm --prefix apps/mechagent-studio run test:browser
```

脚本在 `dist/studio-browser-evidence/` 写入 `manifest.json`、通过状态截图、失败状态截图和窄屏截图。清单的 `api_mode` 为 `deterministic-contract-fixture`；真实服务的 TCP、认证、权限、队列和结果路径由独立 `studio_http` CI 作业及真实求解门禁验证。CI 的 `studio_browser` 作业上传该目录作为短期检查证据，`studio_http` 作业上传独立 HTTP 清单。

输入契约门禁同时检查 `SimulationCase` 的版本、单位、坐标、区域和来源字段，检查
`SimulationCase.execution_readiness()` 对六类字段来源和区域置信度的执行阻断，检查
`ModelParams` 与案例契约之间的兼容转换，以及未知未来 schema 的拒绝行为。运行层门禁
检查 v1 至 v9 数据库迁移、迁移记录、旧作业读取、组织字段、worker 退出码和未来数据库版本拒绝；API 门禁检查 `/api/v1`
路由与旧 `/api` 兼容入口的弃用响应头；指标门禁检查 `/api/v1/metrics` 的项目范围、admin
全局范围、脱敏输出、数据库重启后的统计一致性以及结果大小和证据清单完整性计数。

CAD 区域门禁检查源文件摘要、当前导入摘要内可复现的拓扑实体、零件摘要、候选区域所属零件和六向区域候选是否随 `GeometryCandidate` 进入
`ModelParams.metadata.cad_geometry`；案例提升只接受唯一、已映射且置信度不低于 0.80 的
面/边拓扑 ID，并核对 ID 存在于同一份 `topology_entities` 且维度符合区域语义。`ambiguous`、
`unresolved`、缺少拓扑 ID 或引用未知拓扑 ID 的区域必须生成 `unknown` 区域并使
`SimulationCase.execution_ready` 为 `False`。案例投影到兼容模型时，`regions` 写入
`metadata.case_regions`；直接 CAD 网格对已声明的案例区域只使用该契约，未声明区域才允许由候选区域补充兼容别名，并在生成节点集合时拒绝未知、重复或面/边维度不匹配的拓扑 ID。
直接 CAD 网格适配器同样要求区域候选置信度至少为 0.80，并拒绝区域名称或别名冲突；多实体文件可以生成带零件归属的 C3D4 检查网格并保留 `unconnected_parts` 标记，求解器在没有装配、接触和连接契约时拒绝该模型。

实体 CAD 直接网格的本机证据使用以下命令生成。两个清单均要求源文件摘要、案例区域契约、拓扑区域节点集合、
C3D4 单元、最小 `min_sicn`、CalculiX 结果和位移、应力、反力、能量字段全部有效；带孔案例额外
检查贯穿圆孔的圆柱内壁拓扑面保留在直接导入实体中。

```powershell
python scripts/run_cad_topology_case.py --generate-box --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe --output-dir mechagent_output/cad-topology-evidence
python scripts/run_cad_topology_case.py --generate-hole-box --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe --output-dir mechagent_output/cad-hole-topology-evidence
```

未指定 `--seed-size` 时，实体块使用 15 mm，贯穿孔实体使用 8 mm；实际尺寸写入对应清单。清单中的 `CADArtifact`、`GeometryValidation`、`RegionBinding`、拓扑区域、C3D4 质量、求解状态和结果字段检查必须全部为 `true`。

网格独立性使用同一案例、递减 seed size 和同一求解器重复运行；收敛状态同时检查终点相邻网格变化和解析参考误差。当前 TC-01 的四级真实运行证据为 `mechagent_output/mesh-convergence-tc01/manifest.json`，seed size 为 40、20、10、5 mm，终点节点/单元数为 201/200，终点相邻网格相对变化为 2.014e-5，解析参考相对误差为 0.1031%，清单状态为 `passed`。质量指标名称和 `min_quality` 门禁已在参数化梁、板、开孔板、结构化实体和 CAD 直接网格路径中统一记录；该证据只覆盖参数化 B31 梁，CAD 实体、多区域映射、其他单元族的网格独立性以及跨网格器质量指标的工程等价性仍需独立验收。

CAD 实体网格独立性使用 `scripts/run_cad_mesh_convergence.py`。脚本在同一源文件上复用一次 CAD 几何分析，并要求每个 seed size 的运行保持源文件 SHA-256、拓扑摘要、区域契约摘要、局部尺寸场契约摘要、区域节点集合、C3D4 质量指标和 CalculiX 求解状态一致；每个运行目录保存完整结果场、网格和运行记录。没有参考值时，稳定的网格结果为 `unverified`，不能作为工程验收；提供与案例单位一致的解析或独立参考值及容差后，终点相邻网格变化、参考误差和质量门禁全部通过才为 `passed`。局部尺寸场契约摘要由区域名称、目标尺寸和影响距离确定，尺寸场变化会使收敛身份不一致。

```powershell
python scripts/run_cad_mesh_convergence.py `
  --generate-box `
  --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe `
  --output-dir mechagent_output/cad-mesh-convergence-box `
  --seed-size 20 --seed-size 10 --seed-size 5 `
  --reference 0.0047619048 --reference-tolerance 0.03

python scripts/run_cad_mesh_convergence.py `
  --generate-box `
  --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe `
  --output-dir mechagent_output/cad-mesh-convergence-local-size `
  --seed-size 20 --seed-size 10 `
  --local-size-field root:4:12 `
  --stabilization-tolerance 0.02

python scripts/run_cad_mesh_convergence.py `
  --generate-hole-box `
  --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe `
  --output-dir mechagent_output/cad-mesh-convergence-hole-box `
  --seed-size 8 --seed-size 6 --seed-size 4 `
  --stabilization-tolerance 0.02
```

带 `root:4:12` 局部尺寸场的实体块收敛清单为
`mechagent_output/cad-mesh-convergence-local-size/manifest.json`，状态为 `passed`。两个运行保持
相同的源文件摘要、拓扑摘要、区域契约摘要和局部尺寸场摘要；seed size 为 20 mm 和 10 mm，节点/单元
数分别为 457/1442 和 453/1423，最小 `min_sicn` 分别为 0.31488 和 0.31705，终点相邻结果变化为
9.543e-5，参考相对误差为 1.332%。清单同时保留局部尺寸场的区域、目标尺寸、影响距离和实际拓扑绑定。

实体块参考值为均匀端面压力下的轴向位移 `pL/E`，其中 `p=10 MPa`、`L=100 mm`、`E=210000 MPa`；该公式只适用于脚本默认的完整矩形实体和轴向线弹性工况。贯穿孔案例没有内置解析参考值，清单只能记录网格稳定性和 `unverified` 状态。

```powershell
python scripts/run_mesh_convergence.py `
  --case-id TC-01 `
  --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe `
  --output-dir mechagent_output/mesh-convergence-YYYYMMDD
```

输出目录必须为空；脚本拒绝覆盖既有证据。`convergence.json` 的 `status=passed` 且清单校验退出码为 0，才算该案例收敛门禁通过。只有网格结果稳定而没有参考解时，状态为 `unverified`，工程验收待参考证据。

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
python scripts/run_natural_language_cases.py --output-dir mechagent_output/natural-language-cases-YYYYMMDD
python scripts/run_llm_smoke.py
python scripts/studio_http_smoke.py --output-dir mechagent_output/studio-http-evidence-live
python scripts/build_knowledge.py
python scripts/index_knowledge.py
python -m mechagent.cli inspect "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力静力分析" --json
python -m mechagent.cli config validate
python -m mechagent.cli config validate --llm
python -m pip check
python -m build packages/mechagent-core
python -m build packages/mechagent
python scripts/generate_sbom.py --output dist/mechagent-sbom.spdx.json
python scripts/build_release_manifest.py --output dist/mechagent-release-manifest.json
# 只有发布环境已配置 cosign 和签名密钥时执行；命令会立即验证签名
python scripts/sign_release.py --manifest dist/mechagent-release-manifest.json --root . --signature dist/mechagent-release-manifest.sig --key path/to/cosign.key --expected-commit <tag-commit>
# GitHub OIDC keyless 模式
python scripts/sign_release.py --manifest dist/mechagent-release-manifest.json --root . --bundle dist/mechagent-release-manifest.sigstore.json --expected-commit <tag-commit> --certificate-identity "https://github.com/ORG/REPO/.github/workflows/release.yml@refs/tags/vX.Y.Z"
# 下载或归档后独立校验清单中的所有文件摘要和签名身份
python scripts/verify_release.py --manifest dist/mechagent-release-manifest.json --root . --bundle dist/mechagent-release-manifest.sigstore.json --expected-commit <tag-commit> --certificate-identity "https://github.com/ORG/REPO/.github/workflows/release.yml@refs/tags/vX.Y.Z"
# 两侧结果均来自同一 SimulationCase；默认比较 requested_fields，可显式选择 mapped_fields、comparison_fields 或 fields
python scripts/compare_backends.py --left calculix-result.json --right abaqus-result.json --left-backend calculix --right-backend abaqus --output dist/backend-comparison.json
# 比较统一语义字段
python scripts/compare_backends.py --left calculix-result.json --right abaqus-result.json --left-backend calculix --right-backend abaqus --field-source comparison_fields --output dist/backend-comparison-semantic.json
# 在本机真实运行同一案例并保存输入摘要、各工具结果和比较清单
python scripts/run_backend_comparison.py --case-id TC-01 --case-id TC-03 --case-id TC-04 --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe --abaqus D:/Abaqus2023/Commands/abaqus.bat --relative 0.03 --absolute 0.005 --output-dir mechagent_output/backend-comparison
# 在同一 SimulationCase 上验证 Abaqus 多步执行、完整场量和逐步结果字段
python scripts/run_abaqus_multistep.py --abaqus D:/Abaqus2023/Commands/abaqus.bat --output-dir mechagent_output/abaqus-multistep
# 验证 CalculiX 多步执行、FRD 原生场量和逐步结果字段
python scripts/run_calculix_multistep.py --calculix D:/Calculix/CalculiX-2.23.0-win-x64/bin/ccx_MT.exe --output-dir mechagent_output/calculix-multistep
python scripts/check_wheel_install.py
python -m mkdocs build --strict
python scripts/clean_artifacts.py
```

## 验证范围与结果

测试覆盖数据契约、解析与单位、能力及工具工厂、编排和错误归因、LLM 响应与脱敏、SDK/CLI/Studio API、求解与后处理、知识索引、安装包、文档链接、主题和翻译。前端测试检查翻译插值、动态摘要、占位符一致性、标签键盘切换、作业状态和幂等提交；浏览器检查覆盖真实求解、场量、报告、历史、语言、主题和窄屏布局。

当前维护基线包括五个标准算例、28 个自然语言案例以及 15 项 LLM smoke 检查。标准算例均满足上表阈值；自然语言案例按是否有参考分别报告。Python 与前端测试、TypeScript/Vite 构建、生产依赖 `npm audit --omit=dev --audit-level=high`、Python 运行时外部依赖审计（`scripts/audit_python_dependencies.py --runtime-only`）、Ruff、mypy、隔离 wheel 安装、依赖一致性及严格文档构建均由质量门禁执行，结果以当前命令输出和对应证据清单为准。`scripts/audit_python_dependencies.py` 从两个包的 `pyproject.toml` 收集运行、开发和文档依赖，排除仓库内未发布到 PyPI 的本地发行包，再调用 `pip-audit`；网络或漏洞服务不可用时审计失败，审计结果按失败状态处理。CI 使用 `scripts/check_env.py --profile portable` 和 `pytest -m "not real_solver"`；本机真实求解单独执行。

`scripts/generate_sbom.py` 生成 SPDX 2.3 JSON，包含当前 Python 环境和 `package-lock.json` 中的依赖及 purl。依赖缺少许可证元数据时保留 `NOASSERTION`；该清单用于发布前许可证审计，许可证人工确认另行进行。

`scripts/build_release_manifest.py` 要求两个包各有一个当前版本的 wheel 和 sdist，并记录 Git 提交、UTC 时间、相对路径、大小、媒体类型、SHA-256 和构建上下文 provenance。provenance 包含源提交状态、Python/Node/平台版本和 `SOURCE_DATE_EPOCH`；签名、作者身份和可信构建服务证明由后续发布步骤提供。`scripts/sign_release.py` 支持受控密钥签名和 GitHub OIDC keyless 签名，签名后立即执行 `verify-blob`；`scripts/verify_release.py` 可在独立环境重新校验所有 artifact 摘要、签名身份、期望提交和期望版本。发布清单必须声明干净 Git 源状态。缺少签名工具、密钥或 OIDC 证书身份时以失败结束。
`.github/workflows/release.yml` 在构建前执行 `scripts/check_release_tag.py`，要求 `v<版本>` 与两个包的版本完全一致；构建后使用 GitHub OIDC 生成 build provenance attestation，并用 `gh attestation verify` 校验每个发布 subject 的仓库、工作流、tag 和 OIDC issuer 身份，再由 cosign 对发布清单执行 keyless 签名和验证。签名和独立验证同时要求清单绑定 `github.sha`，防止使用其他提交生成的清单通过 tag 发布门禁。工作流只响应显式版本 tag；本地构建清单和源码状态不能替代可信 CI 的签名与 attestation。该门禁只有 tag 工作流在目标仓库中成功运行后才形成外部验证证据。
PR 和发布工作流中的第三方 action 固定到完整 commit SHA；PR 工作流仅授予 `contents: read`，发布工作流才申请发布、OIDC 和 attestation 所需权限。

结果选择器在 `ResultFieldSpec.unit` 非空时要求后端场声明相同单位；单位缺失或不一致的必需字段直接失败，不能用请求单位覆盖实际单位。选定字段、单元质心映射和统一语义字段分别保留来源与推导信息。字段位置或单位与另一后端不一致时，`requested_fields` 和 `comparison_fields` 返回 `failed`；原始 `fields` 和 `mapped_fields` 保持 `unverified`，避免把不同离散语义的值按标签配对。

`scripts/compare_backends.py` 支持比较 `requested_fields`、原始 `fields`、统一单元质心 `mapped_fields` 和统一语义 `comparison_fields`。请求字段优先按节点坐标建立一一对应，梁类一维网格按主轴位置聚合；原始场只有在位置、单位和离散映射可证明一致时才逐值比较，其他情况标记为 `unverified`。结果提取根据节点坐标和单元连接生成 `mesh_digest`；原始 `element` 场在两侧提供完整且无歧义的 `element_centroids` 时按质心坐标配对，坐标缺失、覆盖不足或存在多个候选质心时保持 `unverified`；未提供可用质心坐标时才按两侧一致网格指纹和字段键进行比较。原始 `integration_point` 场要求两侧网格指纹一致且字段键对应。统一单元质心字段由单元连接、节点坐标和原始场值确定性聚合；节点场必须覆盖单元所需节点，只有梁允许对截面展开节点按主轴站位聚合。板和实体的部分覆盖会保留已映射单元并记录不完整覆盖，比较器不把它作为可通过的跨后端结果。每个映射字段保留源值数量、目标单元数量、已映射数量、覆盖率、完整性、源位置和映射方法；比较器对覆盖率不足的 `mapped_fields` 返回 `unverified`。统一语义字段由应力本构、全场极值和支撑区域合力推导。每个适配器结果包含完整 `case_digest` 和后端无关的 `physical_case_digest`，并保留单位、坐标系、输入摘要和工作目录内产物摘要。`case_digest` 包含结果字段原生位置；`physical_case_digest` 包含物理输入、分析步和求解控制，排除来源元数据、案例标识以及结果字段的原生位置。两侧完整指纹不一致时，只有物理指纹同时存在且一致才允许继续比较；物理指纹不一致直接返回 `failed`。字段位置、单位或离散语义仍按字段契约校验，不能由物理指纹一致性覆盖。比较器在两侧结果只要有一侧声明 `units` 或 `coordinate_system` 时，要求另一侧同时声明且内容完全一致，校验失败返回 `failed`。多步结果统一提供 `steps`、逐帧字段、`step_results`、兼容别名 `result_steps` 和逐步逐帧的 `mapped_step_fields`，按 `load_steps.sequence` 排列；缺失分析步保持失败或未验证状态。比较结果保留来源、推导、对齐方式、缺失字段、未验证字段、误差以及每个字段的 `status`、`reason`、`alignment`、比较数量、映射方法和双方覆盖率。`run_backend_comparison.py` 在同一 `SimulationCase` 上运行选定工具并保存案例摘要、原始结果、统一单元质心字段、统一语义字段、反力平衡报告和比较清单；清单中的后端结果引用使用相对于输出目录的 POSIX 路径，便于独立归档和验证。默认跨后端阈值为相对误差 3%、绝对误差 0.005；单元质心字段默认相对误差阈值为 10%。多步和跨工具脚本在写入清单前等待产物连续两次快照一致，并确认目录内没有活动求解锁。
`compare_backend_step_fields()` 进一步按 `step_id` 或 `sequence` 配对分析步，再按求解帧标识配对输出帧；它对每个帧复用同一结果级契约、网格对齐、字段覆盖和误差阈值。只由一侧输出且标记为 `initial` 的基准帧保留在 `unmatched_frames`，不作为求解帧数值对应项；缺少其他求解帧或分析步返回 `failed`，没有逐步结果返回 `unverified`。重复分析步或帧标识、未知 `frame_role`、非对象字段记录或显式空 `frames` 数组进入 `invalid_records`，比较状态为 `failed`；只有未提供 `frames` 字段时才允许使用步级最终字段兼容表示。`scripts/run_backend_comparison.py` 在两侧存在逐步结果时同时执行 `requested_fields` 和 `mapped_fields` 的逐步逐帧比较，并将状态纳入案例总状态；任何分析步或求解帧缺失都会使案例比较失败。

坐标映射必须覆盖参与比较的全部场值；坐标缺失、覆盖不足或多个候选点落入同一容差范围时不使用后端本地标签直比，结果保持 `unverified`。字段同时声明 `quantity`、`component`、`invariant` 或 `selector` 时，两侧声明必须一致，否则返回 `failed`。

Studio API 路径隔离门禁覆盖健康检查、环境诊断、预检、worker 结果、进度事件和历史作业读取。测试使用 POSIX、Windows 驱动器、UNC 和父目录跳转样例，确认公开响应只保留文件名或工作目录内相对路径，并保留请求正文与非路径诊断信息。该门禁与结果清单的相对路径校验分开执行：前者限制 API 可见内容，后者校验归档文件的完整性和越界引用。HTTP 错误门禁覆盖缺少凭据、权限拒绝、参数校验、空请求、限流和未知作业，要求 `/api/v1` 与兼容 `/api` 返回稳定 `code`、诊断 `detail` 及正确的版本/弃用响应头。

本机 Abaqus 2023 与 CalculiX 2.23 的真实适配器运行中，TC-01、TC-03、TC-04 的请求位移字段、统一单元质心字段、统一语义摘要和两侧反力平衡均通过。权威清单为 `mechagent_output/backend-comparison-current/manifest.json`，状态为 `passed`。清单中三个案例的 `requested_step_fields` 与 `mapped_step_fields` 均为 `passed`，每个案例的一步一个求解帧均完成逐帧比较。位移使用 `line-coordinate-centerline` 或 `node-coordinate` 对齐；统一单元质心字段包含 `stress_sxx`、`strain_exx` 和 `volume`，实体案例还包含 `strain_energy_density`，阈值为相对误差 10% 或绝对误差 0.005。三个案例的原始 `element` 位置 `volume` 字段均按完整单元质心坐标完成配对；TC-03 的原始反力离散值超出逐节点比较阈值，其他节点、积分点、梁截面展开和原始能量字段在缺少可证明对应关系时保持 `unverified`。统一语义字段覆盖应力最大分量、应变能密度摘要和支撑区域反力合力，阈值为相对误差 3% 或绝对误差 0.005。反力平衡报告根据模型可计算的集中力、梁全跨线载荷和参数化板/实体压力合力，校核支撑边界反力；位移控制、力矩、温度载荷、未知 CAD 受载面积和未支持区域保持 `unverified`。逐积分点应力、逐节点反力、原始能量场、其他网格、单元族和物理域仍需独立验收。

适配器测试覆盖许可证探针非零返回、进程内槽位等待超时、共享 SQLite 队列的跨进程容量限制、租约释放和容量漂移拒绝；这些记录适配器和队列的失败路径。Abaqus 实际许可证不可用时仍需保存本机审计记录。共享队列的验证范围是同一可用文件系统上的 Python 进程协调；FLEXnet 和集群许可证服务的容量状态需单独审计。

`scripts/run_abaqus_multistep.py` 的本机验证清单为 `mechagent_output/abaqus-multistep-evidence/manifest.json`，状态为 `passed`。该运行包含 2 个分析步、每步 2 个 ODB 帧、101 个节点、400 个积分点应力和应变值、100 个单元体积值、400 个应变能密度值、101 个节点反力值、全局 `ALLIE` 能量值以及 4 个逐帧结果记录。两个步骤均保留 `ALLIE`、`ALLSE`、`ALLWK` 和 `ALLPD` 历史能量；`requested_fields` 与 `step_results` 均包含位移、应力分量、应变、体积、应变能密度、反力和能量字段。每个逐帧记录都经过相同字段覆盖检查。该证据验证 Abaqus 适配器的本机多步执行与场提取路径，不扩大到非线性、接触或其他单元族。

`scripts/run_calculix_multistep.py` 的本机验证清单为 `mechagent_output/calculix-multistep-evidence/manifest.json`，状态为 `passed`。该运行包含 2 个分析步、每步 1 个 FRD 结果帧、404 个节点场值、100 个单元体积值以及位移、应力、应变、应变能密度、节点反力和单元能量字段；`requested_fields` 与 `step_results` 覆盖同一组物理量。CalculiX 当前输出的应力、应变和反力位置为节点，体积、应变能密度和能量位置为单元；这些原生位置保留在结果契约中，跨后端比较通过坐标对应或单元质心映射完成。该证据验证 CalculiX 适配器的多步 FRD 解析路径，不把原生节点场声明为积分点场。

`mechagent_output/multistep-comparison-current/manifest.json` 保存 Abaqus 与 CalculiX 双步 `mapped_fields` 的逐帧比较。两侧 `physical_case_digest` 一致，每个分析步的求解帧比较通过；Abaqus 还保留每步 `initial` 基准帧，而 CalculiX 不输出这类帧，基准帧记录在 `unmatched_frames`，不影响求解帧状态。清单状态只有在所有分析步和求解帧均通过时才为 `passed`。

Studio 备份必须在调度器停止且没有活动作业时创建；清单覆盖数据库、作业目录和本地对象，恢复目标必须为空目录。

真实 S3 验收使用 `scripts/check_s3_storage.py --bucket <bucket>`，可附加
`--endpoint-url <url>`、`--require-lifecycle-id <id>` 和 `--output-dir <directory>`。
脚本通过 boto3 标准凭据链创建随机探针对象，验证 SHA-256 metadata、下载、前缀列举和默认删除；
指定 `--output-dir` 时保存 `probe.json` 与可校验的 `manifest.json`。该探针的证据范围是指定桶当前权限
和生命周期读取结果；跨主机恢复、容量配额和灾备指标需单独验收。

Studio 本机磁盘配额通过 `studio.max_storage_bytes` 配置。配额统计数据库父目录及本地 `artifact_root` 内的普通文件，提交前和成功结果写入后检查；超额提交返回 HTTP 507，超额结果记录 `storage_quota_exceeded`，不保留公开结果引用。`null` 表示不启用配额，S3 远端对象不计入本机目录用量。`tests/core/test_artifacts_backup.py` 覆盖提交前超额、结果写入后超额、外置本地对象目录和指标状态，`tests/core/test_studio.py` 覆盖 HTTP 507 映射。

```powershell
python scripts/backup_studio.py create --database mechagent_output/.studio/jobs.sqlite3 --destination mechagent_output/studio-backup
python scripts/restore_studio.py --backup mechagent_output/studio-backup --destination mechagent_output/studio-restore
python scripts/restore_studio.py --backup mechagent_output/studio-backup --destination mechagent_output/studio-restore --verify-only
```

数据库使用 S3 结果对象时，冷备份必须显式指定对象存储；脚本会将数据库引用的对象下载到备份清单，
恢复时可上传到目标桶：

```powershell
python scripts/backup_studio.py create `
  --database mechagent_output/.studio/jobs.sqlite3 `
  --destination mechagent_output/studio-backup `
  --artifact-backend s3 --bucket <source-bucket> --prefix mechagent `
  --endpoint-url <source-endpoint> --region <source-region>
python scripts/restore_studio.py `
  --backup mechagent_output/studio-backup `
  --destination mechagent_output/studio-restore `
  --artifact-backend s3 --bucket <target-bucket> --prefix mechagent `
  --endpoint-url <target-endpoint> --region <target-region>
```

备份与恢复命令使用 boto3 标准凭据链，不在清单或日志写入凭据；目标桶权限和跨主机 RTO/RPO
仍须在实际部署环境运行演练。

灾难恢复演练使用独立的空 workspace，不覆盖既有备份或恢复目录。脚本记录源数据库和恢复数据库的完整性、作业数量、备份/恢复耗时、RPO 丢失作业数和总 RTO，并按显式目标判定退出码。RPO 基准是演练开始时可见的作业 ID；RTO 从演练开始计时到恢复数据库完成完整性检查。为验证结果对象，可通过 `--source-artifact-backend`、`--source-artifact-root` 或 `--source-bucket` 等参数指定源端对象存储，通过对应的 `--target-*` 参数指定目标端对象存储；清单同时记录源端引用校验、目标端对象校验和恢复结果载荷读取状态。当前机器的实际 Studio 数据库演练证据为 `mechagent_output/studio-recovery-evidence/manifest.json`，源库含 1 个终态作业，恢复后作业 ID 丢失数为 0，RTO 约 0.089 秒，目标为 60 秒，清单状态为 `passed`。该证据范围是指定机器、数据库、对象目录和目标阈值；实际跨主机或 S3 部署仍需运行带源端和目标端存储参数的演练。

```powershell
python scripts/drill_studio_recovery.py `
  --database mechagent_output/.studio/jobs.sqlite3 `
  --workspace mechagent_output/recovery-drill-YYYYMMDD `
  --rto-target-seconds 60 `
  --rpo-max-lost-jobs 0
```

使用不同的 S3 兼容对象存储验证结果对象迁移时，为命令增加
`--source-artifact-backend s3 --source-bucket <source-bucket> --source-prefix <prefix>`
以及 `--target-artifact-backend s3 --target-bucket <target-bucket> --target-prefix <prefix>`；
端点和区域分别使用 `--source-endpoint-url`、`--source-region`、
`--target-endpoint-url` 和 `--target-region`。源端和目标端使用 boto3 标准凭据链，脚本不记录凭据。

退出码为 0 且 `recovery-drill.json` 的 `status` 为 `passed` 才算该环境的演练通过。目标目录已存在、数据库含活动作业、备份清单不完整、作业 ID 丢失或 RTO 超限均保留失败状态；不要删除失败证据后重跑。

S3 兼容对象存储通过 `pip install "mechagent[s3]"` 和 `studio.artifact_backend=s3` 启用；
访问密钥由 boto3 标准凭据链提供。`studio.artifact_s3_endpoint_url` 和
`studio.artifact_s3_region` 可选择 S3 兼容私有端点和区域。当前仓库包含客户端、摘要校验和恢复
接口；上传、下载和恢复均校验对象内容与 SHA-256 摘要。恢复演练可以把源端和目标端配置为不同的
对象存储，并把结果对象摘要和载荷读取状态写入演练报告。远端桶权限、跨主机备份保留和灾难恢复时间指标
仍需要部署环境单独验收。

```powershell
python scripts/check_s3_storage.py `
  --bucket <bucket> `
  --prefix mechagent/probe `
  --require-lifecycle-id <lifecycle-rule-id> `
  --output-dir mechagent_output/s3-storage-evidence
```

退出码为 0 且 JSON 或 `manifest.json` 中 `status` 为 `passed` 才表示该桶的当前写入、读取、列举、
删除和生命周期检查通过。该探针不证明跨主机备份恢复、容量配额或对象锁策略；这些仍需在部署环境
执行独立演练。

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

`tests/core/test_runtime.py` 使用真实独立进程验证取消、心跳丢失、执行超时、进程身份与子进程终止，验证 worker 异常退出时退出码进入终态记录和证据清单，使用数据库并发验证幂等键、排队容量和领取上限。API 测试通过真实 worker 产生失败报告，并在应用生命周期重启后查询相同作业；不依靠同进程 monkeypatch 代替 worker 求解。SDK、结果文件和清单测试覆盖配置脱敏、源配置变化、文件缺失与内容篡改。

```powershell
python -m pytest tests/core/test_runtime.py tests/core/test_studio.py
python -m mechagent.cli verify-evidence path/to/run/manifest.json
```

文件校验通过返回退出码 0，不匹配返回 1；工程参考比较单独执行。Windows Job Object 进程树终止具有本机与 Windows CI 行为测试；其他操作系统的进程边界仍需独立验收。运行层当前没有求解器内部断点续算接口。

身份目录门禁使用组织管理员创建主体、验证项目和组织范围、轮换并停用 API key；数据库只保留
SHA-256 摘要，创建和轮换响应中的明文 key 不会写入主体表。`expires_at` 必须是带时区且晚于当前时间的 ISO 8601 时间；认证查询拒绝已过期主体，更新请求省略该字段时保留原值，显式 `null` 表示永不过期。跨组织管理员可读取和管理全部组织，普通管理员只能操作所属组织。指标接口的最小检查使用已配置的 Bearer API key；不携带项目范围时只有 admin 可以读取本组织统计：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/v1/metrics?project_id=default -Headers @{Authorization="Bearer <key>"}
```

响应包含作业状态计数、队列等待、执行时长、失败代码、结果对象大小、证据完整性计数、本机工作目录字节数与配额、数据库文件系统容量以及 worker 和可见子进程的 CPU 时间与峰值常驻内存；请求正文、凭据、文件路径和原始 worker 诊断位于响应字段之外。资源或文件系统字段为空时表示当前边界没有可读取的采样；本机工作目录配额和文件系统指标与 S3 容量、集中 telemetry 分别统计。

独立 HTTP 验收使用 `scripts/studio_http_smoke.py`。脚本在临时输出目录生成只含 API key 摘要的配置，启动独立 Uvicorn 进程，并通过回环 TCP 请求验证缺少凭据、管理员认证、v1 响应头、主体创建、过期时间返回、PATCH 保留和清除过期时间、已过期主体拒绝认证、项目允许与拒绝、密钥轮换、旧密钥撤销、主体停用和审计读取。脚本只在进程结束后写入 `http-smoke.json` 和 `manifest.json`，不会输出明文 key；退出码为 0 且清单校验无错误才算通过：

```powershell
python scripts/studio_http_smoke.py --output-dir mechagent_output/studio-http-evidence-live
```

输出目录必须为空；保留已有清单时使用新的空目录执行，不覆盖既有证据。

本机 HTTP 验收清单为 `mechagent_output/studio-http-evidence-live/manifest.json`，状态为 `passed`。该证据覆盖单机回环 HTTP 和单个 SQLite 数据库，不证明 TLS、反向代理、外部身份提供商、跨主机审计或分布式配额。

## 清理策略

```powershell
# 先列出精确删除目标，不修改文件系统
python scripts/clean_artifacts.py --dry-run
# 删除可再生成缓存和构建产物
python scripts/clean_artifacts.py
python scripts/clean_artifacts.py --include-studio-runtime
python scripts/clean_artifacts.py --include-runs
```

`--dry-run` 会执行相同的作业数据库、求解锁、仓库边界和 Git 跟踪文件检查，只输出待删除路径。默认清理 Python、pytest、Ruff、mypy、通用工具和 Vite 缓存、覆盖率文件、包构建目录、前端依赖、文档站点、浏览器临时输出、备份/恢复临时目录、可再生成知识索引以及常见临时文件（`.pyc`、`.pyo`、`.tsbuildinfo`、`.eslintcache`、`.coverage.*`、`.upload.*.tmp`、交换文件、调试日志和系统缩略图），保留 `mechagent_output/` 与 FEM 运行文件。`--include-studio-runtime` 仅删除 `mechagent_output/.studio` 的本地 Studio 运行时数据库、作业目录和对象目录，保留正式证据目录；`--include-runs` 同时删除运行证据和 `.frd/.dat/.sta/.msg`。这两个选项要求目标中没有需要保留的报告、ODB、输入、发布包或活动作业。脚本在任何删除前检查路径边界；Git 跟踪文件及其父目录受到保护，相关目录存在 `.lck` 或作业数据库存在排队、启动、运行、取消中任务时拒绝运行证据清理。

`.env`、`knowledge/sources/` 和非空 `knowledge/raw/` 不属于清理目标。外部求解器和 Python 安装目录由维护者管理。

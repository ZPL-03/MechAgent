# 验证与质量门禁

本文记录标准验证算例、独立自然语言测试案例、质量门禁命令、测试覆盖范围与清理策略。

## 标准验证

标准验证由独立命令执行：

```powershell
python scripts/run_benchmarks.py
```

| 编号 | 物理量 | CalculiX | 解析参考 | 相对误差 | 阈值 | 状态 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| TC-01 | `tip_deflection` | 14.896 mm | 14.880952 mm | 0.101120% | 1% | 通过 |
| TC-02 | `center_deflection` | 0.155959 mm | 0.154233 mm | 1.118913% | 2% | 通过 |
| TC-03 | `axial_displacement` | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% | 通过 |
| TC-04 | `tip_deflection` | 5.58805 mm | 5.580357 mm | 0.137856% | 2% | 通过 |
| TC-05 | `axial_displacement` | 0.00949132 mm | 0.00952381 mm | 0.341140% | 8% | 通过 |

解析参考公式见 [求解器、网格与后处理](solver_mesh.md)。

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
`ModelParams` 与案例契约之间的兼容转换，以及未知未来 schema 的拒绝行为。运行层门禁
检查 v1 数据库迁移、迁移记录、旧作业读取和未来数据库版本拒绝；API 门禁检查 `/api/v1`
路由与旧 `/api` 兼容入口的弃用响应头。

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
python scripts/check_wheel_install.py
python -m mkdocs build --strict
python scripts/clean_artifacts.py
```

## 验证范围与结果

测试覆盖数据契约、解析与单位、能力及工具工厂、编排和错误归因、LLM 响应与脱敏、SDK/CLI/Studio API、求解与后处理、知识索引、安装包、文档链接、主题和翻译。前端测试检查翻译插值、动态摘要、占位符一致性、标签键盘切换、作业状态和幂等提交；浏览器检查覆盖真实求解、场量、报告、历史、语言、主题和窄屏布局。

当前维护基线包括五个标准算例、28 个自然语言案例以及 15 项 LLM smoke 检查。标准算例均满足上表阈值；自然语言案例按是否有参考分别报告。Python 测试收集 516 项并全部通过，便携测试以最终门禁输出为准；测试环境有 2 条第三方弃用告警。前端 19 项测试、TypeScript/Vite 构建、生产依赖 `npm audit --omit=dev --audit-level=high`、Ruff、mypy、隔离 wheel 安装、依赖一致性及严格文档构建通过。Python 依赖漏洞审计尚未形成稳定的 CI 门禁。CI 使用 `scripts/check_env.py --profile portable` 和 `pytest -m "not real_solver"`，不替代本机真实求解验证。

`scripts/generate_sbom.py` 生成 SPDX 2.3 JSON，包含当前 Python 环境和 `package-lock.json` 中的依赖及 purl。依赖缺少许可证元数据时保留 `NOASSERTION`；该清单可作为发布前许可证审计输入，不替代许可证人工确认。

`scripts/build_release_manifest.py` 要求两个包各有一个当前版本的 wheel 和 sdist，并记录 Git 提交、UTC 时间、相对路径、大小、媒体类型和 SHA-256。清单用于核对构建资产；它不提供签名、作者身份或构建 provenance。

## 作业故障与证据校验

`tests/core/test_runtime.py` 使用真实独立进程验证取消、心跳丢失、执行超时、进程身份与子进程终止，使用数据库并发验证幂等键、排队容量和领取上限。API 测试通过真实 worker 产生失败报告，并在应用生命周期重启后查询相同作业；不依靠同进程 monkeypatch 代替 worker 求解。SDK、结果文件和清单测试覆盖配置脱敏、源配置变化、文件缺失与内容篡改。

```powershell
python -m pytest tests/core/test_runtime.py tests/core/test_studio.py
python -m mechagent.cli verify-evidence path/to/run/manifest.json
```

文件校验通过返回退出码 0，不匹配返回 1；校验不替代工程参考比较。Windows Job Object 进程树终止具有本机与 Windows CI 行为测试；其他操作系统的进程边界仍需独立验收。运行层不提供求解器内部断点续算。

## 清理策略

```powershell
python scripts/clean_artifacts.py
python scripts/clean_artifacts.py --include-runs
```

默认清理缓存、包构建目录、前端依赖、文档站点、浏览器临时输出和可再生成知识索引，保留 `mechagent_output/` 与 FEM 运行文件。`--include-runs` 同时删除运行证据和 `.frd/.dat/.sta/.msg`。使用该选项前应将需要保留的报告、ODB、输入和发布包移出清理目标，并确认没有活动作业。脚本在任何删除前检查路径边界；Git 跟踪文件及其父目录受到保护，相关目录存在 `.lck` 或作业数据库存在排队/启动/运行/取消中任务时拒绝运行证据清理。

`.env`、`knowledge/sources/` 和非空 `knowledge/raw/` 不属于清理目标。外部求解器和 Python 安装目录由维护者管理。

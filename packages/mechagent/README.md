# mechagent

`mechagent` 提供 SDK、CLI、Studio、LLM、知识库与多智能体编排。应用通过能力注册和 core 工具工厂完成工程请求到求解证据的链路；工具内部表示由适配器隔离。

## 使用

在仓库根目录的已激活 Python 3.10+ 虚拟环境中执行：

```powershell
python -m pip install -e packages/mechagent-core
python -m pip install -e "packages/mechagent[dev,docs]"
python -m mechagent.cli doctor
python -m mechagent.cli studio --open-browser
```

SDK 入口为 `MechAgent.from_config()`、`inspect()` 和 `run()`。Studio、CLI 与 SDK 共用能力、执行门禁和结果契约。复合请求拆分为独立任务，单任务失败时保留诊断，其余任务继续执行。

## 产品与边界

Studio 支持中英文界面、明暗与系统主题、几何/网格/结果视口、验收检查和 Markdown 报告。Three.js 懒加载并按需渲染。界面只消费公开摘要，原始 LLM prompt 与 response 不进入公开输出。

内置能力限定为结构线弹性静力，默认工具为 CalculiX 和 Gmsh；Abaqus/Standard 适配器已注册，覆盖当前结构静力族的输入、作业启动和 ODB 结果场提取。LLM 可参与能力选择、参数补全、网格建议和工程解释；输出必须满足工程契约。CAD 候选链路、几何候选生成与验证、Abaqus 适配器和独立工具基准的范围见[能力说明](../../docs/capabilities.md)、[几何路线](../../docs/geometry_ai.md)与[工具说明](../../docs/solver_mesh.md)。

安装配置见[本地开发配置](../../docs/local_setup.md)，产品目标见[产品蓝图](../../docs/product_blueprint.md)，模块与状态见[架构](../../docs/architecture.md)和[编排说明](../../docs/orchestration.md)。本包采用 Apache License 2.0。

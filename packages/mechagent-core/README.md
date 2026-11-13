# mechagent-core

`mechagent-core` 提供 CAE/FEA 数据模型、材料目录、工具抽象、后处理与验证参考，不依赖 Agent 编排层。

| 模块 | 职责 |
| --- | --- |
| `models` / `rules` | Pydantic 参数、枚举、范围和结构静力执行约束 |
| `solver` / `mesher` | `AbstractSolver`、`AbstractMesher` 与统一结果模型 |
| `cad` | `AbstractCADKernel`、形体摘要与参数候选 |
| `executor` | `AbstractJobExecutor`、作业模型与同步本地执行器 |
| `factory` | 求解器、网格器、CAD 内核与执行器的注册/创建/注销 |
| `materials` / `postproc` | 钢铝材料目录、`PostProcessor` 摘要；没有独立工厂注册 API |
| `adapters` / `validation` | CalculiX、Abaqus/Standard、Gmsh OCC/CAD mesh 适配与解析参考 |

内置注册名为 `calculix`、`abaqus`、`calculix-inp`、`gmsh-occ`、`gmsh-cad-inp`、`local`。适配器封装各工具的格式和调用，核心契约保持统一。参数拒绝非有限数值，成功网格必须提供实际网格路径。CAD 摘要、拓扑区域和直接 C3D4 网格的能力边界见[几何路线](../../docs/geometry_ai.md)。支持范围和失败行为见[架构与数据契约](../../docs/architecture.md)、[工具说明](../../docs/solver_mesh.md)。

在已激活 Python 3.10+ 虚拟环境中安装：

```powershell
python -m pip install -e packages/mechagent-core
```

本包采用 Apache License 2.0，提供 PEP 561 类型标记。验证与数值证据见[验证说明](../../docs/validation.md)。

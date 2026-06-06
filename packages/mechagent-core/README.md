# mechagent-core

`mechagent-core` 提供开源 CAE/FEA 工具抽象层，包括求解器接口、网格器接口、
Pydantic 数据模型、后处理工具、开源适配器和解析参考公式。

内置材料目录位于 `mechagent.core.materials`，提供钢和铝合金的自然语言别名匹配。
核心 Pydantic 模型要求几何尺寸、材料参数、载荷幅值/方向、边界值、网格尺寸和复合铺层数值均为有限数值。
`MeshConfig.seed_size`、`MeshConfig.min_quality` 和 `SolverResult.wall_time` 同样拒绝非有限数值。

## 适配器

- `CalculiXAdapter`：生成 B31 梁、S4 壳板和 C3D8R 实体 `.inp`，调用 CalculiX，并解析 `.frd`。
- `CalculiXInpMesher`：矩形板路径调用 Gmsh Python API，梁和矩形实体块路径使用确定性结构化网格，
  统一生成 CalculiX 可消费网格片段。

求解器和网格器通过 `register_solver()`、`register_mesher()` 注册到工厂，通过
`unregister_solver()`、`unregister_mesher()` 注销。上层调用 `create_solver()`、
`create_mesher()` 获取后端实例。

工程规则函数包括 `check_parameter_ranges()`、`ensure_parameter_ranges()`、
`check_static_execution_contract()` 和 `ensure_static_execution_contract()`。
`CalculiXAdapter` 在输入生成前校验各向同性线性静力材料、几何非线性开关、单元类型、
几何必需尺寸、边界条件、载荷区域和载荷方向。

## 结构静力能力

| 几何 | 单元 | 载荷 | 边界 |
| --- | --- | --- | --- |
| 梁 | B31 | 纯全局 Y 向端部集中力、全跨均布线载荷 | 一端固支 |
| 矩形板 | S4 | 纯全局 Z 向均布压力 | 四边简支 |
| 矩形实体块 | C3D8R | 纯全局 X 向端面压力、端面合力 | 一端固定 |

## 标准验证

| 编号 | 物理量 | 求解器 | 验收 |
| --- | --- | --- | --- |
| TC-01 | `tip_deflection` | CalculiX | 误差 < 1% |
| TC-02 | `center_deflection` | CalculiX | 误差 < 2% |
| TC-03 | `axial_displacement` | CalculiX | 误差 < 8% |
| TC-04 | `tip_deflection` | CalculiX | 误差 < 2% |
| TC-05 | `axial_displacement` | CalculiX | 误差 < 8% |

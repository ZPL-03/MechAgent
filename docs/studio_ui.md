# Studio 使用指南

MechAgent Studio 是面向用户的本地工程工作台：在同一界面完成自然语言输入、运行前预检、求解、3D 可视化、验收复核与报告阅读。本文面向使用者；前端工程结构见 [前端架构](frontend_architecture.md)，设计规范见 [设计系统规范](design_system.md)。

## 启动

Studio 由 CLI 启动，默认监听 `127.0.0.1:8765`：

```powershell
python -m mechagent.cli doctor
python -m mechagent.cli demo --llm-agents
python -m mechagent.cli studio --open-browser
python -m mechagent.cli studio --open-browser --request "求解长480mm、宽280mm、厚6mm、材料钢的长圆槽孔薄板，槽孔中心x=240mm、槽孔中心y=140mm、槽长160mm、槽宽40mm，四边简支，承受0.003MPa向下均布压力的静力响应" --llm-agents --view geometry --auto-run
```

`demo` 从示例库读取 `SC-27` 长圆槽孔薄板作为默认展示工况，`--example` 可选择其他示例编号。`--request`、`--llm-agents`、`--view geometry|mesh|result` 生成带请求、参数补全状态和初始视图的可复现入口；`--auto-run` 与 `--request` 同用时写入一次性自动运行信号。入口 URL 使用 `/studio?request=…&llm=1&view=…&run=1` 查询参数契约。

## 界面布局

界面采用自适应工作台结构，按宽度在三栏 / 两栏 / 单列之间切换（断点见 [设计系统规范](design_system.md)）：

- **左栏（输入）**：自然语言请求输入、参数补全开关、运行前预检、运行按钮、CLI 复现命令与工作台链接复制；工况示例库、运行历史、模型摘要分页切换。
- **中区（工作区）**：任务切换、3D 几何/网格/结果视口、任务结果矩阵、Markdown 工程报告，以及报告与可视化的复制/下载。
- **右栏（检查器）**：作业与验收状态固定展示；求解流程、Agent 链路、阶段产物和摘要 JSON 通过标签式详情面板切换，内容超出时在面板内部滚动。
- **顶栏**：品牌、运行状态徽标、运行环境诊断面板、主题切换。

## 引导式工作流

工作台围绕「输入 → 预检 → 运行 → 结果」四步引导：

1. **输入**：填写真实工程仿真需求，或从工况示例库一键载入。首次访问提供引导提示与「一键体验示例」。
2. **预检**：输入后自动触发 `MechAgent.inspect()`，展示能力识别、几何类型、缺参诊断和复合任务拆分，判断请求是否可执行。
3. **运行**：点击运行后创建后端作业，贯穿式进度与求解流程面板按后端阶段事件实时更新；运行中结果区与视口显示骨架占位。
4. **结果**：求解完成后展示 3D 结果场、主结果、参考值、相对误差、验收结论、Agent 链路摘要、阶段产物路径与 Markdown 报告。

每个面板在无数据时显示上下文空状态与下一步建议；作业失败在提示条与验收面板同时呈现。

## 主题切换

顶栏主题切换提供「明 / 暗 / 跟随系统」三态。默认跟随系统配色，用户选择持久化到浏览器本地存储，3D 视口背景、网格底与图例随主题切换。

## 3D 视口交互

视口工具栏支持：

- **渲染模式**：几何 / 网格 / 结果三种视图切换。
- **场量**：结果模式下切换 `U` 位移模量、`Ux/Uy/Uz` 位移分量；`.frd` 存在应力场时切换 `S Mises`、`Sxx`、`Syy`、`Szz`、`Sxy`、`Syz`、`Sxz`。
- **视角**：等轴、俯视、前视、右视快捷视角，复位与适配。
- **变形比例**：结果模式调整位移放大系数。
- **图例**：颜色条 + 数值范围 + 单位，随当前场量同步；可开关。
- **导出**：3D 场景 PNG 导出，SVG 兼容输出由后端可视化层生成。

视口右下角透明嵌入式 XYZ 全局坐标系跟随主相机旋转。渲染器采用按需重绘（交互、缩放、视图切换、尺寸变化触发），静止状态不运行连续动画循环。几何类型坐标映射：梁保持横向弯曲视角；矩形板、开孔薄板和实体块将求解 `Z` 轴映射为竖向轴。

## 导出与复现

- **工作台链接**：携带 `request`、`llm`、`view` 查询参数，复制后可复现输入与视图状态；`run=1` 自动运行信号读取后从地址栏移除，不随链接复制保留。
- **CLI 复现命令**：根据当前请求与 `/api/health` 返回的 Python 执行器生成，可在终端或 CI 复跑。
- **报告**：Markdown 工程报告可复制、下载。
- **摘要 JSON**：SDK 公开摘要可复制、下载，文件名按当前任务编号与通过状态生成。
- **运行历史**：浏览器本地保留请求、紧凑摘要与限长报告文本；3D 场景本身不写入本地存储。选中历史项后可重跑该请求恢复几何、网格和结果视图。

复制动作通过固定状态提示和 `aria-live` 区域反馈成功或失败，执行路径使用 Clipboard API 和浏览器原生复制命令回退。

## 可访问性

前端提供跳转到主工作区的 skip link、表单标签、icon-only 按钮 `aria-label`、状态区域 `aria-live`、键盘焦点样式、`prefers-reduced-motion` 动画约束、触控行为、长文本换行和本地化数值格式。正文对比度满足 WCAG AA，明暗主题均适用。

## 后端 API

Studio 后端位于 `packages/mechagent/src/mechagent/ui/server.py`，使用 FastAPI 和 Uvicorn：

- `GET /api/health`：产品名、配置文件路径、当前 Python 执行器和静态资源状态。
- `GET /api/diagnostics`：与 CLI `doctor` 共用的运行环境诊断；`llm=true` 时调用远端 LLM 连接检查。
- `GET /api/capabilities`：已注册仿真能力、默认工具、模型编号和可执行示例请求。
- `GET /api/examples`：完整自然语言示例库（编号、标题、能力编号、几何类型、载荷类型、模型编号、标签、请求文本）。
- `POST /api/inspect`：接收请求与 `use_llm_agents`，调用 `MechAgent.inspect()`，返回任务识别、能力编号、几何类型、缺项、可执行状态和脱敏 Planner trace 摘要。
- `POST /api/run`：调用 `MechAgent.run()`，返回 `success`、Markdown `report`、SDK `summary`、结果 `visualizations` 和运行耗时。
- `POST /api/jobs` / `GET /api/jobs/{job_id}` / `GET /api/jobs`：创建后端仿真作业、轮询作业状态与阶段事件、列出最近作业。
- `GET /{full_path:path}`：服务构建后的 React 单页应用；静态资源缺失时返回构建说明页。

Studio 不改变 Agent 通信契约：浏览器只消费公开摘要、阶段事件和可视化列表，仿真参数、网格、求解、后处理、校核和报告仍由 Python 编排链路产生。可视化层优先读取 `.inp` 网格和 `.frd` 位移场；缺少场数据时使用 `ModelParams` 与主结果值生成等效工程视图。

> 界面截图见 README 与 `docs/assets/`。

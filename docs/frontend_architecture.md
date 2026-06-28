# 前端架构

本文面向贡献者，描述 Studio 前端的目录结构、模块边界、样式约定与构建流程。使用指南见 [Studio 使用指南](studio_ui.md)，设计规范见 [设计系统规范](design_system.md)。

## 技术栈

- React 19 + TypeScript + Vite。
- 图标 `lucide-react`，Markdown `react-markdown` + `remark-gfm`，3D `three`。
- 样式：原生 CSS 自定义属性（设计令牌）+ 令牌驱动的全局样式表 `styles.css`（按区域分节）。不引入 UI 框架。

## 目录结构

```text
apps/mechagent-studio/src/
  main.tsx                 # 入口，挂载 ThemeProvider + App
  App.tsx                  # 瘦壳：Provider + 布局骨架 + hooks 编排
  types.ts                 # 与后端公开摘要对齐的类型契约
  styles.css               # 令牌驱动的全局样式表（按区域分节）
  theme/
    tokens.css             # 排版/间距/圆角/阴影/层级/动效等非颜色令牌
    themes.css             # :root 浅色 / [data-theme=dark] 深色颜色令牌
    base.css               # reset、排版、focus、滚动条、CJK 字体栈
    themeContext.ts        # 主题 context 与类型
    ThemeProvider.tsx      # 主题 Provider（跟随系统 + localStorage 持久化）
    useTheme.ts            # 主题 hook
  lib/
    api.ts                 # 所有 fetch（health/diagnostics/capabilities/examples/inspect/jobs）
    storage.ts             # 运行历史 localStorage 读写与压缩
    url.ts                 # request/llm/view/run 查询参数同步
    cli.ts                 # CLI 复现命令构造
    clipboard.ts           # 剪贴板写入与回退
    download.ts            # 可视化/报告/JSON 下载
    format.ts              # 数值/百分比格式化、记录与文本工具
    labels.ts              # 几何/材料/载荷/边界/网格标签
    results.ts             # 验收状态、指标、摘要、产物推导
    stages.ts              # 求解流程阶段状态
    agentChain.ts          # Agent 链路构建与标签
    diagnostics.ts         # 运行环境诊断摘要
    examples.ts            # 工况库过滤与展示
    visualization.ts       # 任务可视化选择与默认视图
    job.ts                 # 作业状态、耗时、事件
    constants.ts           # STAGES / RENDER_MODES / EXAMPLE_FILTERS / DEFAULT_*
    uiTypes.ts             # UI 层共享类型
  hooks/
    useStudioBootstrap.ts  # 启动拉取 health/diagnostics/capabilities/examples
    useInspection.ts       # 防抖运行前预检
    useToast.ts            # 提示条（aria-live）
  components/
    common.tsx             # PanelTitle / EmptyState / CompactEmpty / Skeleton
    Topbar.tsx             # Topbar / ThemeToggle / StatusPill / RuntimeDiagnosticsMenu
    Composer.tsx           # 请求输入 / 预检卡片 / 操作按钮
    Sidebar.tsx            # SidePanel / 工况库 / 历史 / 摘要
    Workspace.tsx          # WorkflowStepper / ViewportPanel / TaskTabs / ReportPanel
    Inspector.tsx          # InspectorRail：验收 / 流程 / Agent 链路 / 产物 / JSON
  ThreeViewport.tsx        # Three.js 视口（懒加载，主题感知背景）
```

> 运行/历史/任务选择等编排状态保留在 `App.tsx`，复用 `lib/` 的纯函数与 `hooks/` 的副作用封装；`App.tsx` 不直接发请求或操作 DOM 存储。

## 模块边界

- **lib/**：纯函数与副作用封装，不依赖 React。所有 `fetch` 集中在 `api.ts`，组件不直接发请求。
- **hooks/**：组合 `lib/` 与 React 状态，向组件暴露数据与动作；副作用（轮询、防抖、订阅）在此收敛。
- **components/**：展示层，按区域分目录，每个组件配同名 `*.module.css`，只引用语义令牌。
- **theme/**：主题与设计令牌单点来源；组件不写死色值与尺寸。
- **viewport/**：Three.js 渲染拆分；`ThreeViewport` 懒加载，场量与视角作为受控 props 由 `ViewportToolbar` 驱动。

`App.tsx` 仅负责装配 Provider、编排 hooks 与布局骨架，目标控制在 250 行内。

## 样式约定

- 令牌层（`theme/tokens.css`、`theme/themes.css`、`theme/base.css`）与全局样式表 `styles.css` 由 `main.tsx` 一次性 `import`。
- 组件样式集中在 `styles.css`，按区域分节（顶栏、布局、面板、视口、检查器、响应式等），组件使用语义化类名。
- 所有颜色、间距、圆角、阴影、字号引用 `var(--token)`；新增视觉值先在设计系统登记令牌，组件不写死色值与尺寸。
- 明暗主题只切换 `theme/themes.css` 中的颜色语义令牌取值，不在组件层做主题分支；3D 视口背景读取 `--color-viewport-bg`，并在 `data-theme` 变化时更新。

## 数据契约

前端类型定义在 `types.ts`，与后端公开摘要严格对齐（`StudioRunResponse`、`WorkflowSummary`、`TaskSummary`、`VisualizationScene`、`StudioJobResponse` 等）。后端 API 见 [Studio 使用指南](studio_ui.md)。前端只消费脱敏公开摘要，不读取 Agent 内部状态、原始 prompt 或密钥。

## 构建流程

```powershell
npm --prefix apps/mechagent-studio install
npm --prefix apps/mechagent-studio run build
```

`npm run build` 执行 `tsc -b` 类型检查后由 Vite 构建。Vite 配置 `build.outDir` 指向 `packages/mechagent/src/mechagent/ui/static`，构建产物直接作为 `mechagent` 包的静态资源随包发布。开发模式 `npm run dev` 在 `127.0.0.1:5173` 启动，并将 `/api` 代理到本地 Studio 后端 `127.0.0.1:8765`。

前端代码变更后重新执行 `npm run build` 以同步后端静态资源；`node_modules` 与构建中间产物属于清理范围（见 [验证与质量门禁](validation.md)）。

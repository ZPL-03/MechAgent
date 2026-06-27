# 设计系统规范

本文是 MechAgent Studio 前端的设计「单一事实来源」。设计令牌、配色、明暗主题、排版、间距、组件状态以本文为准，`apps/mechagent-studio/src/theme/` 下的 CSS 实现与本文保持一致。

设计目标：在保留工程判读优先、信息密度可控的前提下，提供现代化、可访问、明暗双主题的工作台体验。所有组件只消费**语义令牌**，不写死色值与尺寸。

## 设计原则

- **判读优先**：关键工程指标（计算值、参考值、误差、验收状态）有稳定排版与抗换行保护。
- **层级清晰**：用表面层级（surface elevation）与留白区分信息分组，避免一屏堆叠造成的过载。
- **语义驱动**：颜色、状态、间距通过语义令牌表达；明暗主题只切换令牌取值，不改组件代码。
- **可访问**：正文对比度满足 WCAG AA；焦点可见；尊重 `prefers-reduced-motion`；图标按钮提供 `aria-label`。
- **轻依赖**：原生 CSS 自定义属性 + Vite 原生 CSS Modules，不引入 UI 框架。

## 令牌分层

令牌分两层，组件只引用第二层（语义层）：

1. **原始令牌（primitive）**：色阶与基础刻度，例如 `--blue-600`、`--slate-900`。仅在 `themes.css` 内部映射使用。
2. **语义令牌（semantic）**：角色化别名，例如 `--color-surface`、`--color-text`、`--color-primary`。组件 CSS 只使用语义令牌。

明暗主题通过 `:root`（浅色）与 `[data-theme="dark"]`（深色）覆盖语义令牌实现。

## 颜色

### 角色语义令牌

| 语义令牌 | 角色 |
| --- | --- |
| `--color-bg` | 应用背景（最底层） |
| `--color-surface` | 卡片/面板表面 |
| `--color-surface-subtle` | 次级表面（内嵌区、输入底） |
| `--color-surface-strong` | 强调表面（选中、激活底） |
| `--color-border` | 默认描边/分隔 |
| `--color-border-strong` | 强描边、控件边界 |
| `--color-text` | 主文本 |
| `--color-text-muted` | 次文本、说明 |
| `--color-text-subtle` | 占位、弱提示 |
| `--color-primary` / `--color-primary-hover` | 主操作（运行、主按钮、强调链接） |
| `--color-on-primary` | 主操作上的前景文字 |
| `--color-accent` | 次强调（图例、辅助标识） |
| `--color-success` / `--color-warning` / `--color-danger` / `--color-info` | 语义状态（验收通过/注意/失败/信息） |
| `--color-*-surface` | 对应状态的浅底（如 `--color-success-surface`） |
| `--color-focus-ring` | 焦点轮廓 |
| `--color-viewport-bg` | 3D 画布背景（随主题切换） |

### 取值

浅色（`:root`）：

| 令牌 | 值 |
| --- | --- |
| `--color-bg` | `#f3f6fa` |
| `--color-surface` | `#ffffff` |
| `--color-surface-subtle` | `#f6f9fc` |
| `--color-surface-strong` | `#eaf0f7` |
| `--color-border` | `#dce3ec` |
| `--color-border-strong` | `#b4c2d1` |
| `--color-text` | `#14202e` |
| `--color-text-muted` | `#566576` |
| `--color-text-subtle` | `#8493a4` |
| `--color-primary` / hover | `#1c5d99` / `#154a7d` |
| `--color-on-primary` | `#ffffff` |
| `--color-accent` | `#0b7a75` |
| `--color-success` / `--color-warning` / `--color-danger` / `--color-info` | `#17663a` / `#9a5d12` / `#b42318` / `#1c5d99` |
| `--color-viewport-bg` | `#eef3f8` |

深色（`[data-theme="dark"]`）：

| 令牌 | 值 |
| --- | --- |
| `--color-bg` | `#0c1118` |
| `--color-surface` | `#151c26` |
| `--color-surface-subtle` | `#1a2330` |
| `--color-surface-strong` | `#23303f` |
| `--color-border` | `#2a3645` |
| `--color-border-strong` | `#3c4c5f` |
| `--color-text` | `#e7eef6` |
| `--color-text-muted` | `#9eb0c2` |
| `--color-text-subtle` | `#6c7e91` |
| `--color-primary` / hover | `#4d9be0` / `#69aeea` |
| `--color-on-primary` | `#08111b` |
| `--color-accent` | `#2bb8ad` |
| `--color-success` / `--color-warning` / `--color-danger` / `--color-info` | `#3ec27e` / `#e0a94c` / `#ef6b5f` / `#4d9be0` |
| `--color-viewport-bg` | `#0f1620` |

状态浅底（`--color-*-surface`）由对应状态色在主题内以低透明度叠加 surface 得到，保证明暗下均有足够对比。

## 排版

字体栈采用 CJK 兼容方案：

```text
--font-ui: "Segoe UI Variable Text","Segoe UI","Inter","SF Pro Text","Roboto",
  ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
  "Microsoft YaHei UI","Microsoft YaHei","Noto Sans CJK SC", sans-serif;
--font-mono: "Cascadia Mono","Cascadia Code","JetBrains Mono","SFMono-Regular",
  Consolas, "Microsoft YaHei UI", monospace;
```

字号阶梯（`--text-*`）与行高（`--leading-*`）：

| 令牌 | 字号 | 用途 |
| --- | --- | --- |
| `--text-xs` | 12px | 标签、计数、徽标 |
| `--text-sm` | 13px | 次要正文、说明 |
| `--text-base` | 14px | 正文 |
| `--text-md` | 15px | 面板标题 |
| `--text-lg` | 18px | 品牌、区块标题 |
| `--text-xl` | 22px | 关键指标数值 |
| `--leading-tight` / `--leading-normal` | 1.25 / 1.55 | 数值/正文 |

字重：常规 400、中等 500、半粗 600、粗 700。`font-synthesis-weight: none`。

## 间距、圆角、阴影、层级、动效

间距阶梯（4px 基准，`--space-*`）：`1=4px 2=8px 3=12px 4=16px 5=20px 6=24px 8=32px`。

圆角（`--radius-*`）：`sm=6px md=10px lg=14px pill=999px`。

阴影（`--shadow-*`）：`sm`（卡片）、`md`（浮层）、`lg`（弹窗/抽屉）。深色主题降低阴影、增强描边对比。

层级（`--z-*`）：`base=0 sticky=10 dropdown=100 overlay=900 toast=1000`。

动效（`--ease-*` / `--dur-*`）：`fast=120ms normal=180ms slow=260ms`，`ease-standard: cubic-bezier(.2,.8,.2,1)`。`prefers-reduced-motion: reduce` 时关闭非必要过渡。

## 组件清单

组件样式集中在 `styles.css`（按区域分节），只引用语义令牌。

| 组件 | 说明 | 状态 |
| --- | --- | --- |
| `Button` / `IconButton` | primary / secondary / ghost / danger 变体 | default / hover / active / disabled / loading / focus-visible |
| `Switch` | 参数补全等开关 | on / off / focus / disabled |
| `Tabs` | 视图模式、侧栏、任务切换 | active / inactive / focus |
| `Panel` + `PanelTitle` | 统一卡片容器与标题（icon + 标题 + 操作区） | — |
| `StatusPill` / `Badge` | 运行/验收状态徽标 | neutral / ok / warn / bad / running |
| `EmptyState` | 上下文空状态（icon + 标题 + 说明 + 可选 CTA） | 默认 / 历史回看 / 错误 |
| `Skeleton` | 加载占位 | 文本行 / 卡片 / 视口 |
| `Toast` | 复制/操作反馈，`aria-live` | success / error / info |
| `Legend` | 3D 颜色条 + 范围 + 单位 | 随场量同步 |
| `Stepper` | 引导式工作流（输入→预检→运行→结果） | upcoming / current / done / failed |
| `Collapsible` | 右栏可折叠分组 | expanded / collapsed |

## 状态规范

- **空态**：每个数据面板在无结果时显示上下文 `EmptyState`，文案明确「下一步做什么」，必要时提供 CTA（如「重跑此请求」「一键体验示例」）。
- **加载态**：运行中用 `Skeleton` 占位结果区与视口；主按钮显示 spinner 并禁用重复提交。
- **错误态**：作业失败在 `Toast` 与验收面板同时呈现；预检失败显示结构化缺参诊断与修正建议。
- **运行态**：贯穿式 `Stepper` 与求解流程面板反映后端阶段事件，状态来源于后端，不由前端合成。

## 主题切换

- 默认跟随系统 `prefers-color-scheme`。
- 顶栏 `ThemeToggle` 提供「明 / 暗 / 跟随系统」三态，用户选择持久化到 `localStorage`（键 `mechagent.studio.theme`）。
- 选择写入 `<html data-theme="light|dark">`；「跟随系统」时移除该属性并监听系统变化。
- 3D 视口背景、网格底、图例随主题令牌切换。

## 响应式断点

| 断点 | 宽度 | 布局 |
| --- | --- | --- |
| `lg` 桌面宽屏 | ≥ 1280px | 左/中/右三栏，右栏整列滚动 |
| `md` 笔记本 | 900–1279px | 左栏 + 主区两栏，检查区移至主区下方两列 |
| `sm` 窄屏/移动 | < 900px | 单列堆叠，左右栏折叠为可展开抽屉/标签，输入与运行按钮 sticky |

所有断点避免横向溢出；3D 画布、报告、检查区有最小/最大尺寸约束。

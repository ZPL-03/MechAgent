# 前端架构

Studio 位于 `apps/mechagent-studio`，使用 React 19、TypeScript、Vite、Three.js 和 lucide-react。后端发布目录为 `packages/mechagent/src/mechagent/ui/static`；源码和构建产物共同进入发布检查。

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `App.tsx` | 运行状态、任务与视图选择、历史、导出操作的协调 |
| `components/` | 请求输入、案例与历史、视口外壳、报告、检查器、顶栏与通用状态 |
| `hooks/` | 启动数据、请求预检和通知生命周期 |
| `lib/api.ts` | 全部 HTTP 请求与错误处理 |
| `lib/` 其他模块 | URL、存储、剪贴板、下载和公开摘要的展示计算 |
| `i18n/` | 界面文案目录、翻译与插值、语言上下文和持久化 |
| `theme/` | 语义令牌、基础样式和主题状态 |
| `ThreeViewport.tsx` | 懒加载三维渲染、场量、相机、交互与资源释放 |
| `types.ts` | 与 Studio 公开响应对应的 TypeScript 类型 |
| `styles.css` | 分区与组件样式、响应式规则 |

界面组件只消费公开摘要，不读取 Agent 内部状态或原始 prompt。报告文本与用户请求属于业务数据，不按 UI 语言替换。纯展示函数不发起网络请求；HTTP 集中在 `api.ts`。

## 生命周期

页面启动读取服务健康、环境诊断、能力与案例。请求变化经过防抖和 AbortController 预检；提交后创建后端作业，轮询状态与阶段事件至终态。任务摘要、可视化和报告由同一个运行响应更新。历史只保留有界摘要和报告，回看历史需要重跑才能恢复完整 3D 场景。

主题与语言使用独立上下文，各自写入本地存储。语言变化只重新计算界面文案，不重新提交请求。三维视口按需绘制，交互、尺寸、模式、场量和主题变化触发刷新；卸载释放渲染资源。

## 构建与验证

```powershell
npm --prefix apps/mechagent-studio ci --no-audit --no-fund
npm --prefix apps/mechagent-studio run build
```

构建先运行 `tsc -b`，再生成静态文件。浏览器验收覆盖中英文、明暗与系统主题、真实作业、视口切换、检查器、下载、历史与窄屏。测试不得用模拟结果代替求解验证。设计规则见[设计系统](design_system.md)，API 与用户操作见[Studio 使用指南](studio_ui.md)。

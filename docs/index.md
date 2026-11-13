# MechAgent 文档

MechAgent 将自然语言工程请求编排为可执行、可追踪的仿真任务。内置发布能力为 CalculiX 结构线弹性静力；平台扩展依赖能力与工具契约，不以单一求解器作为通用内核。

## 阅读入口

| 读者任务 | 文档 |
| --- | --- |
| 安装、配置 Python、CalculiX 与 LLM | [本地开发配置](local_setup.md) |
| 提交请求、操作视口、检查报告与导出 | [Studio 使用指南](studio_ui.md) |
| 判断模型、材料、载荷是否受支持 | [能力与自然语言解析](capabilities.md) |
| 理解产品目标与工程使用边界 | [产品蓝图](product_blueprint.md) |
| 理解包边界、注册 API 和数据模型 | [架构与数据契约](architecture.md) |
| 理解任务状态、Agent 输入输出与错误隔离 | [编排与 Agent 通信](orchestration.md) |
| 理解网格、求解器与后处理 | [求解器、网格与后处理](solver_mesh.md) |
| 运行检查与解读验证证据 | [验证与质量门禁](validation.md) |
| 查看当前架构、能力、证据和发布条件汇总 | [技术报告](technical_report.md) |
| 评估运行、数据、身份和供应链风险 | [威胁模型](MechAgent-threat-model.md) |
| 维护前端模块、语言与主题 | [前端架构](frontend_architecture.md)、[设计系统](design_system.md) |
| 规划能力、后端和平台扩展 | [长周期开发计划书](development_plan.md) |

README 提供项目入口；各专题维护自己的事实、命令与约束，其他页面通过链接引用。开发计划中的候选工具和目标能力不代表已实现能力。

# 脚本目录

脚本用于环境检查、验证、构建、发布和本地运维；稳定的用户能力通过 `mechagent` SDK 或 CLI 暴露。

## 命名

- `check_`：读取环境或配置并返回检查结果。
- `audit_`：读取依赖、许可证或运行状态并写出审计清单。
- `run_`：执行案例、求解器或 smoke 流程。
- `build_`、`generate_`、`index_`：构建可再生成产物。
- `compare_`：比较已有结果，不启动求解器。
- `sign_`、`verify_`：签名或校验发布证据。
- `backup_`、`restore_`、`drill_`、`prune_`：Studio 或对象存储运维。
- `clean_`：清理可再生成文件；扩大到运行证据必须使用显式参数。
- `*_cases.py`：只定义案例数据，不执行流程。

脚本的职责、输入、输出和外部状态范围记录在 [`registry.json`](registry.json)；文档门户中的说明见[`docs/script_catalog.md`](../docs/script_catalog.md)。注册表覆盖 `scripts/` 根目录下的全部 Python 脚本，Abaqus 模板单独列在脚本目录文档中。

## 执行约束

脚本从参数或项目配置读取路径，输出写入新目录，不打印密钥。外部求解器、商业许可证、远端对象存储和签名工具属于环境相关检查；脚本退出码和清单状态必须反映真实执行结果。

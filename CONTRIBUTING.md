# 贡献指南

MechAgent 采用 monorepo 结构，所有 Python 命令统一使用：

```powershell
D:/anaconda3/envs/GPT/python.exe
```

本机 `.env` 提供 `URL`、`API_KEY`、`MODEL_NAME` 和 `CALCULIX_CCX`。
公开配置中的求解器路径为 `${CALCULIX_CCX:-ccx}`，外部环境可直接使用 PATH 中的 `ccx`
或通过环境变量指定 CalculiX 可执行文件。
`.env.example` 保留公开模板值。

公开 PR 便携门禁由 GitHub Actions 执行，使用 Python 3.9、`scripts/check_env.py --profile portable`
和 `pytest -m "not real_solver"`，不依赖本机 D 盘路径、CalculiX 可执行文件或远端 LLM 凭证。
维护者发布前运行本地完整门禁：

```powershell
D:/anaconda3/envs/GPT/python.exe scripts/check_env.py
D:/anaconda3/envs/GPT/python.exe -m ruff format packages tests scripts
D:/anaconda3/envs/GPT/python.exe -m ruff check packages tests scripts
D:/anaconda3/envs/GPT/python.exe -m mypy packages scripts tests
D:/anaconda3/envs/GPT/python.exe -m pytest
D:/anaconda3/envs/GPT/python.exe scripts/run_benchmarks.py
D:/anaconda3/envs/GPT/python.exe scripts/run_natural_language_cases.py
D:/anaconda3/envs/GPT/python.exe scripts/run_llm_smoke.py
D:/anaconda3/envs/GPT/python.exe scripts/build_knowledge.py
D:/anaconda3/envs/GPT/python.exe scripts/index_knowledge.py
D:/anaconda3/envs/GPT/python.exe -m mechagent.cli config validate
D:/anaconda3/envs/GPT/python.exe -m pip check
D:/anaconda3/envs/GPT/python.exe -m build packages/mechagent-core --no-isolation
D:/anaconda3/envs/GPT/python.exe -m build packages/mechagent --no-isolation
D:/anaconda3/envs/GPT/python.exe scripts/check_wheel_install.py
D:/anaconda3/envs/GPT/python.exe -m mkdocs build --strict
D:/anaconda3/envs/GPT/python.exe scripts/clean_artifacts.py
```

真实 CalculiX 求解验证和远端 LLM Agent smoke 验证由本地完整门禁执行。

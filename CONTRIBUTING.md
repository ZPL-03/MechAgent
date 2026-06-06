# 贡献指南

MechAgent 采用 monorepo 结构。贡献者先创建并激活独立 Python 环境，再安装项目依赖：

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e packages/mechagent-core
python -m pip install -e "packages/mechagent[dev,docs]"
```

Conda 环境可使用：

```powershell
conda create -n mechagent python=3.9 -y
conda activate mechagent
python -m pip install --upgrade pip
python -m pip install -e packages/mechagent-core
python -m pip install -e "packages/mechagent[dev,docs]"
```

本机 `.env` 提供 `URL`、`API_KEY`、`MODEL_NAME` 和 `CALCULIX_CCX`。
公开配置中的求解器路径为 `${CALCULIX_CCX:-ccx}`，外部环境可直接使用 PATH 中的 `ccx`
或通过环境变量指定 CalculiX 可执行文件。
`.env.example` 保留公开模板值。

公开 PR 便携门禁由 GitHub Actions 执行，使用 Python 3.9、`scripts/check_env.py --profile portable`
和 `pytest -m "not real_solver"`，不依赖本机 D 盘路径、CalculiX 可执行文件或远端 LLM 凭证。
维护者发布前运行本地完整门禁：

```powershell
python scripts/check_env.py
python -m ruff format packages tests scripts
python -m ruff check packages tests scripts
python -m mypy packages scripts tests
python -m pytest
python scripts/run_benchmarks.py
python scripts/run_natural_language_cases.py
python scripts/run_llm_smoke.py
python scripts/build_knowledge.py
python scripts/index_knowledge.py
python -m mechagent.cli config validate
python -m pip check
python -m build packages/mechagent-core --no-isolation
python -m build packages/mechagent --no-isolation
python scripts/check_wheel_install.py
python -m mkdocs build --strict
python scripts/clean_artifacts.py
```

真实 CalculiX 求解验证和远端 LLM Agent smoke 验证由本地完整门禁执行。

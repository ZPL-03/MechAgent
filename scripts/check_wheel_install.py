"""验证构建后的 wheel 可独立安装和导入。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    """验证 mechagent 与 mechagent-core wheel 的安装后导入行为。"""

    args = _parse_args(argv)
    core_wheel = args.core_wheel or _find_single_wheel(
        REPO_ROOT / "packages" / "mechagent-core" / "dist",
        "mechagent_core-*.whl",
    )
    app_wheel = args.app_wheel or _find_single_wheel(
        REPO_ROOT / "packages" / "mechagent" / "dist",
        "mechagent-*.whl",
    )
    with tempfile.TemporaryDirectory(prefix="mechagent-wheel-check-") as target:
        target_path = Path(target).resolve()
        _install_wheels(target_path, core_wheel, app_wheel)
        result = _run_import_check(target_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _parse_args(argv: Sequence[str] | None) -> Namespace:
    parser = ArgumentParser(description="验证 MechAgent wheel 安装后导入行为。")
    parser.add_argument("--core-wheel", type=Path, default=None, help="mechagent-core wheel 路径。")
    parser.add_argument("--app-wheel", type=Path, default=None, help="mechagent wheel 路径。")
    return parser.parse_args(argv)


def _find_single_wheel(dist_dir: Path, pattern: str) -> Path:
    wheels = sorted(dist_dir.glob(pattern))
    if len(wheels) != 1:
        msg = f"{dist_dir} 下匹配 {pattern} 的 wheel 数量必须为 1，当前为 {len(wheels)}。"
        raise FileNotFoundError(msg)
    return wheels[0].resolve()


def _install_wheels(target: Path, core_wheel: Path, app_wheel: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(target),
            str(core_wheel),
            str(app_wheel),
        ],
        check=True,
    )


def _run_import_check(target: Path) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(target)
    completed = subprocess.run(
        [sys.executable, "-c", _IMPORT_CHECK_CODE],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return cast(dict[str, object], json.loads(completed.stdout))


_IMPORT_CHECK_CODE = r"""
import inspect
import json
from pathlib import Path

import mechagent
import mechagent.core
from mechagent import MechAgent, MechAgentResult
from mechagent.cli import app as cli_app
from mechagent.core.validation import tc01_model_params
from mechagent.orchestrator.workflow import SequentialWorkflow

target = Path(__import__("os").environ["PYTHONPATH"]).resolve()
mechagent_file = Path(mechagent.__file__).resolve()
core_file = Path(mechagent.core.__file__).resolve()
if not mechagent_file.is_relative_to(target):
    raise AssertionError(f"mechagent 未从临时安装目录导入: {mechagent_file}")
if not core_file.is_relative_to(target):
    raise AssertionError(f"mechagent.core 未从临时安装目录导入: {core_file}")

run_signature = str(inspect.signature(MechAgent.run))
if "use_llm_agents" not in run_signature:
    raise AssertionError(run_signature)

app_typed = target / "mechagent" / "py.typed"
core_typed = target / "mechagent" / "core" / "py.typed"
if not app_typed.exists():
    raise AssertionError(f"缺少类型标记: {app_typed}")
if not core_typed.exists():
    raise AssertionError(f"缺少类型标记: {core_typed}")

def single_path(pattern):
    matches = sorted(target.glob(pattern))
    if len(matches) != 1:
        raise AssertionError(f"{pattern} 匹配数量必须为 1，当前为 {len(matches)}")
    return matches[0]

app_dist = single_path("mechagent-*.dist-info")
core_dist = single_path("mechagent_core-*.dist-info")
app_license = app_dist / "licenses" / "LICENSE"
core_license = core_dist / "licenses" / "LICENSE"
if "Apache License" not in app_license.read_text(encoding="utf-8"):
    raise AssertionError(f"许可证内容异常: {app_license}")
if "Apache License" not in core_license.read_text(encoding="utf-8"):
    raise AssertionError(f"许可证内容异常: {core_license}")

app_metadata = (app_dist / "METADATA").read_text(encoding="utf-8")
core_metadata = (core_dist / "METADATA").read_text(encoding="utf-8")
app_entry_points = (app_dist / "entry_points.txt").read_text(encoding="utf-8")
if "Name: mechagent" not in app_metadata:
    raise AssertionError("mechagent wheel 缺少包名元数据。")
if "Requires-Dist: mechagent-core==0.1.0" not in app_metadata:
    raise AssertionError("mechagent wheel 缺少 mechagent-core 精确依赖。")
if "Requires-Dist: langgraph>=0.2" not in app_metadata:
    raise AssertionError("mechagent wheel 缺少 langgraph 依赖。")
if "Requires-Dist: fastapi" not in app_metadata:
    raise AssertionError("mechagent wheel 缺少 fastapi 依赖。")
if "Requires-Dist: uvicorn" not in app_metadata:
    raise AssertionError("mechagent wheel 缺少 uvicorn 依赖。")
if "mechagent = mechagent.cli:app" not in app_entry_points:
    raise AssertionError("mechagent wheel 缺少 CLI entry point。")
if "Name: mechagent-core" not in core_metadata:
    raise AssertionError("mechagent-core wheel 缺少包名元数据。")
if "Requires-Dist: gmsh>=4.13" not in core_metadata:
    raise AssertionError("mechagent-core wheel 缺少 gmsh 依赖。")

studio_index = target / "mechagent" / "ui" / "static" / "index.html"
studio_assets = target / "mechagent" / "ui" / "static" / "assets"
if not studio_index.exists():
    raise AssertionError(f"缺少 Studio HTML: {studio_index}")
if not any(studio_assets.glob("*.js")):
    raise AssertionError(f"缺少 Studio JS 资源: {studio_assets}")
if not any(studio_assets.glob("*.css")):
    raise AssertionError(f"缺少 Studio CSS 资源: {studio_assets}")

params = tc01_model_params()
print(json.dumps({
    "imports_ok": True,
    "mechagent_version": mechagent.__version__,
    "mechagent_file": str(mechagent_file),
    "core_file": str(core_file),
    "run_signature": run_signature,
    "result_class": MechAgentResult.__name__,
    "cli_type": type(cli_app).__name__,
    "workflow_class": SequentialWorkflow.__name__,
    "tc01_case_id": params.case_id,
    "app_py_typed": str(app_typed),
    "core_py_typed": str(core_typed),
    "app_license": str(app_license),
    "core_license": str(core_license),
    "app_dist_info": str(app_dist),
    "core_dist_info": str(core_dist),
    "app_entry_points": str(app_dist / "entry_points.txt"),
    "studio_index": str(studio_index),
    "studio_asset_count": len(list(studio_assets.iterdir())),
}, ensure_ascii=False))
"""


if __name__ == "__main__":
    raise SystemExit(main())

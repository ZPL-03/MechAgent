"""检查 MechAgent 开发环境。"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

EXPECTED_PYTHON = Path("D:/anaconda3/envs/AGENT/python.exe")
CONFIG_PATH = Path("config/mechagent.yaml")
_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")


def main(argv: Sequence[str] | None = None) -> int:
    """执行环境检查。

    Args:
        argv: 命令行参数。

    Returns:
        int: 必需项全部通过时返回 0，否则返回 1。

    Raises:
        无。

    Example:
        >>> isinstance(main([]), int)
        True
    """

    args = _parse_args(argv)
    llm_required = bool(args.require_llm)
    calculix_required = args.profile == "local"
    checks = {
        "python": _check_python(args.profile),
        "executables": _check_executables(args.config),
        "packages": _check_packages(),
        "env": _check_env_file(require_llm=llm_required),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    required_ok = (
        checks["python"]["ok"]
        and checks["packages"]["required_ok"]
        and checks["env"]["required_ok"]
        and (checks["executables"]["configured_ccx_available"] or not calculix_required)
    )
    return 0 if required_ok else 1


def _parse_args(argv: Sequence[str] | None) -> Namespace:
    parser = ArgumentParser(description="检查 MechAgent 开发环境。")
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="运行配置文件路径，默认 config/mechagent.yaml。",
    )
    parser.add_argument(
        "--require-llm",
        action="store_true",
        help="要求 URL、API_KEY、MODEL_NAME 均已配置。",
    )
    parser.add_argument(
        "--profile",
        choices=("local", "portable"),
        default="local",
        help="local 校验固定本机执行器和 CalculiX；portable 校验跨机器 Python 与依赖。",
    )
    return parser.parse_args(argv)


def _check_python(profile: str = "local") -> dict[str, Any]:
    if profile == "portable":
        version_ok = sys.version_info >= (3, 10)
        executable_ok = True
    else:
        version_ok = sys.version_info >= (3, 10)
        executable_ok = _same_path(Path(sys.executable), EXPECTED_PYTHON)
    return {
        "ok": version_ok and executable_ok,
        "executable": sys.executable,
        "executable_ok": executable_ok,
        "version": sys.version,
        "version_ok": version_ok,
        "expected_executable": str(EXPECTED_PYTHON),
        "profile": profile,
    }


def _check_executables(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    configured_ccx = _configured_calculix_path(config_path)
    configured_ccx_path_exists = configured_ccx.exists() if configured_ccx is not None else False
    configured_ccx_on_path = _which_configured_executable(configured_ccx)
    return {
        "git": shutil.which("git"),
        "ccx": shutil.which("ccx"),
        "configured_ccx": str(configured_ccx) if configured_ccx is not None else None,
        "configured_ccx_exists": configured_ccx_path_exists,
        "configured_ccx_on_path": configured_ccx_on_path,
        "configured_ccx_available": configured_ccx_path_exists
        or configured_ccx_on_path is not None,
        "config_path": str(config_path),
        "config_path_exists": config_path.exists(),
    }


def _check_packages() -> dict[str, Any]:
    required = [
        "fastapi",
        "gmsh",
        "httpx",
        "langgraph",
        "pydantic",
        "pytest",
        "rich",
        "ruff",
        "mypy",
        "typer",
        "uvicorn",
        "yaml",
    ]
    optional: list[str] = []
    required_status = {name: importlib.util.find_spec(name) is not None for name in required}
    optional_status = {name: importlib.util.find_spec(name) is not None for name in optional}
    return {
        "required": required_status,
        "optional": optional_status,
        "required_ok": all(required_status.values()),
    }


def _check_env_file(require_llm: bool = False) -> dict[str, Any]:
    env_path = Path(".env")
    keys = {"URL": False, "API_KEY": False, "MODEL_NAME": False}
    tool_keys = {"CALCULIX_CCX": False}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            name = line.split("=", 1)[0].strip()
            if name in keys:
                keys[name] = True
            if name in tool_keys:
                tool_keys[name] = True
    for name in keys:
        keys[name] = keys[name] or bool(os.environ.get(name))
    for name in tool_keys:
        tool_keys[name] = tool_keys[name] or bool(os.environ.get(name))
    keys_ok = all(keys.values())
    return {
        "has_env_file": env_path.exists(),
        "keys": keys,
        "tool_keys": tool_keys,
        "keys_ok": keys_ok,
        "llm_required": require_llm,
        "required_ok": env_path.exists() and keys_ok if require_llm else True,
    }


def _which_configured_executable(configured: Path | None) -> str | None:
    if configured is None:
        return None
    if configured.parent != Path("."):
        return None
    return shutil.which(str(configured))


def _configured_calculix_path(config_path: Path) -> Path | None:
    if not config_path.exists():
        return None
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    solver = data.get("solver")
    if not isinstance(solver, dict):
        return None
    calculix = solver.get("calculix")
    if not isinstance(calculix, dict):
        return None
    value = calculix.get("path")
    if not isinstance(value, str) or not value.strip():
        return None
    expanded = _expand_env_string(value.strip(), _dotenv_values(Path(".env")))
    return Path(expanded)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def _dotenv_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        values[name.strip()] = value.strip()
    return values


def _expand_env_string(value: str, dotenv: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        fallback = match.group(2) or ""
        return os.environ.get(name) or dotenv.get(name) or fallback

    expanded = _ENV_PATTERN.sub(replace, value)
    return os.path.expandvars(os.path.expanduser(expanded))


if __name__ == "__main__":
    raise SystemExit(main())

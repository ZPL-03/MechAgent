"""运行环境诊断。"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

from mechagent.app import MechAgent
from mechagent.core.factory import registered_meshers, registered_solvers
from mechagent.llm import LLMConfig, check_connection
from mechagent.orchestrator.capabilities import all_capabilities


def run_environment_diagnostics(
    config_path: Path = Path("config/mechagent.yaml"),
    *,
    check_llm: bool = False,
) -> dict[str, Any]:
    """检查运行 MechAgent 所需的关键环境。

    Args:
        config_path: 配置文件路径。
        check_llm: 是否调用远端 LLM 进行连接检查。

    Returns:
        dict[str, Any]: 可直接 JSON 序列化的诊断结果。
    """

    checks: list[dict[str, Any]] = [_python_check()]
    config_check, agent = _config_check(config_path)
    checks.append(config_check)
    checks.append(_package_check())
    checks.append(_studio_static_check())
    checks.append(_registry_check())
    if agent is not None:
        checks.append(_solver_check(agent))
        checks.append(_llm_check(agent, check_connection_enabled=check_llm))
    else:
        checks.append(
            _check_item(
                "solver",
                "求解器",
                False,
                True,
                {"reason": "配置未加载，无法解析求解器路径。"},
            )
        )
        checks.append(
            _check_item(
                "llm",
                "LLM 配置",
                not check_llm,
                check_llm,
                {"reason": "配置未加载，无法解析 LLM 设置。"},
            )
        )
    checks.append(_frontend_source_check())
    checks.append(_git_check())
    required = [item for item in checks if item["required"]]
    optional = [item for item in checks if not item["required"]]
    return {
        "ok": all(bool(item["ok"]) for item in required),
        "config_path": str(config_path),
        "checks": checks,
        "summary": {
            "required_passed": sum(1 for item in required if item["ok"]),
            "required_total": len(required),
            "optional_passed": sum(1 for item in optional if item["ok"]),
            "optional_total": len(optional),
        },
    }


def _python_check() -> dict[str, Any]:
    version_ok = sys.version_info >= (3, 9)
    return _check_item(
        "python",
        "Python 运行时",
        version_ok,
        True,
        {
            "executable": sys.executable,
            "version": sys.version.split()[0],
            "minimum": "3.9",
        },
    )


def _config_check(config_path: Path) -> tuple[dict[str, Any], MechAgent | None]:
    try:
        agent = MechAgent.from_config(config_path)
    except Exception as exc:
        return (
            _check_item(
                "config",
                "配置文件",
                False,
                True,
                {"path": str(config_path), "error": str(exc)},
            ),
            None,
        )
    config = agent.config
    return (
        _check_item(
            "config",
            "配置文件",
            True,
            True,
            {
                "path": str(config_path),
                "solver": config.solver.default,
                "mesher": config.mesher.default,
                "orchestrator": config.orchestrator.mode,
            },
        ),
        agent,
    )


def _package_check() -> dict[str, Any]:
    modules = [
        "fastapi",
        "gmsh",
        "httpx",
        "langgraph",
        "pydantic",
        "rich",
        "typer",
        "uvicorn",
        "yaml",
    ]
    status = {name: importlib.util.find_spec(name) is not None for name in modules}
    return _check_item(
        "packages",
        "Python 依赖",
        all(status.values()),
        True,
        {"modules": status},
    )


def _studio_static_check() -> dict[str, Any]:
    static_dir = Path(__file__).parent / "ui" / "static"
    assets_dir = static_dir / "assets"
    js_assets = sorted(item.name for item in assets_dir.glob("*.js")) if assets_dir.exists() else []
    css_assets = (
        sorted(item.name for item in assets_dir.glob("*.css")) if assets_dir.exists() else []
    )
    ok = (static_dir / "index.html").exists() and bool(js_assets) and bool(css_assets)
    return _check_item(
        "studio_static",
        "Studio 静态资源",
        ok,
        True,
        {
            "static_dir": str(static_dir),
            "index_html": (static_dir / "index.html").exists(),
            "js_assets": js_assets,
            "css_assets": css_assets,
        },
    )


def _registry_check() -> dict[str, Any]:
    solvers = registered_solvers()
    meshers = registered_meshers()
    capabilities = all_capabilities()
    return _check_item(
        "registry",
        "能力与工具注册",
        bool(solvers) and bool(meshers) and bool(capabilities),
        True,
        {
            "solvers": list(solvers),
            "meshers": list(meshers),
            "capabilities": [item.capability_id for item in capabilities],
        },
    )


def _solver_check(agent: MechAgent) -> dict[str, Any]:
    configured = agent.config.solver.calculix.path
    resolved = _resolve_executable(configured)
    return _check_item(
        "solver",
        "求解器",
        resolved is not None,
        True,
        {
            "name": agent.config.solver.default,
            "configured": configured,
            "resolved": resolved,
            "num_cpus": agent.config.solver.calculix.num_cpus,
            "timeout": agent.config.solver.calculix.timeout,
        },
    )


def _llm_check(agent: MechAgent, *, check_connection_enabled: bool) -> dict[str, Any]:
    settings = agent.config.llm
    configured = bool(settings.base_url and settings.api_key and settings.model)
    details: dict[str, Any] = {
        "base_url": settings.base_url,
        "model": settings.model,
        "api_key_present": bool(settings.api_key),
        "connection_checked": check_connection_enabled,
    }
    if check_connection_enabled and configured:
        health = check_connection(
            LLMConfig(
                base_url=settings.base_url,
                api_key=settings.api_key,
                model=settings.model,
                temperature=settings.temperature,
            )
        )
        details.update(
            {
                "connection_ok": health.ok,
                "status_code": health.status_code,
                "message": health.message,
            }
        )
        ok = health.ok
    else:
        ok = configured if check_connection_enabled else True
    return _check_item("llm", "LLM 配置", ok, check_connection_enabled, details)


def _frontend_source_check() -> dict[str, Any]:
    package_json = Path("apps/mechagent-studio/package.json")
    npm = shutil.which("npm")
    return _check_item(
        "frontend_source",
        "Studio 前端开发工具",
        package_json.exists() and npm is not None,
        False,
        {
            "package_json": str(package_json),
            "package_json_exists": package_json.exists(),
            "npm": npm,
        },
    )


def _git_check() -> dict[str, Any]:
    return _check_item(
        "git", "Git", shutil.which("git") is not None, False, {"git": shutil.which("git")}
    )


def _resolve_executable(value: str) -> str | None:
    candidate = Path(value)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return str(candidate) if candidate.exists() else None
    return shutil.which(value)


def _check_item(
    key: str,
    label: str,
    ok: bool,
    required: bool,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "ok": bool(ok),
        "required": bool(required),
        "details": details,
    }

"""审计 MechAgent 的 Python 外部依赖。

仓库内的两个本地发行包不发布到 PyPI，不能作为 pip-audit 的解析输入；
脚本从两个 pyproject.toml 收集运行、开发和文档依赖，排除这两个本地包，
再交给 pip-audit 解析其外部依赖及漏洞数据库。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only used on Python 3.10.
    import tomli as tomllib

LOCAL_DISTRIBUTIONS = {"mechagent", "mechagent-core"}
_NAME_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)")


def _distribution_name(requirement: str) -> str:
    match = _NAME_PATTERN.match(requirement.strip())
    if match is None:
        raise ValueError(f"无法解析依赖名称：{requirement}")
    return match.group(1).replace("_", "-").lower()


def _project_requirements(path: Path, *, include_optional: bool) -> list[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    requirements = [str(item).strip() for item in project.get("dependencies", [])]
    if include_optional:
        optional = project.get("optional-dependencies", {})
        for values in optional.values():
            requirements.extend(str(item).strip() for item in values)
    return [
        requirement
        for requirement in requirements
        if requirement and _distribution_name(requirement) not in LOCAL_DISTRIBUTIONS
    ]


def collect_requirements(root: Path, *, include_optional: bool = True) -> list[str]:
    """收集并稳定排序外部依赖，排除仓库内本地发行包。"""

    package_roots = (root / "packages" / "mechagent-core", root / "packages" / "mechagent")
    requirements: set[str] = set()
    for package_root in package_roots:
        requirements.update(
            _project_requirements(
                package_root / "pyproject.toml", include_optional=include_optional
            )
        )
    if not requirements:
        raise ValueError("未找到可审计的 Python 外部依赖。")
    return sorted(requirements, key=lambda item: (_distribution_name(item), item))


def audit(root: Path, *, include_optional: bool, timeout: int, output: Path | None = None) -> int:
    """用临时 requirements 文件调用 pip-audit，并返回其退出码。"""

    requirements = collect_requirements(root, include_optional=include_optional)
    with tempfile.TemporaryDirectory(prefix="mechagent-pip-audit-") as directory:
        requirement_file = Path(directory) / "requirements.txt"
        requirement_file.write_text("\n".join(requirements) + "\n", encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "pip_audit",
            "--requirement",
            str(requirement_file),
            "--format",
            "json",
            "--strict",
            "--desc",
            "on",
            "--timeout",
            str(timeout),
        ]
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            command.extend(["--output", str(output)])
        completed = subprocess.run(command, check=False, text=True)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--timeout", type=int, default=30, help="每个漏洞服务请求的超时时间（秒）。"
    )
    parser.add_argument("--output", type=Path, help="将 JSON 审计结果写入文件。")
    parser.add_argument(
        "--runtime-only",
        action="store_true",
        help="只审计运行依赖；默认还包括开发和文档依赖。",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout 必须为正整数。")
    try:
        root = args.root.resolve()
        output = args.output
        if output is not None and not output.is_absolute():
            output = root / output
        return audit(
            root, include_optional=not args.runtime_only, timeout=args.timeout, output=output
        )
    except FileNotFoundError as exc:
        print(f"依赖审计输入缺失：{exc}", file=sys.stderr)
        return 2
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        print(f"依赖审计配置无效：{exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"依赖审计执行失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

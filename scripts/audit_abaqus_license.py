"""执行 Abaqus/FLEXnet 只读许可证探针并保存脱敏审计清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT / "packages" / "mechagent-core" / "src",
    ROOT / "packages" / "mechagent" / "src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from mechagent.evidence import runtime_provenance  # noqa: E402

_SERVER_UP = re.compile(r"license server .*\bUP\b", re.IGNORECASE)
_VENDOR_UP = re.compile(r"\bABAQUSLM\s*:\s*UP\b", re.IGNORECASE)
_FEATURE_USAGE = re.compile(r"\bUsers of\s+\S+", re.IGNORECASE)


def audit_license(
    launcher: Path,
    *,
    output: Path,
    timeout: float = 60.0,
    probe: tuple[str, ...] = ("licensing", "ru"),
) -> dict[str, Any]:
    """运行只读探针并写出不含原始诊断的许可证审计清单。"""

    if timeout <= 0:
        raise ValueError("timeout 必须为正数。")
    if not probe or any(not item.strip() for item in probe):
        raise ValueError("probe 不能包含空命令片段。")

    command = [str(launcher), *probe]
    started = time.perf_counter()
    timed_out = False
    returncode: int | None = None
    stdout = ""
    stderr = ""
    error: str | None = None
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except FileNotFoundError:
        error = "Abaqus launcher 不存在。"
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = _text_output(exc.stdout)
        stderr = _text_output(exc.stderr)
        error = "许可证探针超时。"
    except OSError as exc:
        error = f"许可证探针无法启动：{type(exc).__name__}。"

    checks = {
        "process_succeeded": returncode == 0 and not timed_out and error is None,
        "license_server_up": bool(_SERVER_UP.search(stdout)),
        "vendor_daemon_up": bool(_VENDOR_UP.search(stdout)),
        "feature_usage_observed": bool(_FEATURE_USAGE.search(stdout)),
    }
    errors: list[str] = []
    if error:
        errors.append(error)
    if returncode not in (None, 0):
        errors.append("许可证探针返回非零状态。")
    if not checks["license_server_up"]:
        errors.append("未检测到许可证服务 UP 状态。")
    if not checks["vendor_daemon_up"]:
        errors.append("未检测到 ABAQUSLM vendor daemon UP 状态。")
    if not checks["feature_usage_observed"]:
        errors.append("未检测到许可证 feature 使用信息。")

    manifest = {
        "schema_version": 1,
        "status": "passed" if not errors else "failed",
        "backend": "abaqus-flexnet",
        "launcher": launcher.name,
        "probe": "licensing ru" if probe == ("licensing", "ru") else "custom",
        "timeout_seconds": timeout,
        "duration_seconds": time.perf_counter() - started,
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout_bytes": len(stdout.encode("utf-8")),
        "stderr_bytes": len(stderr.encode("utf-8")),
        "stdout_sha256": _sha256_text(stdout),
        "stderr_sha256": _sha256_text(stderr),
        "checks": checks,
        "errors": errors,
        "provenance": runtime_provenance(
            tool_commands={"abaqus": launcher}, tool_versions={"abaqus": "unknown"}
        ),
        "artifacts": [],
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(output)
    manifest["manifest"] = str(output)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abaqus", type=Path, required=True, help="Abaqus launcher 路径。")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("mechagent_output/abaqus-license-audit/manifest.json"),
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--probe", nargs="+", default=("licensing", "ru"))
    args = parser.parse_args(argv)
    try:
        report = audit_license(
            args.abaqus,
            output=args.output,
            timeout=args.timeout,
            probe=tuple(args.probe),
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


def _text_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

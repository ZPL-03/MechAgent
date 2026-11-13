"""通过独立 Uvicorn 进程验证 Studio 的真实 HTTP 认证和权限边界。"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mechagent.evidence import atomic_json, verify_manifest, write_manifest
from mechagent.redaction import redact_sensitive_text


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(
    url: str, *, method: str = "GET", token: str | None = None, body: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any], dict[str, str]]:
    data = None
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload, dict(exc.headers.items())


def _write_config(path: Path, database: Path, admin_key: str) -> None:
    settings = {
        "database": str(database),
        "artifact_root": str(database.parent / "objects"),
        "artifact_backend": "filesystem",
        "max_workers": 1,
        "max_queued": 4,
        "auth_required": True,
        "auth_api_key_sha256": hashlib.sha256(admin_key.encode("utf-8")).hexdigest(),
        "auth_subject": "http-admin",
        "auth_organization": "engineering",
        "auth_roles": ["admin"],
        "auth_projects": ["default"],
    }
    path.write_text(
        json.dumps({"studio": settings}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _start_server(config: Path, port: int) -> subprocess.Popen[str]:
    code = (
        "import sys, uvicorn; "
        "from pathlib import Path; "
        "from mechagent.ui.server import create_studio_app; "
        "uvicorn.run(create_studio_app(Path(sys.argv[1])), host='127.0.0.1', "
        "port=int(sys.argv[2]), log_level='warning')"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code, str(config), str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_ready(process: subprocess.Popen[str], base_url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(f"Studio HTTP 进程提前退出：{stderr[-1000:]}")
        try:
            status, _, _ = _request(f"{base_url}/api/health")
            if status == 200:
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    raise TimeoutError("Studio HTTP 服务未在限定时间内就绪。")


def run_smoke(output_dir: Path) -> dict[str, Any]:
    """启动独立 HTTP 服务并返回不含凭据的验证结果。"""

    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"HTTP smoke 输出目录必须为空：{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    config = output_dir / "studio-config.json"
    database = output_dir / "jobs.sqlite3"
    admin_key = secrets.token_urlsafe(32)
    _write_config(config, database, admin_key)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = _start_server(config, port)
    checks: dict[str, bool] = {}
    observations: dict[str, Any] = {"endpoint": base_url, "port": port}
    child_key = ""
    rotated_key = ""
    try:
        _wait_ready(process, base_url)
        status, _, _ = _request(f"{base_url}/api/v1/capabilities")
        checks["missing_credentials_rejected"] = status == 401

        status, _, headers = _request(f"{base_url}/api/v1/capabilities", token=admin_key)
        checks["admin_authentication"] = status == 200
        checks["version_header"] = (
            next(
                (
                    value
                    for key, value in headers.items()
                    if key.lower() == "x-mechagent-api-version"
                ),
                None,
            )
            == "v1"
        )

        status, created, _ = _request(
            f"{base_url}/api/v1/identities",
            method="POST",
            token=admin_key,
            body={
                "subject": "http-runner",
                "organization": "engineering",
                "roles": ["runner"],
                "projects": ["project-a"],
            },
        )
        child_key = str(created.get("api_key", ""))
        checks["identity_creation"] = status == 201 and child_key.startswith("mech_")
        checks["key_not_returned_as_digest"] = "api_key_sha256" not in json.dumps(
            created, ensure_ascii=False
        )

        status, _, _ = _request(f"{base_url}/api/v1/jobs?project_id=project-a", token=child_key)
        checks["project_scope_allowed"] = status == 200
        status, _, _ = _request(f"{base_url}/api/v1/jobs?project_id=project-b", token=child_key)
        checks["project_scope_denied"] = status == 403

        status, rotated, _ = _request(
            f"{base_url}/api/v1/identities/http-runner/rotate",
            method="POST",
            token=admin_key,
        )
        rotated_key = str(rotated.get("api_key", ""))
        checks["key_rotation"] = status == 200 and rotated_key.startswith("mech_")
        status, _, _ = _request(f"{base_url}/api/v1/jobs?project_id=project-a", token=child_key)
        checks["old_key_revoked"] = status == 401
        status, _, _ = _request(f"{base_url}/api/v1/jobs?project_id=project-a", token=rotated_key)
        checks["rotated_key_allowed"] = status == 200

        status, _, _ = _request(
            f"{base_url}/api/v1/identities/http-runner",
            method="DELETE",
            token=admin_key,
        )
        checks["identity_disable"] = status == 200
        status, _, _ = _request(f"{base_url}/api/v1/jobs?project_id=project-a", token=rotated_key)
        checks["disabled_key_revoked"] = status == 401

        status, audit, _ = _request(f"{base_url}/api/v1/audit?project_id=*", token=admin_key)
        events = audit.get("events", []) if isinstance(audit, dict) else []
        actions = {str(item.get("action")) for item in events if isinstance(item, dict)}
        checks["audit_events_visible"] = status == 200 and {
            "identity.create",
            "identity.rotate",
            "identity.disable",
        }.issubset(actions)
        observations["audit_event_count"] = len(events)
    except Exception as exc:
        observations["error"] = redact_sensitive_text(
            str(exc), extra_secrets=(admin_key, child_key, rotated_key)
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    observations["checks"] = checks
    observations["status"] = "passed" if checks and all(checks.values()) else "failed"
    observations["server_stopped"] = process.poll() is not None
    observations.pop("port", None)
    atomic_json(output_dir / "http-smoke.json", observations)
    manifest = write_manifest(output_dir, status=observations["status"], details=observations)
    observations["manifest"] = str(manifest)
    observations["manifest_errors"] = verify_manifest(manifest)
    if observations["manifest_errors"]:
        observations["status"] = "failed"
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_smoke(args.output_dir)
    except (FileExistsError, OSError, RuntimeError, TimeoutError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

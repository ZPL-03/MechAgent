"""MechAgent Studio 服务和可视化测试。"""

from __future__ import annotations

import hashlib
import inspect
import sqlite3
import sys
from pathlib import Path
from time import sleep
from typing import cast

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pytest import CaptureFixture, MonkeyPatch
from typer.testing import CliRunner

from mechagent.cli import app
from mechagent.config import AuthPrincipalSettings, StudioSettings
from mechagent.ui.server import (
    _browser_url,
    _studio_entry_url,
    create_studio_app,
    render_index_html,
    run_studio,
)
from mechagent.ui.visualization import visualizations_from_summary


def test_studio_health_endpoint_reports_config(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("{}", encoding="utf-8")
    client = TestClient(create_studio_app(config_path))

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["product"] == "MechAgent Studio"
    assert payload["config"] == str(config_path)
    assert payload["python_executable"] == sys.executable
    assert isinstance(payload["static_ready"], bool)


def test_studio_rate_limit_returns_429_with_retry_metadata(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("{}", encoding="utf-8")
    settings = StudioSettings(
        database=tmp_path / "jobs.sqlite3",
        rate_limit_requests=1,
        rate_limit_window_seconds=60,
    )

    with TestClient(create_studio_app(config_path, studio_settings=settings)) as client:
        first = client.get("/api/v1/health")
        second = client.get("/api/v1/health")

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "1"
    assert first.headers["X-RateLimit-Remaining"] == "0"
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"
    assert second.json() == {"detail": "请求频率超过当前 Studio 限额。"}


def test_studio_authentication_and_project_isolation(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("{}", encoding="utf-8")
    token = "test-api-key"
    settings = StudioSettings(
        database=tmp_path / "jobs.sqlite3",
        auth_required=True,
        auth_api_key_sha256=hashlib.sha256(token.encode()).hexdigest(),
        auth_subject="alice",
        auth_roles=["runner"],
        auth_projects=["project-a"],
    )
    with TestClient(create_studio_app(config_path, studio_settings=settings)) as client:
        assert client.get("/api/capabilities").status_code == 401
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/capabilities", headers=headers).status_code == 200
        denied = client.post(
            "/api/jobs",
            headers=headers,
            json={"request": "unsupported", "project_id": "project-b"},
        )
        assert denied.status_code == 403
        submitted = client.post(
            "/api/jobs",
            headers=headers,
            json={"request": "unsupported", "project_id": "project-a"},
        )
        assert submitted.status_code == 202
        jobs = client.get("/api/jobs?project_id=project-a", headers=headers)
        assert jobs.status_code == 200
        assert jobs.json()["jobs"][0]["project_id"] == "project-a"
        assert client.get("/api/audit?project_id=project-a", headers=headers).status_code == 403

    admin_settings = settings.model_copy(update={"auth_roles": ["admin"]})
    with TestClient(create_studio_app(config_path, studio_settings=admin_settings)) as client:
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/audit?project_id=project-a", headers=headers).status_code == 200


def test_studio_metrics_are_scoped_and_persistent_without_request_data(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("{}", encoding="utf-8")
    token = "metrics-api-key"
    digest = hashlib.sha256(token.encode()).hexdigest()
    settings = StudioSettings(
        database=tmp_path / "jobs.sqlite3",
        auth_required=True,
        auth_api_key_sha256=digest,
        auth_subject="alice",
        auth_roles=["runner"],
        auth_projects=["project-a"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_studio_app(config_path, studio_settings=settings)) as client:
        submitted = client.post(
            "/api/v1/jobs",
            headers=headers,
            json={"request": "包含不应出现在指标中的请求文本", "project_id": "project-a"},
        )
        assert submitted.status_code == 202
        scoped = client.get("/api/v1/metrics?project_id=project-a", headers=headers)
        assert scoped.status_code == 200
        metrics = scoped.json()["metrics"]
        assert metrics["scope"] == {
            "organization": "local",
            "project_id": "project-a",
            "owner": "alice",
        }
        assert metrics["jobs"]["total"] >= 1
        assert "包含不应出现在指标中的请求文本" not in scoped.text
        assert client.get("/api/v1/metrics", headers=headers).status_code == 403

    admin = settings.model_copy(update={"auth_roles": ["admin"], "auth_projects": ["default"]})
    with TestClient(create_studio_app(config_path, studio_settings=admin)) as client:
        all_metrics = client.get("/api/v1/metrics", headers=headers)
        assert all_metrics.status_code == 200
        assert all_metrics.json()["metrics"]["jobs"]["total"] >= 1


def test_studio_rejects_submission_when_storage_quota_is_exceeded(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("{}", encoding="utf-8")
    settings = StudioSettings(database=tmp_path / "jobs.sqlite3", max_storage_bytes=1024)

    with TestClient(create_studio_app(config_path, studio_settings=settings)) as client:
        response = client.post("/api/v1/jobs", json={"request": "quota"})

    assert response.status_code == 507
    assert "存储配额" in response.json()["detail"]


def test_studio_principal_directory_selects_subject_and_scope(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("{}", encoding="utf-8")
    token = "directory-api-key"
    settings = StudioSettings(
        database=tmp_path / "jobs.sqlite3",
        auth_required=True,
        auth_principals=[
            AuthPrincipalSettings(
                subject="bob",
                api_key_sha256=hashlib.sha256(token.encode()).hexdigest(),
                organization="engineering",
                roles=["viewer"],
                projects=["project-b"],
            )
        ],
    )
    with TestClient(create_studio_app(config_path, studio_settings=settings)) as client:
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/jobs?project_id=project-b", headers=headers).status_code == 200
        assert client.get("/api/jobs?project_id=project-a", headers=headers).status_code == 403


def test_studio_managed_identity_directory_is_scoped_and_rotatable(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("{}", encoding="utf-8")
    admin_token = "organization-admin-token"
    settings = StudioSettings(
        database=tmp_path / "jobs.sqlite3",
        auth_required=True,
        auth_api_key_sha256=hashlib.sha256(admin_token.encode()).hexdigest(),
        auth_subject="org-admin",
        auth_organization="engineering",
        auth_roles=["admin"],
        auth_projects=["default"],
    )
    with TestClient(create_studio_app(config_path, studio_settings=settings)) as client:
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        created = client.post(
            "/api/v1/identities",
            headers=admin_headers,
            json={
                "subject": "analyst",
                "organization": "engineering",
                "roles": ["runner"],
                "projects": ["project-a"],
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )
        assert created.status_code == 201
        generated = created.json()["api_key"]
        assert generated.startswith("mech_")
        assert "api_key_sha256" not in created.text
        with sqlite3.connect(settings.database) as connection:
            database_dump = " ".join(
                str(row) for row in connection.execute("SELECT * FROM identities")
            )
        assert generated not in database_dump
        assert hashlib.sha256(generated.encode()).hexdigest() in database_dump
        assert (
            client.get("/api/v1/identities", headers=admin_headers).json()["identities"][0][
                "organization"
            ]
            == "engineering"
        )
        user_headers = {"Authorization": f"Bearer {generated}"}
        assert (
            client.get("/api/v1/jobs?project_id=project-a", headers=user_headers).status_code == 200
        )
        assert (
            client.get("/api/v1/jobs?project_id=project-b", headers=user_headers).status_code == 403
        )
        listed = client.get("/api/v1/identities", headers=admin_headers).json()["identities"]
        assert listed[0]["expires_at"] == "2099-01-01T00:00:00+00:00"
        preserved = client.patch(
            "/api/v1/identities/analyst",
            headers=admin_headers,
            json={
                "organization": "engineering",
                "roles": ["viewer"],
                "projects": ["project-a"],
            },
        )
        assert preserved.status_code == 200
        assert preserved.json()["identity"]["expires_at"] == "2099-01-01T00:00:00+00:00"
        cleared = client.patch(
            "/api/v1/identities/analyst",
            headers=admin_headers,
            json={
                "organization": "engineering",
                "roles": ["runner"],
                "projects": ["project-a"],
                "expires_at": None,
            },
        )
        assert cleared.status_code == 200
        assert cleared.json()["identity"]["expires_at"] is None
        assert (
            client.post(
                "/api/v1/identities",
                headers=admin_headers,
                json={
                    "subject": "other-org",
                    "organization": "other",
                    "roles": ["viewer"],
                    "projects": ["project-a"],
                },
            ).status_code
            == 403
        )
        expired = client.post(
            "/api/v1/identities",
            headers=admin_headers,
            json={
                "subject": "expired",
                "organization": "engineering",
                "roles": ["viewer"],
                "projects": ["project-a"],
                "expires_at": "2020-01-01T00:00:00Z",
            },
        )
        assert expired.status_code == 422
        assert "expires_at" in expired.json()["detail"]
        rotated = client.post("/api/v1/identities/analyst/rotate", headers=admin_headers)
        assert rotated.status_code == 200
        assert (
            client.get("/api/v1/jobs?project_id=project-a", headers=user_headers).status_code == 401
        )
        new_headers = {"Authorization": f"Bearer {rotated.json()['api_key']}"}
        assert (
            client.get("/api/v1/jobs?project_id=project-a", headers=new_headers).status_code == 200
        )
        assert client.delete("/api/v1/identities/analyst", headers=admin_headers).status_code == 200
        assert (
            client.get("/api/v1/jobs?project_id=project-a", headers=new_headers).status_code == 401
        )


def test_studio_cross_organization_admin_requires_explicit_target(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("{}", encoding="utf-8")
    token = "global-admin-token"
    settings = StudioSettings(
        database=tmp_path / "jobs.sqlite3",
        auth_required=True,
        auth_api_key_sha256=hashlib.sha256(token.encode()).hexdigest(),
        auth_subject="global-admin",
        auth_organization="*",
        auth_roles=["admin"],
        auth_projects=["default"],
    )
    with TestClient(create_studio_app(config_path, studio_settings=settings)) as client:
        headers = {"Authorization": f"Bearer {token}"}
        assert (
            client.post(
                "/api/v1/jobs", headers=headers, json={"request": "unsupported"}
            ).status_code
            == 400
        )
        created = client.post(
            "/api/v1/jobs",
            headers=headers,
            json={"request": "unsupported", "organization": "engineering"},
        )
        assert created.status_code == 202
        job_id = created.json()["job_id"]
        assert (
            client.get("/api/v1/jobs?organization=engineering", headers=headers).status_code == 200
        )
        assert client.get(f"/api/v1/jobs/{job_id}", headers=headers).status_code == 200


def test_studio_v1_routes_are_stable_and_legacy_routes_are_deprecated(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("{}", encoding="utf-8")
    client = TestClient(create_studio_app(config_path))

    stable = client.get("/api/v1/health")
    legacy = client.get("/api/health")

    assert stable.status_code == 200
    assert stable.headers["X-MechAgent-API-Version"] == "v1"
    assert legacy.status_code == 200
    assert legacy.headers["Deprecation"] == "true"
    assert legacy.headers["Sunset"] == "2027-06-30"
    assert client.post("/api/v1/jobs", json={"request": "   "}).status_code == 400


def test_studio_diagnostics_endpoint_reuses_environment_doctor(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    captured: list[tuple[Path, bool]] = []

    def fake_diagnostics(config: Path, *, check_llm: bool) -> dict[str, object]:
        captured.append((config, check_llm))
        return {
            "ok": True,
            "config_path": str(config),
            "checks": [
                {
                    "key": "python",
                    "label": "Python 运行时",
                    "ok": True,
                    "required": True,
                    "details": {"version": "3.9"},
                }
            ],
            "summary": {
                "required_passed": 1,
                "required_total": 1,
                "optional_passed": 0,
                "optional_total": 0,
            },
        }

    config_path = tmp_path / "mechagent.yaml"
    monkeypatch.setattr("mechagent.ui.server.run_environment_diagnostics", fake_diagnostics)
    client = TestClient(create_studio_app(config_path))

    default_response = client.get("/api/diagnostics")
    llm_response = client.get("/api/diagnostics?llm=true")

    assert default_response.status_code == 200
    assert llm_response.status_code == 200
    assert default_response.json()["summary"]["required_passed"] == 1
    assert captured == [(config_path, False), (config_path, True)]


def test_studio_run_rejects_empty_request(tmp_path: Path) -> None:
    client = TestClient(create_studio_app(tmp_path / "mechagent.yaml"))

    response = client.post("/api/run", json={"request": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "请求不能为空。"


def test_studio_jobs_reject_empty_request(tmp_path: Path) -> None:
    client = TestClient(create_studio_app(tmp_path / "mechagent.yaml"))

    response = client.post("/api/jobs", json={"request": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "请求不能为空。"


def test_studio_capabilities_endpoint_exposes_registered_examples(tmp_path: Path) -> None:
    client = TestClient(create_studio_app(tmp_path / "mechagent.yaml"))

    response = client.get("/api/capabilities")

    assert response.status_code == 200
    payload = response.json()
    capabilities = payload["capabilities"]
    structural = next(item for item in capabilities if item["capability_id"] == "structural_static")
    assert structural["title"] == "结构静力分析"
    assert structural["solver_name"] == "calculix"
    assert structural["mesher_name"] == "calculix-inp"
    assert structural["model_case_ids"] == [
        "STATIC-BEAM",
        "STATIC-PLATE",
        "STATIC-PERFORATED-PLATE",
        "STATIC-SOLID",
    ]
    assert any("圆孔" in item for item in structural["example_requests"])
    assert any("偏心圆孔" in item for item in structural["example_requests"])


def test_studio_examples_endpoint_exposes_full_catalog(tmp_path: Path) -> None:
    client = TestClient(create_studio_app(tmp_path / "mechagent.yaml"))

    response = client.get("/api/examples")

    assert response.status_code == 200
    payload = response.json()
    examples = payload["examples"]
    assert len(examples) == 28
    assert examples[0]["example_id"] == "SC-01"
    assert examples[0]["capability_id"] == "structural_static"
    assert examples[0]["model_case_id"] == "STATIC-BEAM"
    assert any(item["model_case_id"] == "STATIC-SOLID" for item in examples)
    assert any("偏心圆孔" in item["title"] for item in examples)
    assert any("多孔" in item["title"] for item in examples)
    assert any("长圆槽孔" in item["title"] for item in examples)


def test_studio_inspect_endpoint_returns_preflight(tmp_path: Path) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text("{}", encoding="utf-8")
    client = TestClient(create_studio_app(config_path))

    response = client.post(
        "/api/inspect",
        json={
            "request": (
                "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力静力分析"
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ready"] is True
    assert payload["tasks"][0]["capability_id"] == "structural_static"
    assert payload["tasks"][0]["geometry_type"] == "beam"
    assert payload["tasks"][0]["missing_fields"] == []


def test_studio_inspect_rejects_empty_request(tmp_path: Path) -> None:
    client = TestClient(create_studio_app(tmp_path / "mechagent.yaml"))

    response = client.post("/api/inspect", json={"request": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "请求不能为空。"


def test_studio_run_endpoint_uses_thread_pool(tmp_path: Path) -> None:
    studio_app = create_studio_app(tmp_path / "mechagent.yaml")
    route = next(
        route
        for route in studio_app.routes
        if isinstance(route, APIRoute) and route.path == "/api/run"
    )

    assert not inspect.iscoroutinefunction(route.endpoint)


def test_studio_sync_run_uses_real_worker(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    settings = StudioSettings(database=tmp_path / "jobs.sqlite3")
    with TestClient(create_studio_app(config, studio_settings=settings)) as client:
        response = client.post("/api/run", json={"request": "不支持的仿真请求"})
        assert response.status_code == 200
        assert response.json()["success"] is False
        assert response.json()["summary"]["errors"]
        assert len(client.get("/api/jobs").json()["jobs"]) == 1


def test_studio_jobs_persist_and_expose_retry_evidence(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    settings = StudioSettings(database=tmp_path / "jobs.sqlite3")
    with TestClient(create_studio_app(config, studio_settings=settings)) as client:
        headers = {"Idempotency-Key": "test-request"}
        response = client.post("/api/jobs", json={"request": "不支持的仿真请求"}, headers=headers)
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert (
            client.post("/api/jobs", json={"request": "不支持的仿真请求"}, headers=headers).json()[
                "job_id"
            ]
            == job_id
        )
        assert (
            client.post("/api/jobs", json={"request": "其他请求"}, headers=headers).status_code
            == 409
        )
        for _ in range(300):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"succeeded", "failed", "interrupted"}:
                break
            sleep(0.05)
        assert job["status"] == "failed", job
        assert job["result"]["summary"]["errors"]
        assert job["events"]
        assert client.get(f"/api/jobs/{job_id}/evidence").json()["valid"]
        assert client.get("/api/jobs?limit=101").status_code == 422
        assert client.get("/api/jobs/unknown").status_code == 404
        assert client.get("/api/unknown").status_code == 404
    with TestClient(create_studio_app(config, studio_settings=settings)) as client:
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "failed"
        retry = client.post(f"/api/jobs/{job_id}/retry").json()
        assert retry["job_id"] != job_id
        assert retry["parent_job_id"] == job_id
        cancelled = client.post(f"/api/jobs/{retry['job_id']}/cancel")
        assert cancelled.status_code == 202


def test_studio_static_fallback_html_is_available() -> None:
    html = render_index_html()

    assert "MechAgent Studio 静态资源未构建" in html
    assert "npm --prefix apps/mechagent-studio ci --no-audit --no-fund" in html
    assert "python -m mechagent.cli studio" in html


def test_studio_browser_url_uses_loopback_for_wildcard_host() -> None:
    assert _browser_url("0.0.0.0", 8765) == "http://127.0.0.1:8765"
    assert _browser_url("::", 8765) == "http://127.0.0.1:8765"
    assert _browser_url("::1", 8765) == "http://[::1]:8765"


def test_studio_entry_url_encodes_request_llm_and_view() -> None:
    url = _studio_entry_url(
        "0.0.0.0",
        8765,
        request="求解 偏心圆孔薄板",
        use_llm_agents=True,
        view="result",
    )

    assert url == (
        "http://127.0.0.1:8765/studio?"
        "request=%E6%B1%82%E8%A7%A3+%E5%81%8F%E5%BF%83%E5%9C%86%E5%AD%94"
        "%E8%96%84%E6%9D%BF&llm=1&view=result"
    )


def test_studio_entry_url_omits_empty_query_for_default_state() -> None:
    assert _studio_entry_url("127.0.0.1", 8765) == "http://127.0.0.1:8765"


def test_studio_entry_url_preserves_default_view_with_request() -> None:
    assert (
        _studio_entry_url("127.0.0.1", 8765, request="求解偏心圆孔薄板")
        == "http://127.0.0.1:8765/studio?"
        "request=%E6%B1%82%E8%A7%A3%E5%81%8F%E5%BF%83%E5%9C%86%E5%AD%94"
        "%E8%96%84%E6%9D%BF&view=geometry"
    )


def test_studio_entry_url_supports_explicit_auto_run() -> None:
    assert (
        _studio_entry_url(
            "127.0.0.1",
            8765,
            request="求解偏心圆孔薄板",
            auto_run=True,
        )
        == "http://127.0.0.1:8765/studio?"
        "request=%E6%B1%82%E8%A7%A3%E5%81%8F%E5%BF%83%E5%9C%86%E5%AD%94"
        "%E8%96%84%E6%9D%BF&view=geometry&run=1"
    )


def test_studio_entry_url_rejects_auto_run_without_request() -> None:
    with pytest.raises(ValueError, match="自动运行"):
        _studio_entry_url("127.0.0.1", 8765, auto_run=True)


def test_run_studio_prints_bind_and_browser_urls(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_uvicorn_run(_app: object, *, host: str, port: int) -> None:
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr("mechagent.ui.server.uvicorn.run", fake_uvicorn_run)
    monkeypatch.setattr(
        "mechagent.ui.server.webbrowser.open",
        lambda url: captured.update({"browser_url": url}),
    )

    run_studio(
        host="0.0.0.0",
        port=9876,
        config=tmp_path / "mechagent.yaml",
        open_browser=True,
        request="求解偏心圆孔薄板",
        use_llm_agents=True,
        view="mesh",
        auto_run=True,
    )

    output = capsys.readouterr().out
    assert "MechAgent Studio 服务: http://0.0.0.0:9876" in output
    assert (
        "浏览器入口: http://127.0.0.1:9876/studio?"
        "request=%E6%B1%82%E8%A7%A3%E5%81%8F%E5%BF%83%E5%9C%86%E5%AD%94"
        "%E8%96%84%E6%9D%BF&llm=1&view=mesh&run=1"
    ) in output
    assert captured == {
        "browser_url": (
            "http://127.0.0.1:9876/studio?"
            "request=%E6%B1%82%E8%A7%A3%E5%81%8F%E5%BF%83%E5%9C%86%E5%AD%94"
            "%E8%96%84%E6%9D%BF&llm=1&view=mesh&run=1"
        ),
        "host": "0.0.0.0",
        "port": 9876,
    }


def test_cli_studio_delegates_to_server(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_studio(
        *,
        host: str,
        port: int,
        config: Path,
        open_browser: bool,
        request: str | None,
        use_llm_agents: bool,
        view: str,
        auto_run: bool,
    ) -> None:
        captured.update(
            {
                "host": host,
                "port": port,
                "config": config,
                "open_browser": open_browser,
                "request": request,
                "use_llm_agents": use_llm_agents,
                "view": view,
                "auto_run": auto_run,
            }
        )

    monkeypatch.setattr("mechagent.cli.run_studio", fake_run_studio)
    runner = CliRunner()
    config_path = tmp_path / "mechagent.yaml"

    result = runner.invoke(
        app,
        [
            "studio",
            "--config",
            str(config_path),
            "--host",
            "0.0.0.0",
            "--port",
            "9876",
            "--open-browser",
            "--request",
            "求解偏心圆孔薄板",
            "--llm-agents",
            "--view",
            "result",
            "--auto-run",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "host": "0.0.0.0",
        "port": 9876,
        "config": config_path,
        "open_browser": True,
        "request": "求解偏心圆孔薄板",
        "use_llm_agents": True,
        "view": "result",
        "auto_run": True,
    }


def test_cli_studio_rejects_invalid_view() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["studio", "--view", "bad-view"])

    assert result.exit_code != 0
    assert "bad-view" in result.output


def test_cli_studio_rejects_auto_run_without_request() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["studio", "--auto-run"])

    assert result.exit_code != 0
    assert "--auto-run" in result.output


def test_visualizations_require_real_mesh_and_solver_fields() -> None:
    visuals = visualizations_from_summary(
        {
            "tasks": [
                _task_summary("TASK_1", "beam", {"length": 1000.0}),
                _task_summary("TASK_2", "plate", {"length": 300.0, "width": 200.0}),
                _task_summary(
                    "TASK_3",
                    "solid",
                    {"length": 200.0, "width": 20.0, "height": 20.0},
                ),
            ]
        }
    )

    assert [item.kind for item in visuals] == ["message", "message", "message"]
    for item in visuals:
        assert item.svg.startswith("<svg")
        assert item.task_id.startswith("TASK_")
        assert item.scene is None
        assert "缺少真实网格文件" in item.caption


def test_visualization_rejects_mesh_without_solver_fields(tmp_path: Path) -> None:
    input_file = tmp_path / "mesh_only.inp"
    input_file.write_text(
        "\n".join(
            [
                "*NODE",
                "1, 0, 0, 0",
                "2, 100, 0, 0",
                "*ELEMENT, TYPE=B31, ELSET=EALL",
                "1, 1, 2",
            ]
        ),
        encoding="utf-8",
    )
    task = _task_summary("TASK_1", "beam", {"length": 100.0})
    solver_result = cast(dict[str, object], task["solver_result"])
    visual = visualizations_from_summary(
        {
            "tasks": [
                {
                    **task,
                    "mesh_result": {"mesh_file": str(input_file)},
                    "solver_result": {
                        **solver_result,
                        "output_files": [str(input_file)],
                    },
                }
            ]
        }
    )[0]

    assert visual.kind == "message"
    assert visual.scene is None
    assert "缺少真实求解场量" in visual.caption


def test_visualization_scene_exposes_displacement_and_stress_fields(tmp_path: Path) -> None:
    input_file = tmp_path / "field_case.inp"
    input_file.write_text(
        "\n".join(
            [
                "*NODE",
                "1, 0, 0, 0",
                "2, 100, 0, 0",
                "3, 100, 50, 0",
                "4, 0, 50, 0",
                "*ELEMENT, TYPE=S4, ELSET=EALL",
                "1, 1, 2, 3, 4",
            ]
        ),
        encoding="utf-8",
    )
    frd_file = tmp_path / "field_case.frd"
    frd_file.write_text(
        "\n".join(
            [
                " -4  DISP        4    1",
                _frd_line(1, 0.0, 0.0, 0.0),
                _frd_line(2, 0.1, 0.0, -1.0),
                _frd_line(3, 0.1, 0.0, -2.0),
                _frd_line(4, 0.0, 0.0, -1.0),
                " -3",
                " -4  STRESS      6    1",
                _frd_line(1, 10.0, 4.0, 1.0, 2.0, 0.5, 0.25),
                _frd_line(2, 12.0, 5.0, 1.5, 2.2, 0.5, 0.25),
                _frd_line(3, 15.0, 6.0, 2.0, 2.5, 0.5, 0.25),
                _frd_line(4, 11.0, 5.0, 1.2, 2.1, 0.5, 0.25),
                " -3",
            ]
        ),
        encoding="utf-8",
    )

    base_task = _task_summary("TASK_1", "plate", {"length": 100.0, "width": 50.0})
    base_solver_result = cast(dict[str, object], base_task["solver_result"])
    visual = visualizations_from_summary(
        {
            "tasks": [
                {
                    **base_task,
                    "mesh_result": {"mesh_file": str(input_file)},
                    "solver_result": {
                        **base_solver_result,
                        "output_files": [str(input_file), str(frd_file)],
                    },
                }
            ]
        }
    )[0]

    assert visual.scene is not None
    fields = {field["key"]: field for field in visual.scene["fields"]}
    assert {"u_mag", "ux", "uy", "uz", "s_mises", "sxx", "syy", "szz", "sxy", "syz", "sxz"} <= set(
        fields
    )
    assert fields["s_mises"]["kind"] == "stress"
    assert fields["s_mises"]["unit"] == "MPa"
    assert visual.scene["nodes"][2]["fields"]["uz"] == -2.0
    assert visual.scene["nodes"][2]["fields"]["sxx"] == 15.0


def test_visualization_scene_aligns_shell_derived_result_nodes(tmp_path: Path) -> None:
    input_file = tmp_path / "shell_case.inp"
    input_file.write_text(
        "\n".join(
            [
                "*NODE",
                "1, 0, 0, 0",
                "2, 100, 0, 0",
                "3, 100, 50, 0",
                "4, 0, 50, 0",
                "*ELEMENT, TYPE=S4, ELSET=EALL",
                "1, 1, 2, 3, 4",
            ]
        ),
        encoding="utf-8",
    )
    frd_file = tmp_path / "shell_case.frd"
    frd_file.write_text(
        "\n".join(
            [
                " -4  DISP        4    1",
                _frd_line(5, 0.0, 0.0, -1.0),
                _frd_line(6, 0.0, 0.0, -3.0),
                _frd_line(7, 0.0, 0.0, -2.0),
                _frd_line(8, 0.0, 0.0, -4.0),
                _frd_line(9, 0.0, 0.0, -5.0),
                _frd_line(10, 0.0, 0.0, -7.0),
                _frd_line(11, 0.0, 0.0, -6.0),
                _frd_line(12, 0.0, 0.0, -8.0),
                " -3",
                " -4  STRESS      6    1",
                _frd_line(5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                _frd_line(6, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                _frd_line(7, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                _frd_line(8, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                _frd_line(9, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                _frd_line(10, 9.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                _frd_line(11, 6.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                _frd_line(12, 8.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                " -3",
            ]
        ),
        encoding="utf-8",
    )

    base_task = _task_summary("TASK_1", "plate", {"length": 100.0, "width": 50.0})
    model_params = cast(dict[str, object], base_task["model_params"])
    model_params["loads"] = [
        {"type": "pressure", "magnitude": 0.01, "region": "top_surface", "direction": [0, 0, -1]}
    ]
    model_params["bcs"] = [
        {"type": "simply_supported", "region": "all_edges", "dofs": ["uz"], "values": [0.0]}
    ]
    base_solver_result = cast(dict[str, object], base_task["solver_result"])
    visual = visualizations_from_summary(
        {
            "tasks": [
                {
                    **base_task,
                    "mesh_result": {"mesh_file": str(input_file)},
                    "solver_result": {
                        **base_solver_result,
                        "output_files": [str(input_file), str(frd_file)],
                    },
                }
            ]
        }
    )[0]

    assert visual.scene is not None
    nodes = {node["id"]: node for node in visual.scene["nodes"]}
    assert nodes[1]["fields"]["uz"] == -2.0
    assert nodes[3]["fields"]["uz"] == -6.0
    assert nodes[3]["fields"]["sxx"] == 9.0
    assert visual.scene["loads"][0]["region"] == "top_surface"
    assert visual.scene["boundary_conditions"][0]["region"] == "all_edges"


def _beam_summary() -> dict[str, object]:
    return {
        "success": True,
        "tasks": [
            _task_summary(
                "TASK_1",
                "beam",
                {"length": 1000.0, "width": 20.0, "height": 40.0},
            )
        ],
        "errors": [],
    }


def _task_summary(
    task_id: str,
    geometry_type: str,
    dimensions: dict[str, float],
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "title": "结构静力分析",
        "model_params": {
            "geometry": {
                "type": geometry_type,
                "dimensions": dimensions,
            }
        },
        "mesh_result": {},
        "solver_result": {
            "success": True,
            "quantity": "displacement",
            "unit": "mm",
            "predicted": 1.25,
            "reference": 1.24,
            "relative_error": 0.008,
            "tolerance": 0.02,
            "passed": True,
            "verification_status": "passed",
            "output_files": [],
        },
    }


def _frd_line(node_id: int, *values: float) -> str:
    return f" -1{node_id:10d}" + "".join(f"{value:12.5E}" for value in values)

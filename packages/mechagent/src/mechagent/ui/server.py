"""MechAgent Studio 本地服务。"""

from __future__ import annotations

import json
import sys
import time
import webbrowser
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from mechagent import MechAgent, __version__
from mechagent.config import MechAgentConfig, StudioSettings
from mechagent.diagnostics import run_environment_diagnostics
from mechagent.evidence import verify_manifest, write_manifest
from mechagent.examples import example_payloads
from mechagent.orchestrator.capabilities import all_capabilities
from mechagent.runtime.artifacts import create_artifact_store
from mechagent.runtime.auth import (
    ApiKeyAuthenticator,
    AuthenticationError,
    AuthorizationError,
    Principal,
    ensure_authorized,
)
from mechagent.runtime.manager import JobManager
from mechagent.runtime.store import (
    TERMINAL,
    IdempotencyError,
    JobStore,
    QueueFullError,
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STUDIO_VIEW_MODES = {"geometry", "mesh", "result"}


class StudioRunRequest(BaseModel):
    """Studio 单次运行请求。"""

    model_config = ConfigDict(extra="forbid")
    request: str = Field(default="", max_length=20000, description="自然语言仿真请求。")
    use_llm_agents: bool = Field(default=False, description="是否启用远端参数补全链路。")
    project_id: str = Field(
        default="default",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )


def create_studio_app(
    config: Path = Path("config/mechagent.yaml"), *, studio_settings: StudioSettings | None = None
) -> FastAPI:
    """创建本机单用户 ASGI 应用；生命周期启动持久队列调度。"""
    config_path = config
    if studio_settings is not None:
        configured_settings = studio_settings
    elif config_path.is_file():
        configured_settings = MechAgent.from_config(config_path).config.studio
    else:
        configured_settings = MechAgentConfig().studio
    configured_principal = Principal(
        subject=configured_settings.auth_subject,
        roles=frozenset(configured_settings.auth_roles),
        project_ids=frozenset(configured_settings.auth_projects),
    )
    directory = tuple(
        (
            item.api_key_sha256,
            Principal(
                subject=item.subject,
                roles=frozenset(item.roles),
                project_ids=frozenset(item.projects),
                organization=item.organization,
            ),
        )
        for item in configured_settings.auth_principals
    )
    authenticator = ApiKeyAuthenticator(configured_settings.auth_api_key_sha256, directory)
    manager: JobManager | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal manager
        settings = configured_settings
        manager = JobManager(
            JobStore(
                settings.database,
                artifact_store=create_artifact_store(
                    settings.artifact_backend,
                    root=settings.artifact_root or settings.database.parent / "objects",
                    bucket=settings.artifact_s3_bucket,
                    prefix=settings.artifact_s3_prefix,
                ),
                max_active_jobs_per_project=settings.max_active_jobs_per_project,
                max_result_bytes=settings.max_result_bytes,
            ),
            settings,
        )
        manager.start()
        try:
            yield
        finally:
            manager.close()

    app = FastAPI(
        title="MechAgent Studio API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def api_compatibility_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            configured_settings.auth_required
            and request.url.path.startswith("/api")
            and request.url.path not in {"/api/health", "/api/docs", "/api/openapi.json"}
        ):
            authorization = request.headers.get("Authorization", "")
            token = (
                authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
            )
            try:
                request.state.principal = authenticator.authenticate(token, configured_principal)
            except AuthenticationError as exc:
                return Response(
                    content=json.dumps({"detail": str(exc)}, ensure_ascii=False),
                    status_code=401,
                    media_type="application/json",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        else:
            request.state.principal = configured_principal
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/v1/"):
            response.headers["X-MechAgent-API-Version"] = "v1"
        elif path.startswith("/api/") and path not in {"/api/docs", "/api/openapi.json"}:
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = "2027-06-30"
            response.headers["Link"] = '</api/v1>; rel="successor-version"'
        return response

    def runtime() -> JobManager:
        if manager is None:
            raise HTTPException(503, "作业调度器未启动。")
        return manager

    def principal(request: Request) -> Principal:
        return getattr(request.state, "principal", configured_principal)

    def authorize(request: Request, action: str, project_id: str) -> Principal:
        current = principal(request)
        try:
            ensure_authorized(current, action, project_id)
        except AuthorizationError as exc:
            if manager is not None:
                manager.store.audit(
                    subject=current.subject,
                    action=action,
                    project_id=project_id,
                    outcome="denied",
                    details={"path": request.url.path},
                )
            raise HTTPException(403, str(exc)) from exc
        if manager is not None:
            manager.store.audit(
                subject=current.subject,
                action=action,
                project_id=project_id,
                outcome="allowed",
                details={"path": request.url.path},
            )
        return current

    def read(job_id: str, request: Request) -> dict[str, Any]:
        try:
            job = runtime().store.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "作业不存在。") from exc
        authorize(request, "read", str(job["project_id"]))
        return job

    def payload(job: dict[str, Any], *, include_result: bool = True) -> dict[str, Any]:
        try:
            return runtime().store.payload(job, include_result=include_result)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    def submit(
        body: StudioRunRequest, request: Request, key: str | None, parent: str | None = None
    ) -> dict[str, Any]:
        request_text = body.request.strip()
        if not request_text:
            raise HTTPException(400, "请求不能为空。")
        dispatcher = runtime()
        current = authorize(request, "submit", body.project_id)
        if dispatcher.error:
            raise HTTPException(503, dispatcher.error)
        try:
            return dispatcher.store.submit(
                request_text,
                body.use_llm_agents,
                config_path,
                max_queued=dispatcher.settings.max_queued,
                idempotency_key=key,
                parent_job_id=parent,
                owner=current.subject,
                project_id=body.project_id,
            )
        except IdempotencyError as exc:
            raise HTTPException(409, str(exc)) from exc
        except QueueFullError as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "2"}) from exc

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": manager is None or manager.error is None,
            "product": "MechAgent Studio",
            "config": str(config_path),
            "python_executable": sys.executable,
            "static_ready": _STATIC_DIR.joinpath("index.html").exists(),
            "runtime": {"ready": manager is not None, "error": manager.error if manager else None},
        }

    @app.get("/api/diagnostics")
    def diagnostics(llm: bool = False) -> dict[str, Any]:
        return run_environment_diagnostics(config_path, check_llm=llm)

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, Any]:
        return {
            "capabilities": [
                {
                    "capability_id": item.capability_id,
                    "task_case_id": item.task_case_id,
                    "title": item.title,
                    "analysis_type": item.analysis_type,
                    "physics_domain": item.physics_domain,
                    "solver_name": item.solver_name,
                    "mesher_name": item.mesher_name,
                    "model_case_ids": list(item.model_case_ids),
                    "example_requests": list(item.example_requests),
                    "planner_description": item.planner_description,
                }
                for item in all_capabilities()
            ]
        }

    @app.get("/api/examples")
    def examples() -> dict[str, Any]:
        return {"examples": example_payloads()}

    @app.post("/api/run")
    def run_simulation(
        body: StudioRunRequest,
        request: Request,
        idempotency_key: str | None = Header(None, min_length=1, max_length=128),
    ) -> dict[str, Any]:
        job = submit(body, request, idempotency_key)
        while job["status"] not in TERMINAL:
            if runtime().error:
                raise HTTPException(503, runtime().error)
            time.sleep(0.25)
            job = read(job["job_id"], request)
        return payload(job)["result"] or {
            "success": False,
            "error": job["error"],
            "job_id": job["job_id"],
            "status": job["status"],
        }

    @app.post("/api/inspect")
    def inspect_simulation(body: StudioRunRequest, request: Request) -> dict[str, Any]:
        request_text = body.request.strip()
        if not request_text:
            raise HTTPException(400, "请求不能为空。")
        authorize(request, "inspect", body.project_id)
        return (
            MechAgent.from_config(config_path)
            .inspect(
                request_text,
                use_llm_agents=body.use_llm_agents,
            )
            .model_dump(mode="json")
        )

    @app.post("/api/jobs", status_code=202)
    def create_job(
        body: StudioRunRequest,
        request: Request,
        idempotency_key: str | None = Header(None, min_length=1, max_length=128),
    ) -> dict[str, Any]:
        return payload(submit(body, request, idempotency_key))

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str, request: Request) -> dict[str, Any]:
        return payload(read(job_id, request))

    @app.get("/api/jobs")
    def list_jobs(
        request: Request,
        project_id: str = Query("default", min_length=1, max_length=128),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        current = authorize(request, "read", project_id)
        owner = None if "admin" in current.roles else current.subject
        return {
            "jobs": [
                payload(item, include_result=False)
                for item in runtime().store.list_jobs(
                    limit=limit,
                    offset=offset,
                    owner=owner,
                    project_id=project_id,
                )
            ]
        }

    @app.get("/api/audit")
    def audit_events(
        request: Request,
        project_id: str = Query("default", min_length=1, max_length=128),
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, Any]:
        current = authorize(request, "inspect", project_id)
        if "admin" not in current.roles:
            raise HTTPException(403, "只有 admin 可以读取审计事件。")
        return {"events": runtime().store.list_audit_events(limit=limit, project_id=project_id)}

    @app.get("/api/metrics")
    def metrics(
        request: Request,
        project_id: str | None = Query(None, min_length=1, max_length=128),
    ) -> dict[str, Any]:
        """返回受项目权限约束的脱敏作业、结果、证据和 worker 资源指标。"""

        current = principal(request)
        if project_id is None:
            authorize(request, "inspect", "*")
            return {"metrics": runtime().store.metrics()}
        authorize(request, "inspect", project_id)
        owner = None if "admin" in current.roles else current.subject
        return {"metrics": runtime().store.metrics(project_id=project_id, owner=owner)}

    @app.post("/api/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
        job = read(job_id, request)
        authorize(request, "cancel", str(job["project_id"]))
        runtime().store.cancel(job_id)
        job = read(job_id, request)
        if job["status"] == "cancelled":
            write_manifest(
                runtime().store.directory(job_id),
                status="cancelled",
                details={"job_id": job_id, "error_code": "cancelled_before_start"},
            )
        return payload(job)

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry_job(
        job_id: str,
        request: Request,
        idempotency_key: str | None = Header(None, min_length=1, max_length=128),
    ) -> dict[str, Any]:
        job = read(job_id, request)
        authorize(request, "retry", str(job["project_id"]))
        if job["status"] not in TERMINAL:
            raise HTTPException(409, "只有终态作业可以重试。")
        return payload(
            submit(
                StudioRunRequest(
                    request=job["request"],
                    use_llm_agents=job["use_llm_agents"],
                    project_id=job["project_id"],
                ),
                request,
                idempotency_key,
                job_id,
            )
        )

    @app.get("/api/jobs/{job_id}/evidence")
    def job_evidence(job_id: str, request: Request) -> dict[str, Any]:
        job = read(job_id, request)
        if job["status"] not in TERMINAL:
            raise HTTPException(409, "作业尚未结束。")
        path = runtime().store.directory(job_id) / "manifest.json"
        if not path.is_file():
            raise HTTPException(409, "作业证据清单缺失。")
        errors = verify_manifest(path)
        return {
            "valid": not errors,
            "errors": errors,
            "manifest": json.loads(path.read_text(encoding="utf-8")),
        }

    # v1 是稳定客户端边界；旧 /api 路径保留兼容期并通过响应头声明迁移终点。
    _versioned_routes = (
        ("/api/v1/health", health, ["GET"], None),
        ("/api/v1/diagnostics", diagnostics, ["GET"], None),
        ("/api/v1/capabilities", capabilities, ["GET"], None),
        ("/api/v1/examples", examples, ["GET"], None),
        ("/api/v1/run", run_simulation, ["POST"], None),
        ("/api/v1/inspect", inspect_simulation, ["POST"], None),
        ("/api/v1/jobs", create_job, ["POST"], 202),
        ("/api/v1/jobs/{job_id}", read_job, ["GET"], None),
        ("/api/v1/jobs", list_jobs, ["GET"], None),
        ("/api/v1/audit", audit_events, ["GET"], None),
        ("/api/v1/metrics", metrics, ["GET"], None),
        ("/api/v1/jobs/{job_id}/cancel", cancel_job, ["POST"], 202),
        ("/api/v1/jobs/{job_id}/retry", retry_job, ["POST"], 202),
        ("/api/v1/jobs/{job_id}/evidence", job_evidence, ["GET"], None),
    )
    for path, endpoint, methods, status_code in _versioned_routes:
        if status_code is None:
            app.add_api_route(path, endpoint, methods=methods, include_in_schema=True)
        else:
            app.add_api_route(
                path,
                endpoint,
                methods=methods,
                include_in_schema=True,
                status_code=status_code,
            )

    @app.get("/{full_path:path}")
    def serve_studio(full_path: str) -> Response:
        if full_path.startswith("api/"):
            raise HTTPException(404, "API 不存在。")
        if _STATIC_DIR.joinpath("index.html").exists():
            static_file = _static_file_for(full_path)
            if static_file is not None and static_file.is_file():
                return FileResponse(static_file)
            return FileResponse(_STATIC_DIR / "index.html")
        return HTMLResponse(render_index_html())

    return app


def run_studio(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    config: Path = Path("config/mechagent.yaml"),
    open_browser: bool = False,
    request: str | None = None,
    use_llm_agents: bool = False,
    view: str = "geometry",
    auto_run: bool = False,
) -> None:
    """启动 MechAgent Studio。"""

    bind_url = _studio_url(host, port)
    browser_url = _studio_entry_url(
        host,
        port,
        request=request,
        use_llm_agents=use_llm_agents,
        view=view,
        auto_run=auto_run,
    )
    print(f"MechAgent Studio 服务: {bind_url}")
    print(f"浏览器入口: {browser_url}")
    if open_browser:
        webbrowser.open(browser_url)
    uvicorn.run(create_studio_app(config), host=host, port=port)


def _browser_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    return _studio_url(browser_host, port)


def _studio_entry_url(
    host: str,
    port: int,
    *,
    request: str | None = None,
    use_llm_agents: bool = False,
    view: str = "geometry",
    auto_run: bool = False,
) -> str:
    normalized_view = _normalize_studio_view(view)
    query: dict[str, str] = {}
    request_text = request.strip() if request else ""
    if auto_run and not request_text:
        msg = "自动运行需要提供自然语言请求。"
        raise ValueError(msg)
    if request_text:
        query["request"] = request_text
    if use_llm_agents:
        query["llm"] = "1"
    if query or auto_run or normalized_view != "geometry":
        query["view"] = normalized_view
    if auto_run:
        query["run"] = "1"
    if not query:
        return _browser_url(host, port)
    return f"{_browser_url(host, port).rstrip('/')}/studio?{urlencode(query)}"


def _normalize_studio_view(view: str) -> str:
    normalized = view.strip().lower()
    if normalized not in _STUDIO_VIEW_MODES:
        choices = "、".join(sorted(_STUDIO_VIEW_MODES))
        msg = f"Studio 视图必须是 {choices}。"
        raise ValueError(msg)
    return normalized


def _studio_url(host: str, port: int) -> str:
    url_host = host
    if ":" in url_host and not url_host.startswith("["):
        url_host = f"[{url_host}]"
    return f"http://{url_host}:{port}"


def render_index_html() -> str:
    """返回静态资源缺失时的 HTML 响应。"""

    return _FALLBACK_HTML


def _static_file_for(full_path: str) -> Optional[Path]:
    relative = Path(full_path or "index.html")
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = (_STATIC_DIR / relative).resolve()
    try:
        candidate.relative_to(_STATIC_DIR.resolve())
    except ValueError:
        return None
    return candidate


_FALLBACK_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MechAgent Studio</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #f5f7fa;
      color: #172033;
      font-family: Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
    }
    main {
      width: min(720px, calc(100vw - 32px));
      background: #ffffff;
      border: 1px solid #d9e0e7;
      border-radius: 8px;
      padding: 28px;
      box-shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
    }
    h1 { margin: 0 0 12px; font-size: 24px; letter-spacing: 0; }
    p { margin: 0; color: #5d6b82; line-height: 1.7; }
    code { color: #1e5aa7; }
  </style>
</head>
<body>
  <main>
    <h1>MechAgent Studio 静态资源未构建</h1>
    <p>运行 <code>npm --prefix apps/mechagent-studio ci --no-audit --no-fund</code> 和
      <code>npm --prefix apps/mechagent-studio run build</code> 后，
      <code>python -m mechagent.cli studio</code> 会服务完整产品界面。</p>
  </main>
</body>
</html>
"""

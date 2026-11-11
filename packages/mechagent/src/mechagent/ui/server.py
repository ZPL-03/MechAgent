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
from mechagent.config import StudioSettings
from mechagent.diagnostics import run_environment_diagnostics
from mechagent.evidence import verify_manifest, write_manifest
from mechagent.examples import example_payloads
from mechagent.orchestrator.capabilities import all_capabilities
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


def create_studio_app(
    config: Path = Path("config/mechagent.yaml"), *, studio_settings: StudioSettings | None = None
) -> FastAPI:
    """创建本机单用户 ASGI 应用；生命周期启动持久队列调度。"""
    config_path = config
    manager: JobManager | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal manager
        settings = studio_settings or MechAgent.from_config(config_path).config.studio
        manager = JobManager(JobStore(settings.database), settings)
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

    def read(job_id: str) -> dict[str, Any]:
        try:
            return runtime().store.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "作业不存在。") from exc

    def payload(job: dict[str, Any], *, include_result: bool = True) -> dict[str, Any]:
        try:
            return runtime().store.payload(job, include_result=include_result)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    def submit(
        body: StudioRunRequest, key: str | None, parent: str | None = None
    ) -> dict[str, Any]:
        request_text = body.request.strip()
        if not request_text:
            raise HTTPException(400, "请求不能为空。")
        dispatcher = runtime()
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
        idempotency_key: str | None = Header(None, min_length=1, max_length=128),
    ) -> dict[str, Any]:
        job = submit(body, idempotency_key)
        while job["status"] not in TERMINAL:
            if runtime().error:
                raise HTTPException(503, runtime().error)
            time.sleep(0.25)
            job = read(job["job_id"])
        return payload(job)["result"] or {
            "success": False,
            "error": job["error"],
            "job_id": job["job_id"],
            "status": job["status"],
        }

    @app.post("/api/inspect")
    def inspect_simulation(body: StudioRunRequest) -> dict[str, Any]:
        request_text = body.request.strip()
        if not request_text:
            raise HTTPException(400, "请求不能为空。")
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
        idempotency_key: str | None = Header(None, min_length=1, max_length=128),
    ) -> dict[str, Any]:
        return payload(submit(body, idempotency_key))

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str) -> dict[str, Any]:
        return payload(read(job_id))

    @app.get("/api/jobs")
    def list_jobs(
        limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
    ) -> dict[str, Any]:
        return {
            "jobs": [
                payload(item, include_result=False)
                for item in runtime().store.list_jobs(limit=limit, offset=offset)
            ]
        }

    @app.post("/api/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(job_id: str) -> dict[str, Any]:
        read(job_id)
        runtime().store.cancel(job_id)
        job = read(job_id)
        if job["status"] == "cancelled":
            write_manifest(
                runtime().store.directory(job_id),
                status="cancelled",
                details={"job_id": job_id, "error_code": "cancelled_before_start"},
            )
        return payload(job)

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry_job(
        job_id: str, idempotency_key: str | None = Header(None, min_length=1, max_length=128)
    ) -> dict[str, Any]:
        job = read(job_id)
        if job["status"] not in TERMINAL:
            raise HTTPException(409, "只有终态作业可以重试。")
        return payload(
            submit(
                StudioRunRequest(request=job["request"], use_llm_agents=job["use_llm_agents"]),
                idempotency_key,
                job_id,
            )
        )

    @app.get("/api/jobs/{job_id}/evidence")
    def job_evidence(job_id: str) -> dict[str, Any]:
        job = read(job_id)
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
        ("/api/v1/health", health, ["GET"]),
        ("/api/v1/diagnostics", diagnostics, ["GET"]),
        ("/api/v1/capabilities", capabilities, ["GET"]),
        ("/api/v1/examples", examples, ["GET"]),
        ("/api/v1/run", run_simulation, ["POST"]),
        ("/api/v1/inspect", inspect_simulation, ["POST"]),
        ("/api/v1/jobs", create_job, ["POST"]),
        ("/api/v1/jobs/{job_id}", read_job, ["GET"]),
        ("/api/v1/jobs", list_jobs, ["GET"]),
        ("/api/v1/jobs/{job_id}/cancel", cancel_job, ["POST"]),
        ("/api/v1/jobs/{job_id}/retry", retry_job, ["POST"]),
        ("/api/v1/jobs/{job_id}/evidence", job_evidence, ["GET"]),
    )
    for path, endpoint, methods in _versioned_routes:
        app.add_api_route(path, endpoint, methods=methods, include_in_schema=True)

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

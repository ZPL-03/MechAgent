"""MechAgent Studio 本地服务。"""

from __future__ import annotations

import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Optional
from urllib.parse import urlencode
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from mechagent import MechAgent
from mechagent.examples import example_payloads
from mechagent.orchestrator.capabilities import all_capabilities
from mechagent.orchestrator.progress import ProgressEvent, progress_sink
from mechagent.ui.visualization import visualizations_from_summary

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_MAX_STUDIO_JOBS = 16
_STUDIO_VIEW_MODES = {"geometry", "mesh", "result"}


class StudioRunRequest(BaseModel):
    """Studio 单次运行请求。"""

    model_config = ConfigDict(extra="forbid")

    request: str = Field(default="", description="自然语言仿真请求。")
    use_llm_agents: bool = Field(default=False, description="本次运行是否启用远端参数补全链路。")


@dataclass
class StudioJob:
    """Studio 后端作业状态。"""

    job_id: str
    request: str
    use_llm_agents: bool
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    events: list[ProgressEvent] | None = None


def create_studio_app(config: Path = Path("config/mechagent.yaml")) -> FastAPI:
    """创建 MechAgent Studio ASGI 应用。"""

    config_path = config
    jobs: dict[str, StudioJob] = {}
    jobs_lock = RLock()
    app = FastAPI(
        title="MechAgent Studio API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "product": "MechAgent Studio",
            "config": str(config_path),
            "python_executable": sys.executable,
            "static_ready": _STATIC_DIR.joinpath("index.html").exists(),
        }

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
    async def run_simulation(payload: StudioRunRequest) -> dict[str, Any]:
        request_text = payload.request.strip()
        if not request_text:
            raise HTTPException(status_code=400, detail="请求不能为空。")
        return _run_studio_request(config_path, request_text, payload.use_llm_agents)

    @app.post("/api/inspect")
    async def inspect_simulation(payload: StudioRunRequest) -> dict[str, Any]:
        request_text = payload.request.strip()
        if not request_text:
            raise HTTPException(status_code=400, detail="请求不能为空。")
        agent = MechAgent.from_config(config_path)
        return agent.inspect(
            request_text,
            use_llm_agents=payload.use_llm_agents,
        ).model_dump(mode="json")

    @app.post("/api/jobs", status_code=202)
    def create_job(payload: StudioRunRequest) -> dict[str, Any]:
        request_text = payload.request.strip()
        if not request_text:
            raise HTTPException(status_code=400, detail="请求不能为空。")
        job = StudioJob(
            job_id=uuid4().hex,
            request=request_text,
            use_llm_agents=payload.use_llm_agents,
            status="queued",
            created_at=_utc_now(),
            events=[],
        )
        with jobs_lock:
            jobs[job.job_id] = job
            _prune_jobs(jobs)
        thread = Thread(
            target=_run_studio_job,
            args=(jobs, jobs_lock, job.job_id, config_path),
            daemon=True,
        )
        thread.start()
        return _job_payload(job)

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str) -> dict[str, Any]:
        with jobs_lock:
            job = jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="作业不存在。")
            return _job_payload(job)

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        with jobs_lock:
            ordered_jobs = sorted(jobs.values(), key=lambda item: item.created_at, reverse=True)
            return {"jobs": [_job_payload(item) for item in ordered_jobs]}

    @app.get("/{full_path:path}")
    def serve_studio(full_path: str) -> Response:
        if _STATIC_DIR.joinpath("index.html").exists():
            static_file = _static_file_for(full_path)
            if static_file is not None and static_file.is_file():
                return FileResponse(static_file)
            return FileResponse(_STATIC_DIR / "index.html")
        return HTMLResponse(render_index_html())

    return app


def _run_studio_request(
    config_path: Path,
    request_text: str,
    use_llm_agents: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        agent = MechAgent.from_config(config_path)
        result = agent.run(request_text, use_llm_agents=use_llm_agents)
        visualizations = [item.to_dict() for item in visualizations_from_summary(result.summary)]
        return {
            "success": bool(result.summary.get("success", False)),
            "report": result.report,
            "summary": result.summary,
            "visualizations": visualizations,
            "metadata": {"duration_ms": int((time.perf_counter() - started) * 1000)},
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "summary": {
                "success": False,
                "errors": [{"node": "studio", "message": str(exc)}],
                "tasks": [],
            },
            "visualizations": [],
            "metadata": {"duration_ms": int((time.perf_counter() - started) * 1000)},
        }


def _run_studio_job(
    jobs: dict[str, StudioJob],
    jobs_lock: RLock,
    job_id: str,
    config_path: Path,
) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job.status = "running"
        job.started_at = _utc_now()
        request_text = job.request
        use_llm_agents = job.use_llm_agents
    try:

        def collect_event(event: ProgressEvent) -> None:
            with jobs_lock:
                active_job = jobs[job_id]
                if active_job.events is None:
                    active_job.events = []
                active_job.events.append(event)

        with progress_sink(collect_event):
            result = _run_studio_request(config_path, request_text, use_llm_agents)
        with jobs_lock:
            job = jobs[job_id]
            job.result = result
            job.error = result.get("error")
            job.status = "succeeded" if result.get("success") else "failed"
            job.finished_at = _utc_now()
    except Exception as exc:
        with jobs_lock:
            job = jobs[job_id]
            job.result = None
            job.error = str(exc)
            job.status = "failed"
            job.finished_at = _utc_now()


def _job_payload(job: StudioJob) -> dict[str, Any]:
    duration_ms: int | None = None
    if job.started_at is not None:
        ended_at = job.finished_at or _utc_now()
        duration_ms = int((ended_at - job.started_at).total_seconds() * 1000)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "request": job.request,
        "use_llm_agents": job.use_llm_agents,
        "created_at": _isoformat(job.created_at),
        "started_at": _isoformat(job.started_at),
        "finished_at": _isoformat(job.finished_at),
        "duration_ms": duration_ms,
        "result": job.result,
        "error": job.error,
        "events": list(job.events or []),
    }


def _prune_jobs(jobs: dict[str, StudioJob]) -> None:
    removable = sorted(
        (job for job in jobs.values() if job.status not in {"queued", "running"}),
        key=lambda item: item.created_at,
    )
    while len(jobs) > _MAX_STUDIO_JOBS and removable:
        jobs.pop(removable.pop(0).job_id, None)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def run_studio(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    config: Path = Path("config/mechagent.yaml"),
    open_browser: bool = False,
    request: str | None = None,
    use_llm_agents: bool = False,
    view: str = "geometry",
) -> None:
    """启动 MechAgent Studio。"""

    bind_url = _studio_url(host, port)
    browser_url = _studio_entry_url(
        host,
        port,
        request=request,
        use_llm_agents=use_llm_agents,
        view=view,
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
) -> str:
    normalized_view = _normalize_studio_view(view)
    query: dict[str, str] = {}
    request_text = request.strip() if request else ""
    if request_text:
        query["request"] = request_text
    if use_llm_agents:
        query["llm"] = "1"
    if query or normalized_view != "geometry":
        query["view"] = normalized_view
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

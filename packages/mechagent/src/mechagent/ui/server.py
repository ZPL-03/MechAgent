"""MechAgent Studio 本地服务。"""

from __future__ import annotations

import time
import webbrowser
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from mechagent import MechAgent
from mechagent.ui.visualization import visualizations_from_summary

_STATIC_DIR = Path(__file__).resolve().parent / "static"


class StudioRunRequest(BaseModel):
    """Studio 单次运行请求。"""

    model_config = ConfigDict(extra="forbid")

    request: str = Field(default="", description="自然语言仿真请求。")
    use_llm_agents: bool = Field(default=False, description="本次运行是否启用 LLM Agent。")


def create_studio_app(config: Path = Path("config/mechagent.yaml")) -> FastAPI:
    """创建 MechAgent Studio ASGI 应用。"""

    config_path = config
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
            "static_ready": _STATIC_DIR.joinpath("index.html").exists(),
        }

    @app.post("/api/run")
    def run_simulation(payload: StudioRunRequest) -> dict[str, Any]:
        request_text = payload.request.strip()
        if not request_text:
            raise HTTPException(status_code=400, detail="请求不能为空。")
        started = time.perf_counter()
        try:
            agent = MechAgent.from_config(config_path)
            result = agent.run(request_text, use_llm_agents=payload.use_llm_agents)
            visualizations = [
                item.to_dict() for item in visualizations_from_summary(result.summary)
            ]
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

    @app.get("/{full_path:path}")
    def serve_studio(full_path: str) -> Response:
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
) -> None:
    """启动 MechAgent Studio。"""

    url = f"http://{host}:{port}"
    print(f"MechAgent Studio: {url}")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(create_studio_app(config), host=host, port=port)


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
    <p>运行 <code>npm --prefix apps/mechagent-studio install</code> 和
      <code>npm --prefix apps/mechagent-studio run build</code> 后，
      <code>python -m mechagent.cli studio</code> 会服务完整产品界面。</p>
  </main>
</body>
</html>
"""

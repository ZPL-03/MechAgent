"""MechAgent Studio 服务和可视化测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from typer.testing import CliRunner

from mechagent.cli import app
from mechagent.ui.server import create_studio_app, render_index_html
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
    assert isinstance(payload["static_ready"], bool)


def test_studio_run_rejects_empty_request(tmp_path: Path) -> None:
    client = TestClient(create_studio_app(tmp_path / "mechagent.yaml"))

    response = client.post("/api/run", json={"request": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "请求不能为空。"


def test_studio_run_returns_summary_and_visualizations(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeAgent:
        def run(
            self,
            request: str,
            use_llm_agents: bool | None = None,
        ) -> SimpleNamespace:
            captured["request"] = request
            captured["use_llm_agents"] = use_llm_agents
            return SimpleNamespace(report="# 报告", summary=_beam_summary())

    monkeypatch.setattr("mechagent.ui.server.MechAgent.from_config", lambda _path: FakeAgent())
    client = TestClient(create_studio_app(tmp_path / "mechagent.yaml"))

    response = client.post(
        "/api/run",
        json={"request": "求解悬臂梁", "use_llm_agents": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert captured == {"request": "求解悬臂梁", "use_llm_agents": True}
    assert payload["success"] is True
    assert payload["report"] == "# 报告"
    assert payload["summary"]["tasks"][0]["task_id"] == "TASK_1"
    assert payload["visualizations"][0]["kind"] == "beam"
    assert payload["metadata"]["duration_ms"] >= 0


def test_studio_static_fallback_html_is_available() -> None:
    html = render_index_html()

    assert "MechAgent Studio 静态资源未构建" in html
    assert "python -m mechagent.cli studio" in html


def test_cli_studio_delegates_to_server(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_studio(
        *,
        host: str,
        port: int,
        config: Path,
        open_browser: bool,
    ) -> None:
        captured.update(
            {
                "host": host,
                "port": port,
                "config": config,
                "open_browser": open_browser,
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
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "host": "0.0.0.0",
        "port": 9876,
        "config": config_path,
        "open_browser": True,
    }


def test_visualizations_cover_current_static_geometry_types() -> None:
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

    assert [item.kind for item in visuals] == ["beam", "plate", "solid"]
    for item in visuals:
        assert item.svg.startswith("<svg")
        assert item.task_id.startswith("TASK_")


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

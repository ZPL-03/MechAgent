"""MechAgent Studio 服务和可视化测试。"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from time import sleep
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pytest import CaptureFixture, MonkeyPatch
from typer.testing import CliRunner

from mechagent.cli import app
from mechagent.orchestrator.progress import emit_progress
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
    assert len(examples) == 26
    assert examples[0]["example_id"] == "SC-01"
    assert examples[0]["capability_id"] == "structural_static"
    assert examples[0]["model_case_id"] == "STATIC-BEAM"
    assert any(item["model_case_id"] == "STATIC-SOLID" for item in examples)
    assert any("偏心圆孔" in item["title"] for item in examples)
    assert any("多孔" in item["title"] for item in examples)


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


def test_studio_run_endpoint_uses_event_loop_thread(tmp_path: Path) -> None:
    studio_app = create_studio_app(tmp_path / "mechagent.yaml")
    route = next(
        route
        for route in studio_app.routes
        if isinstance(route, APIRoute) and route.path == "/api/run"
    )

    assert inspect.iscoroutinefunction(route.endpoint)


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
            emit_progress("planner", "running", "任务识别开始")
            emit_progress("planner", "complete", "任务识别完成")
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


def test_studio_job_endpoints_return_polled_result(
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
            emit_progress("planner", "running", "任务识别开始")
            emit_progress("planner", "complete", "任务识别完成")
            return SimpleNamespace(report="# 报告", summary=_beam_summary())

    monkeypatch.setattr("mechagent.ui.server.MechAgent.from_config", lambda _path: FakeAgent())
    client = TestClient(create_studio_app(tmp_path / "mechagent.yaml"))

    response = client.post(
        "/api/jobs",
        json={"request": "求解悬臂梁", "use_llm_agents": True},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["job_id"]
    assert payload["status"] in {"queued", "running", "succeeded"}

    job_payload = payload
    for _ in range(50):
        job_response = client.get(f"/api/jobs/{payload['job_id']}")
        assert job_response.status_code == 200
        job_payload = job_response.json()
        if job_payload["status"] in {"succeeded", "failed"}:
            break
        sleep(0.01)

    assert captured == {"request": "求解悬臂梁", "use_llm_agents": True}
    assert job_payload["status"] == "succeeded"
    assert job_payload["duration_ms"] >= 0
    assert job_payload["result"]["success"] is True
    assert job_payload["result"]["visualizations"][0]["kind"] == "beam"
    assert [(event["stage"], event["status"]) for event in job_payload["events"]] == [
        ("planner", "running"),
        ("planner", "complete"),
    ]

    list_response = client.get("/api/jobs")
    assert list_response.status_code == 200
    assert list_response.json()["jobs"][0]["job_id"] == payload["job_id"]


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
        assert item.scene is not None
        assert item.scene["mode"] == "result"
        assert item.scene["geometry_type"] == item.kind
        assert (item.scene["scalar"]["name"], item.scene["scalar"]["unit"]) == (
            "U 位移模量",
            "mm",
        )
        assert [field["key"] for field in item.scene["fields"]][:4] == [
            "u_mag",
            "ux",
            "uy",
            "uz",
        ]


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

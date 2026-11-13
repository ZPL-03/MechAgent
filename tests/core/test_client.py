"""Studio Python HTTP 客户端契约测试。"""

from __future__ import annotations

import json
import re

import httpx
import pytest

from mechagent import StudioClient, StudioClientError


def _response(request: httpx.Request, status: int = 200, **payload: object) -> httpx.Response:
    return httpx.Response(status, json=payload, request=request)


def test_studio_client_covers_stable_routes_and_request_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(request, ok=True)

    with StudioClient(
        "https://studio.example.test/api/v1/",
        api_key="secret-key",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert client.health() == {"ok": True}
        client.diagnostics(llm=True)
        client.capabilities()
        client.examples()
        client.inspect("检查梁", project_id="beam", organization="engineering")
        client.create_job("运行梁", idempotency_key="job-key")
        client.run("同步运行")
        client.get_job("job/id with space")
        client.list_jobs(project_id="beam", organization="engineering", limit=2, cursor="next-page")
        client.list_audit(project_id="beam", organization="engineering", limit=3, cursor="audit")
        client.cancel_job("job-1")
        client.retry_job("job-1", idempotency_key="retry-key")
        client.evidence("job-1")
        client.metrics(project_id="beam", organization="engineering")
        client.list_identities()
        client.create_identity({"subject": "analyst"})
        client.update_identity("analyst/user", {"active": True})
        client.rotate_identity("analyst/user")
        client.disable_identity("analyst/user")

    assert requests
    for request in requests:
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Authorization"] == "Bearer secret-key"

    by_path = {request.method + " " + request.url.path: request for request in requests}
    assert by_path["GET /api/v1/diagnostics"].url.params["llm"] == "1"
    assert by_path["POST /api/v1/jobs"].headers["Idempotency-Key"] == "job-key"
    generated = by_path["POST /api/v1/run"].headers["Idempotency-Key"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    list_request = by_path["GET /api/v1/jobs"]
    assert dict(list_request.url.params) == {
        "project_id": "beam",
        "organization": "engineering",
        "limit": "2",
        "cursor": "next-page",
    }
    assert "/api/v1/jobs/job%2Fid%20with%20space" in str(
        next(request.url for request in requests if request.url.path.endswith("job/id with space"))
    )
    assert json.loads(by_path["POST /api/v1/inspect"].content) == {
        "request": "检查梁",
        "use_llm_agents": False,
        "project_id": "beam",
        "organization": "engineering",
    }


def test_studio_client_preserves_api_errors_and_transport_failures() -> None:
    def api_error(request: httpx.Request) -> httpx.Response:
        return _response(request, 409, code="conflict", detail={"reason": "duplicate"})

    with (
        StudioClient(transport=httpx.MockTransport(api_error)) as client,
        pytest.raises(StudioClientError) as raised,
    ):
        client.health()
    error = raised.value
    assert error.status_code == 409
    assert error.code == "conflict"
    assert error.detail == {"reason": "duplicate"}
    assert error.request_url == "http://127.0.0.1:8765/api/v1/health"

    def invalid_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="upstream unavailable", request=request)

    with (
        StudioClient(transport=httpx.MockTransport(invalid_response)) as client,
        pytest.raises(StudioClientError) as raised,
    ):
        client.health()
    assert raised.value.code == "http_error"
    assert raised.value.detail == "upstream unavailable"

    def transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with (
        StudioClient(transport=httpx.MockTransport(transport_error)) as client,
        pytest.raises(StudioClientError) as raised,
    ):
        client.health()
    assert raised.value.status_code == 0
    assert raised.value.code == "transport_error"
    assert raised.value.request_url is None


def test_studio_client_rejects_invalid_base_urls_and_pagination_arguments() -> None:
    with pytest.raises(ValueError, match="绝对 URL"):
        StudioClient("/api/v1")
    with pytest.raises(ValueError, match="query"):
        StudioClient("http://localhost/api/v1?token=secret")
    with pytest.raises(ValueError, match="timeout"):
        StudioClient(timeout=0)

    with StudioClient(transport=httpx.MockTransport(lambda request: _response(request))) as client:
        with pytest.raises(ValueError, match="不能同时使用"):
            client.list_jobs(cursor="page", offset=1)
        with pytest.raises(ValueError, match="非空白"):
            client.create_job("请求", idempotency_key=" ")
        with pytest.raises(ValueError, match="非空白"):
            client.retry_job("job", idempotency_key="")

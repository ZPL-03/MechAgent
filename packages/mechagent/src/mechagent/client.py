"""MechAgent Studio HTTP 客户端。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, TypeAlias
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx

DEFAULT_STUDIO_BASE_URL = "http://127.0.0.1:8765/api/v1"
QueryValue: TypeAlias = str | int | None


class StudioClientError(RuntimeError):
    """Studio API 或传输层错误。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: Any,
        *,
        request_url: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.request_url = request_url
        suffix = f": {detail}" if detail not in (None, "") else ""
        super().__init__(f"Studio API 请求失败（{code}, HTTP {status_code}）{suffix}")


class StudioClient:
    """访问 Studio `/api/v1` 的同步 Python 客户端。

    客户端负责 Bearer API key、稳定错误字段、幂等键和游标参数的传递；
    返回值保留服务端 JSON 结构，不在客户端生成或推断工程结果。
    """

    def __init__(
        self,
        base_url: str = DEFAULT_STUDIO_BASE_URL,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Studio base_url 必须是带 http 或 https 的绝对 URL。")
        if parsed.query or parsed.fragment:
            raise ValueError("Studio base_url 不能包含 query 或 fragment。")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Studio timeout 必须是正的有限数值。")
        if api_key is not None and not api_key.strip():
            raise ValueError("Studio api_key 不能为空。")
        headers = {"Accept": "application/json"}
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=normalized,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        """关闭底层 HTTP 连接池。"""

        self._client.close()

    def __enter__(self) -> "StudioClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
        json: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if idempotency_key is not None:
            if not 1 <= len(idempotency_key) <= 128 or any(
                char.isspace() for char in idempotency_key
            ):
                raise ValueError("idempotency_key 必须是 1 到 128 个非空白字符。")
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self._client.request(
                method,
                path.lstrip("/"),
                params={key: value for key, value in (params or {}).items() if value is not None},
                json=json,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise StudioClientError(0, "transport_error", str(exc)) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text}
        if not isinstance(payload, dict):
            payload = {"detail": payload}
        if not response.is_success:
            code = payload.get("code")
            detail = payload.get("detail", "Studio API 返回错误响应。")
            raise StudioClientError(
                response.status_code,
                code if isinstance(code, str) and code else "http_error",
                detail,
                request_url=str(response.request.url),
            )
        return payload

    @staticmethod
    def _key(value: str) -> str:
        return quote(value, safe="")

    @staticmethod
    def _idempotency_key(value: str | None) -> str:
        return uuid4().hex if value is None else value

    def health(self) -> dict[str, Any]:
        return self._request("GET", "health")

    def diagnostics(self, *, llm: bool = False) -> dict[str, Any]:
        return self._request("GET", "diagnostics", params={"llm": int(llm)})

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "capabilities")

    def examples(self) -> dict[str, Any]:
        return self._request("GET", "examples")

    def inspect(
        self,
        request: str,
        *,
        use_llm_agents: bool = False,
        project_id: str = "default",
        organization: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "inspect",
            json={
                "request": request,
                "use_llm_agents": use_llm_agents,
                "project_id": project_id,
                "organization": organization,
            },
        )

    def create_job(
        self,
        request: str,
        *,
        use_llm_agents: bool = False,
        project_id: str = "default",
        organization: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "jobs",
            json={
                "request": request,
                "use_llm_agents": use_llm_agents,
                "project_id": project_id,
                "organization": organization,
            },
            idempotency_key=self._idempotency_key(idempotency_key),
        )

    def run(
        self,
        request: str,
        *,
        use_llm_agents: bool = False,
        project_id: str = "default",
        organization: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "run",
            json={
                "request": request,
                "use_llm_agents": use_llm_agents,
                "project_id": project_id,
                "organization": organization,
            },
            idempotency_key=self._idempotency_key(idempotency_key),
        )

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"jobs/{self._key(job_id)}")

    def list_jobs(
        self,
        *,
        project_id: str = "default",
        organization: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        if cursor is not None and offset is not None:
            raise ValueError("cursor 和 offset 不能同时使用。")
        return self._request(
            "GET",
            "jobs",
            params={
                "project_id": project_id,
                "organization": organization,
                "limit": limit,
                "cursor": cursor,
                "offset": offset,
            },
        )

    def list_audit(
        self,
        *,
        project_id: str = "default",
        organization: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "audit",
            params={
                "project_id": project_id,
                "organization": organization,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"jobs/{self._key(job_id)}/cancel")

    def retry_job(self, job_id: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"jobs/{self._key(job_id)}/retry",
            idempotency_key=self._idempotency_key(idempotency_key),
        )

    def evidence(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"jobs/{self._key(job_id)}/evidence")

    def list_artifacts(self, job_id: str) -> dict[str, Any]:
        """返回作业对象索引。"""

        return self._request("GET", f"jobs/{self._key(job_id)}/artifacts")

    def download_artifact(self, job_id: str, artifact_path: str) -> bytes:
        """下载作业对象内容；服务端会按对象摘要恢复并校验。"""

        normalized = artifact_path.replace("\\", "/")
        response = self._client.get(
            f"jobs/{self._key(job_id)}/artifacts/{quote(normalized, safe='/')}"
        )
        if not response.is_success:
            try:
                payload = response.json()
            except ValueError:
                payload = {"detail": response.text}
            if not isinstance(payload, dict):
                payload = {"detail": payload}
            code = payload.get("code")
            raise StudioClientError(
                response.status_code,
                code if isinstance(code, str) and code else "http_error",
                payload.get("detail", "Studio API 返回错误响应。"),
                request_url=str(response.request.url),
            )
        return response.content

    def metrics(
        self,
        *,
        project_id: str | None = None,
        organization: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "metrics",
            params={"project_id": project_id, "organization": organization},
        )

    def list_identities(self) -> dict[str, Any]:
        return self._request("GET", "identities")

    def create_identity(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._request("POST", "identities", json=dict(body))

    def update_identity(self, subject: str, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"identities/{self._key(subject)}", json=dict(body))

    def rotate_identity(self, subject: str) -> dict[str, Any]:
        return self._request("POST", f"identities/{self._key(subject)}/rotate")

    def disable_identity(self, subject: str) -> dict[str, Any]:
        return self._request("DELETE", f"identities/{self._key(subject)}")

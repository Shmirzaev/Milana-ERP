from __future__ import annotations

from typing import Any

import httpx

from .audit import sanitize_payload
from .auth import MCPAuthConfigError, auth_headers
from .config import Settings, get_settings


class ERPApiError(RuntimeError):
    def __init__(self, status_code: int, detail: str, *, path: str | None = None):
        self.status_code = status_code
        self.detail = detail
        self.path = path
        super().__init__(detail)

    def to_public_dict(self) -> dict[str, Any]:
        if self.status_code == 401:
            message = "ERP authentication failed. Sign in again and provide a fresh ERP bearer token."
        elif self.status_code == 403:
            message = "ERP permission denied for this tool."
        else:
            message = self.detail
        return {
            "status_code": self.status_code,
            "message": message,
            "path": self.path,
        }


class ERPApiClient:
    def __init__(self, settings: Settings | None = None, http_client: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=self.settings.erp_api_base_url,
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=False,
        )

    async def __aenter__(self) -> "ERPApiClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        api_path = path if path.startswith("/") else f"/{path}"
        try:
            headers = {
                "Accept": "application/json",
                "User-Agent": "milana-erp-mcp/0.1",
                **auth_headers(self.settings),
            }
            response = await self._client.request(method, api_path, params=params, json=json_body, headers=headers)
        except MCPAuthConfigError as exc:
            raise ERPApiError(401, str(exc), path=api_path) from exc
        except httpx.TimeoutException as exc:
            raise ERPApiError(504, "ERP API request timed out", path=api_path) from exc
        except httpx.RequestError as exc:
            raise ERPApiError(502, "ERP API request failed", path=api_path) from exc

        if response.status_code >= 400:
            raise ERPApiError(response.status_code, _error_detail(response), path=api_path)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return sanitize_payload(response.json())
        except ValueError as exc:
            raise ERPApiError(502, "ERP API returned a non-JSON response", path=api_path) from exc

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        return await self.request("POST", path, json_body=json_body)

    async def get_me(self) -> dict[str, Any]:
        data = await self.get("/api/auth/me")
        return data if isinstance(data, dict) else {"raw": data}


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or f"ERP API error {response.status_code}")[:500]
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload
    else:
        detail = payload
    return str(detail)[:500]

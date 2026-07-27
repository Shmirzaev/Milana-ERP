from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest

from milana_erp_mcp.client import ERPApiClient
from milana_erp_mcp.config import Settings
from milana_erp_mcp.tools import (
    erp_create_task_tool,
    erp_finance_summary_tool,
    erp_gm_summary_tool,
    erp_me_tool,
    erp_search_tool,
    erp_send_notification_tool,
)


ME = {
    "id": 7,
    "name": "General Manager",
    "email": "gm@example.com",
    "role": "Management",
    "department": "Management",
    "permissions": ["management.view", "finance.view"],
}


def _json_response(status_code: int, payload: Any) -> httpx.Response:
    return httpx.Response(status_code, json=payload, headers={"content-type": "application/json"})


def _settings() -> Settings:
    return Settings(erp_api_base_url="http://erp.test", bearer_token="real-user-token")


async def _with_client(
    handler: Callable[[httpx.Request, list[httpx.Request]], httpx.Response],
    callback: Callable[[ERPApiClient, list[httpx.Request], Settings], Any],
) -> Any:
    seen: list[httpx.Request] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["authorization"] == "Bearer real-user-token"
        return handler(request, seen)

    settings = _settings()
    async with httpx.AsyncClient(base_url=settings.erp_api_base_url, transport=httpx.MockTransport(transport_handler)) as raw:
        client = ERPApiClient(settings=settings, http_client=raw)
        return await callback(client, seen, settings)


@pytest.mark.asyncio
async def test_erp_me_returns_authenticated_user() -> None:
    def handler(request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        assert request.url.path == "/api/auth/me"
        return _json_response(200, ME)

    async def callback(client: ERPApiClient, _seen: list[httpx.Request], settings: Settings) -> dict[str, Any]:
        return await erp_me_tool(settings=settings, client=client)

    result = await _with_client(handler, callback)
    assert result["ok"] is True
    assert result["data"]["id"] == 7


@pytest.mark.asyncio
async def test_erp_search_wraps_global_search_and_sanitizes_fields() -> None:
    def handler(request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        if request.url.path == "/api/auth/me":
            return _json_response(200, ME)
        assert request.url.path == "/api/search"
        assert request.url.params["q"] == "SO-100"
        return _json_response(
            200,
            [
                {
                    "type": "SalesOrder",
                    "id": 10,
                    "label": "SO-100",
                    "url": "/sales-orders/10",
                    "password_hash": "must-not-leak",
                    "api_token": "must-not-leak",
                }
            ],
        )

    async def callback(client: ERPApiClient, _seen: list[httpx.Request], settings: Settings) -> dict[str, Any]:
        return await erp_search_tool("SO-100", settings=settings, client=client)

    result = await _with_client(handler, callback)
    assert result["ok"] is True
    assert result["data"][0]["label"] == "SO-100"
    assert "password_hash" not in result["data"][0]
    assert "api_token" not in result["data"][0]


@pytest.mark.asyncio
async def test_erp_gm_summary_wraps_management_dashboard() -> None:
    def handler(request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        if request.url.path == "/api/auth/me":
            return _json_response(200, ME)
        assert request.url.path == "/api/dashboard/management"
        return _json_response(200, {"active_orders": 12, "late_orders": 2})

    async def callback(client: ERPApiClient, _seen: list[httpx.Request], settings: Settings) -> dict[str, Any]:
        return await erp_gm_summary_tool(settings=settings, client=client)

    result = await _with_client(handler, callback)
    assert result["ok"] is True
    assert result["data"]["active_orders"] == 12


@pytest.mark.asyncio
async def test_send_notification_preview_does_not_call_send_endpoint() -> None:
    def handler(request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        assert request.url.path == "/api/auth/me"
        return _json_response(200, ME)

    async def callback(client: ERPApiClient, seen: list[httpx.Request], settings: Settings) -> dict[str, Any]:
        result = await erp_send_notification_tool(
            target_type="user_id",
            user_id=3,
            title="Check late order",
            message="Please review SO-100.",
            settings=settings,
            client=client,
        )
        assert [request.url.path for request in seen] == ["/api/auth/me"]
        return result

    result = await _with_client(handler, callback)
    assert result["ok"] is True
    assert result["requires_confirmation"] is True
    assert result["preview"]["target"]["user_id"] == 3


@pytest.mark.asyncio
async def test_send_notification_confirm_calls_backend_endpoint() -> None:
    def handler(request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        if request.url.path == "/api/auth/me":
            return _json_response(200, ME)
        assert request.method == "POST"
        assert request.url.path == "/api/notifications/send"
        payload = json.loads(request.content)
        assert payload["target_type"] == "department"
        assert payload["department"] == "cutting"
        return _json_response(
            200,
            {
                "message": "notification_sent",
                "created_count": 2,
                "notification_ids": [91, 92],
                "recipients": [{"user_id": 11}, {"user_id": 12}],
            },
        )

    async def callback(client: ERPApiClient, _seen: list[httpx.Request], settings: Settings) -> dict[str, Any]:
        return await erp_send_notification_tool(
            target_type="department",
            department="cutting",
            title="Production update",
            message="Please review the active queue.",
            confirm=True,
            settings=settings,
            client=client,
        )

    result = await _with_client(handler, callback)
    assert result["ok"] is True
    assert result["data"]["created_count"] == 2


@pytest.mark.asyncio
async def test_create_task_preview_does_not_create_task() -> None:
    def handler(request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        assert request.url.path == "/api/auth/me"
        return _json_response(200, ME)

    async def callback(client: ERPApiClient, seen: list[httpx.Request], settings: Settings) -> dict[str, Any]:
        result = await erp_create_task_tool(
            assignee_user_id=3,
            title="Review delayed bundles",
            description="Check bundle queue.",
            settings=settings,
            client=client,
        )
        assert [request.url.path for request in seen] == ["/api/auth/me"]
        return result

    result = await _with_client(handler, callback)
    assert result["ok"] is True
    assert result["requires_confirmation"] is True
    assert result["preview"]["assignee"]["user_id"] == 3


@pytest.mark.asyncio
async def test_api_permission_error_is_clean() -> None:
    def handler(request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        if request.url.path == "/api/auth/me":
            return _json_response(200, ME)
        assert request.url.path == "/api/dashboard/finance"
        return _json_response(403, {"detail": "Missing permission"})

    async def callback(client: ERPApiClient, _seen: list[httpx.Request], settings: Settings) -> dict[str, Any]:
        return await erp_finance_summary_tool(settings=settings, client=client)

    result = await _with_client(handler, callback)
    assert result["ok"] is False
    assert result["error"]["status_code"] == 403
    assert result["error"]["message"] == "ERP permission denied for this tool."


@pytest.mark.asyncio
async def test_non_gm_user_is_blocked_by_mcp_gate() -> None:
    non_gm = {
        "id": 22,
        "name": "Operator",
        "email": "operator@example.com",
        "role": "Cutting",
        "department": "Cutting",
        "permissions": ["cutting.records"],
    }

    def handler(request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        assert request.url.path == "/api/auth/me"
        return _json_response(200, non_gm)

    async def callback(client: ERPApiClient, seen: list[httpx.Request], settings: Settings) -> dict[str, Any]:
        result = await erp_search_tool("SO-100", settings=settings, client=client)
        assert [request.url.path for request in seen] == ["/api/auth/me"]
        return result

    result = await _with_client(handler, callback)
    assert result["ok"] is False
    assert result["error"]["status_code"] == 403
    assert "GM-only" in result["error"]["message"]

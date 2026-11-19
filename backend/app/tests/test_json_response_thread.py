"""Prove response parity and that large encoders cannot monopolize the ASGI loop."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from inspect import iscoroutinefunction, signature
from threading import Event, get_ident

import httpx
import pytest
from fastapi import FastAPI

from app.core import json_response


def test_registered_heavy_reads_keep_signature_and_pure_payload_callers():
    from app.api.routes import inbox, inventory, process_tracking

    for router, path, original in [
        (inbox.router, "/inbox/department-orders", inbox.department_order_page),
        (inbox.router, "/inbox", inbox.department_inbox),
        (process_tracking.router, "/process-tracking", process_tracking.list_processes),
        (inventory.router, "/inventory/batches", inventory.list_batches),
        (inventory.router, "/inventory/stock", inventory.get_stock),
    ]:
        route = next(r for r in router.routes if r.path == path)
        assert route.endpoint.__wrapped__ is original
        assert signature(route.endpoint) == signature(original)
        assert not iscoroutinefunction(route.endpoint)
        assert route.response_model is None


@pytest.mark.parametrize("paged", [False, True])
def test_worker_json_matches_default_fastapi_bytes(paged):
    from fastapi.testclient import TestClient

    class State(str, Enum):
        READY = "ready"

    rows = [{"date": datetime(2026, 11, 19, 3, 4, 5, tzinfo=timezone.utc),
             "quantity": Decimal("12.50"), "state": State.READY,
             "nested": [None, "Ўзбекча / Русский", {"empty": []}]}]
    payload = {"rows": rows, "total": 1, "page": 1, "page_size": 100} if paged else rows

    def endpoint():
        return payload

    app = FastAPI()
    app.get("/default")(endpoint)
    app.get("/worker")(json_response.json_response_endpoint(endpoint))
    with TestClient(app) as client:
        old, new = client.get("/default"), client.get("/worker")
    assert new.status_code == old.status_code == 200
    assert new.content == old.content
    assert new.headers == old.headers
    assert endpoint() is payload


@pytest.mark.parametrize("path", ["/heavy", "/inventory/batches", "/inventory/stock"])
def test_blocked_encoder_leaves_event_loop_available(monkeypatch, path):
    entered, release = Event(), Event()
    encoder = json_response.jsonable_encoder
    encoding_threads = []
    rendering_threads = []
    render = json_response.JSONResponse.render

    def blocked(value):
        encoding_threads.append(get_ident())
        entered.set()
        assert release.wait(5), "test failed to release encoder"
        return encoder(value)

    monkeypatch.setattr(json_response, "jsonable_encoder", blocked)

    def traced_render(self, content):
        if isinstance(content, dict) and "rows" in content:
            rendering_threads.append(get_ident())
        return render(self, content)

    monkeypatch.setattr(json_response.JSONResponse, "render", traced_render)
    app = FastAPI()

    def heavy():
        return {"rows": [{"quantity": Decimal("2.5")}]}

    if path == "/heavy":
        app.get(path)(json_response.json_response_endpoint(heavy))
    else:
        from app.api.routes import inventory
        from app.db.session import get_db

        route = next(r for r in inventory.router.routes if r.path == path)
        permission = next(d.call for d in route.dependant.dependencies if d.name == "_")
        app.dependency_overrides[get_db] = lambda: object()
        app.dependency_overrides[permission] = lambda: object()
        monkeypatch.setattr(inventory.stock_service, "list_batches", lambda *a, **kw: heavy())
        monkeypatch.setattr(inventory.stock_service, "stock_view", lambda *a, **kw: heavy())
        app.include_router(inventory.router)

    @app.get("/health")
    async def health():
        return {"ok": True}

    async def run():
        loop_thread = get_ident()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            pending = asyncio.create_task(client.get(path))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                response = await asyncio.wait_for(client.get("/health"), 2)
                assert response.json() == {"ok": True}
                assert not pending.done()
                assert encoding_threads and loop_thread not in encoding_threads
            finally:
                release.set()
                response = await pending
            assert response.json() == {"rows": [{"quantity": 2.5}]}
            assert rendering_threads == encoding_threads

    asyncio.run(run())


def test_async_endpoint_is_rejected():
    async def endpoint():
        return {}

    with pytest.raises(TypeError, match="synchronous"):
        json_response.json_response_endpoint(endpoint)


@pytest.mark.parametrize("path,original_name,service_name", [
    ("/inventory/batches", "list_batches", "list_batches"),
    ("/inventory/stock", "get_stock", "stock_view"),
])
@pytest.mark.parametrize("paged", [False, True])
def test_inventory_http_contract_matches_original(monkeypatch, path, original_name, service_name, paged):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from app.api.routes import inventory
    from app.db.session import get_db

    original = getattr(inventory, original_name)
    registered = next(r for r in inventory.router.routes if r.path == path)
    permission = next(d.call for d in registered.dependant.dependencies if d.name == "_")
    db, actor = object(), object()
    rows = [{"id": 7, "quantity": Decimal("12.50"), "reserved_quantity": 2.0,
             "received_date": datetime(2026, 11, 19, 3, 4, 5, tzinfo=timezone.utc),
             "active_reservations": [{"unit": "кг", "remaining_quantity": 2.0}],
             "archived_at": None, "label": "Ўзбекча / Русский"}]
    payload = {"rows": rows, "total": 1, "page": 2, "page_size": 50} if paged else rows
    calls = []

    def service(*args, **kwargs):
        calls.append((args, kwargs))
        return payload

    monkeypatch.setattr(inventory.stock_service, service_name, service)
    control, candidate = FastAPI(), FastAPI()
    control.add_api_route(path, original, methods=["GET"], response_model=None)
    candidate.include_router(inventory.router)
    for app in (control, candidate):
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[permission] = lambda: actor
    # require_permissions returns its own callable for each original registration.
    control_route = next(r for r in control.routes if r.path == path)
    control_permission = next(d.call for d in control_route.dependant.dependencies if d.name == "_")
    control.dependency_overrides[control_permission] = lambda: actor
    query = "?q=кг&group=materials&page=2&page_size=50&include_total=" + str(paged).lower()
    if path.endswith("batches"):
        query += "&archived=true&hide_empty=true&item_ids=7,8"
    with TestClient(control) as old_client, TestClient(candidate) as new_client:
        old, new = old_client.get(path + query), new_client.get(path + query)
        assert old.status_code == new.status_code == 200
        assert old.content == new.content
        assert old.headers == new.headers
        assert calls[0] == calls[1]
        assert calls[1][0] == (db, actor)
        old_operation = control.openapi()["paths"][path]["get"]
        new_operation = candidate.openapi()["paths"][path]["get"]
        for field in ("parameters", "responses", "security"):
            assert old_operation.get(field) == new_operation.get(field)

        def denied():
            raise HTTPException(403, "Missing inventory permission")

        candidate.dependency_overrides[permission] = denied
        count = len(calls)
        assert new_client.get(path + query).status_code == 403
        assert len(calls) == count

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
    from app.api.routes import inbox, process_tracking

    for router, path, original in [
        (inbox.router, "/inbox/department-orders", inbox.department_order_page),
        (inbox.router, "/inbox", inbox.department_inbox),
        (process_tracking.router, "/process-tracking", process_tracking.list_processes),
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


def test_blocked_encoder_leaves_event_loop_available(monkeypatch):
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

    app.get("/heavy")(json_response.json_response_endpoint(heavy))

    @app.get("/health")
    async def health():
        return {"ok": True}

    async def run():
        loop_thread = get_ident()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            pending = asyncio.create_task(client.get("/heavy"))
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

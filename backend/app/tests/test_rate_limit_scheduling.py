import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, get_ident
import time

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app import main
from app.core import shared_store


def _request(path="/api/example", method="GET"):
    return Request({"type": "http", "method": method, "path": path,
                    "headers": [], "client": ("127.0.0.1", 1234),
                    "scheme": "http", "server": ("localhost", 80), "query_string": b""})


def test_rate_limit_storage_runs_off_event_loop(tmp_path, monkeypatch):
    store = shared_store.SQLiteSharedCounterStore(
        f"sqlite:///{(tmp_path / 'limits.db').as_posix()}", prefix="test")
    monkeypatch.setattr(main, "get_shared_counter_store", lambda: store)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_PER_MINUTE", 3)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_WINDOW_SECONDS", 60)
    loop_thread = get_ident()
    increment, ttl = store.increment, store.ttl

    def checked_increment(*args):
        assert get_ident() != loop_thread, "Counter I/O blocks the event loop"
        return increment(*args)

    def checked_ttl(*args):
        assert get_ident() != loop_thread, "Counter TTL I/O blocks the event loop"
        return ttl(*args)

    monkeypatch.setattr(store, "increment", checked_increment)
    monkeypatch.setattr(store, "ttl", checked_ttl)

    async def next_response(request):
        return Response(status_code=204)

    async def run():
        return await asyncio.gather(*[
            main._global_rate_limit(_request(), next_response) for _ in range(8)
        ])

    responses = asyncio.run(run())
    assert sum(response.status_code == 204 for response in responses) == 3
    rejected = [response for response in responses if response.status_code == 429]
    assert len(rejected) == 5
    assert all(1 <= int(response.headers["retry-after"]) <= 60 for response in rejected)


@pytest.mark.parametrize("path,method,enabled", [
    ("/health", "GET", True), ("/api/example", "OPTIONS", True),
    ("/api/example", "GET", False),
])
def test_rate_limit_bypass_does_not_access_storage(monkeypatch, path, method, enabled):
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_ENABLED", enabled)

    def forbidden_store():
        pytest.fail("Bypass must not access storage")

    monkeypatch.setattr(main, "get_shared_counter_store", forbidden_store)

    async def next_response(request):
        return Response(status_code=204)

    assert asyncio.run(main._global_rate_limit(_request(path, method), next_response)).status_code == 204


def test_shared_store_initialization_is_singleton_under_concurrency(monkeypatch):
    monkeypatch.setattr(shared_store, "_store", None)
    monkeypatch.setattr(shared_store.settings, "SHARED_STORE_URL", "sqlite:///unused-test.db")
    created = []
    barrier = Barrier(8)

    def construct(*args, **kwargs):
        time.sleep(.03)
        store = shared_store.InMemorySharedCounterStore()
        created.append(store)
        return store

    monkeypatch.setattr(shared_store, "SQLiteSharedCounterStore", construct)

    def get_store(_):
        barrier.wait(timeout=5)
        return shared_store.get_shared_counter_store()

    with ThreadPoolExecutor(max_workers=8) as pool:
        stores = list(pool.map(get_store, range(8)))
    assert len(created) == 1
    assert all(store is stores[0] for store in stores)


from app.tests.test_attendance_import_races import attendance_postgres_sessions  # noqa: F401


def test_postgres_roster_lock_survives_concurrent_rate_store_workers(
    attendance_postgres_sessions, tmp_path, monkeypatch,
):
    from app.api.routes import attendance
    from app.models import AttendancePerson
    from starlette.concurrency import run_in_threadpool

    sessions, engine = attendance_postgres_sessions
    store = shared_store.SQLiteSharedCounterStore(f"sqlite:///{tmp_path / 'limits.db'}", prefix="postgres")
    monkeypatch.setattr(main, "get_shared_counter_store", lambda: store)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_PER_MINUTE", 3)
    payload = attendance.PeopleSnapshotIn(
        device={"device_key": "perf37-roster", "name": "Synthetic", "vendor": "Hikvision",
                "source_host": "127.0.0.1", "reported_person_count": 1},
        people=[{"external_person_id": "37", "full_name": "Synthetic employee"}],
        full_snapshot=True,
    )

    def import_roster():
        with sessions() as db:
            attendance.import_people_snapshot(payload, db, identity=None)
        return Response(status_code=204)

    async def next_response(request):
        return await run_in_threadpool(import_roster)

    async def run():
        return await asyncio.gather(*[
            main._global_rate_limit(_request(), next_response) for _ in range(8)
        ])

    responses = asyncio.run(run())
    assert [r.status_code for r in responses].count(204) == 3
    assert [r.status_code for r in responses].count(429) == 5
    with sessions() as db:
        assert db.query(AttendancePerson).filter_by(external_person_id="37").count() == 1

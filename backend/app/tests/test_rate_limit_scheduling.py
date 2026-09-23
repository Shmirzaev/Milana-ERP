import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from threading import Barrier, get_ident
import time

import jwt
import pytest
from starlette.requests import Request
from starlette.responses import Response

from app import main
from app.core import shared_store
from app.core.config import settings
from app.core.security import create_access_token


def _request(path="/api/example", method="GET", *, headers=None, client_host="127.0.0.1"):
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request({"type": "http", "method": method, "path": path,
                    "headers": raw_headers, "client": (client_host, 1234),
                    "scheme": "http", "server": ("localhost", 80), "query_string": b""})


def _bearer(user_id):
    return {"authorization": f"Bearer {create_access_token(user_id)}"}


def _configure_limit(monkeypatch, store, *, limit=2, window=60):
    monkeypatch.setattr(main, "get_shared_counter_store", lambda: store)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_PER_MINUTE", limit)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_WINDOW_SECONDS", window)


async def _accepted(request):
    async def next_response(_request):
        return Response(status_code=204)

    return await main._global_rate_limit(request, next_response)


def test_rate_limit_storage_runs_off_event_loop(tmp_path, monkeypatch):
    store = shared_store.SQLiteSharedCounterStore(
        f"sqlite:///{(tmp_path / 'limits.db').as_posix()}", prefix="test")
    _configure_limit(monkeypatch, store, limit=3)
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


def test_authenticated_users_behind_one_ip_have_separate_budgets(monkeypatch):
    store = shared_store.InMemorySharedCounterStore()
    _configure_limit(monkeypatch, store, limit=2)
    shared_ip = {"x-forwarded-for": "203.0.113.20"}

    async def run():
        responses = []
        for user_id in (101, 101, 202, 202, 101, 202):
            headers = shared_ip | _bearer(user_id)
            responses.append(await _accepted(_request(headers=headers)))
        return responses

    responses = asyncio.run(run())
    assert [response.status_code for response in responses] == [204, 204, 204, 204, 429, 429]


def test_simultaneous_authenticated_limits_are_atomic_per_user(tmp_path, monkeypatch):
    store = shared_store.SQLiteSharedCounterStore(
        f"sqlite:///{(tmp_path / 'identity-limits.db').as_posix()}", prefix="test"
    )
    _configure_limit(monkeypatch, store, limit=3)

    async def run():
        async def one(user_id):
            response = await _accepted(_request(headers=_bearer(user_id)))
            return user_id, response.status_code

        return await asyncio.gather(*(one(user_id) for user_id in (101, 202) for _ in range(8)))

    results = asyncio.run(run())
    for user_id in (101, 202):
        statuses = [status for result_user_id, status in results if result_user_id == user_id]
        assert statuses.count(204) == 3
        assert statuses.count(429) == 5


def test_anonymous_and_invalid_tokens_share_the_ip_budget(monkeypatch):
    store = shared_store.InMemorySharedCounterStore()
    _configure_limit(monkeypatch, store, limit=2)
    forwarded = {"x-forwarded-for": "203.0.113.30"}
    invalid = forwarded | {"authorization": "Bearer not-a-jwt"}
    expired = jwt.encode(
        {"sub": "101", "exp": 1}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )

    async def run():
        return [
            await _accepted(_request(headers=forwarded)),
            await _accepted(_request(headers=invalid)),
            await _accepted(_request(headers=forwarded | {"authorization": f"Bearer {expired}"})),
        ]

    assert [response.status_code for response in asyncio.run(run())] == [204, 204, 429]


def test_public_auth_entry_points_stay_ip_scoped_without_token_oracle(monkeypatch):
    store = shared_store.InMemorySharedCounterStore()
    _configure_limit(monkeypatch, store, limit=2)
    forwarded = {"x-forwarded-for": "203.0.113.40"}

    async def run():
        return [
            await _accepted(_request("/api/auth/login-panel", headers=forwarded | _bearer(101))),
            await _accepted(_request("/api/auth/login-panel/", headers=forwarded | _bearer(202))),
            await _accepted(_request("/api/auth/login-panel", headers=forwarded | {"authorization": "Bearer invalid"})),
        ]

    assert [response.status_code for response in asyncio.run(run())] == [204, 204, 429]


@pytest.mark.parametrize("path", sorted(main._RATE_LIMIT_IP_ONLY_PATHS))
def test_every_public_auth_path_forces_ip_identity(path):
    request = _request(f"{path}/", headers=_bearer(101))
    assert main._rate_limit_identity_key(request) == "ip:127.0.0.1"


def test_proxy_headers_are_only_used_for_trusted_peers():
    forwarded = {"x-forwarded-for": "203.0.113.50, 10.0.0.1"}
    assert main._rate_limit_identity_key(_request(headers=forwarded)) == "ip:203.0.113.50"
    assert main._rate_limit_identity_key(
        _request(headers=forwarded, client_host="8.8.8.8")
    ) == "ip:8.8.8.8"


def test_cookie_credentials_use_the_same_canonical_user_identity():
    token = create_access_token("00101")
    request = _request(headers={"cookie": f"{settings.AUTH_COOKIE_NAME}={token}"})
    assert main._rate_limit_identity_key(request) == "user:101"


def test_rate_limit_identity_never_replaces_route_authentication(client, monkeypatch):
    _configure_limit(monkeypatch, shared_store.InMemorySharedCounterStore(), limit=100)
    signed_for_unknown_user = create_access_token(999_999_999)

    response = client.get(
        "/api/auth/me",
        headers={"authorization": f"Bearer {signed_for_unknown_user}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Inactive or unknown user"


def test_sqlite_fixed_window_ttl_expires_and_cleans_up(tmp_path, monkeypatch):
    store = shared_store.SQLiteSharedCounterStore(
        f"sqlite:///{(tmp_path / 'ttl.db').as_posix()}", prefix="test"
    )
    clock = [1_000.0]
    monkeypatch.setattr(shared_store, "time", SimpleNamespace(time=lambda: clock[0]))

    assert store.increment("bucket", 5) == 1
    clock[0] += 2
    assert store.increment("bucket", 5) == 2
    assert store.ttl("bucket") == 3
    clock[0] += 4
    assert store.ttl("bucket") is None
    assert store.increment("bucket", 5) == 1


def test_redis_increment_and_ttl_are_one_atomic_operation():
    calls = []

    class FakeRedis:
        def eval(self, script, key_count, key, ttl):
            calls.append((script, key_count, key, ttl))
            return 7

    store = object.__new__(shared_store.RedisSharedCounterStore)
    store._client = FakeRedis()
    store._prefix = "test"

    assert store.increment("bucket", 60) == 7
    assert len(calls) == 1
    script, key_count, key, ttl = calls[0]
    assert "INCR" in script and "EXPIRE" in script
    assert (key_count, key, ttl) == (1, "test:bucket", 60)


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

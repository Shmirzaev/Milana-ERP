import asyncio
from types import SimpleNamespace

from jose import jwt
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


@pytest.mark.parametrize("path", ["/api/auth/token", "/api/auth/login-panel", "/api/auth/forgot-password", "/api/auth/reset-password", "/api/session/login"])
def test_every_public_auth_path_forces_ip_identity(path):
    request = _request(f"{path}/", headers=_bearer(101))
    assert main._rate_limit_identity_key(request) == "ip:127.0.0.1"


def test_proxy_headers_are_only_used_for_trusted_peers(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,10.0.0.1/32")
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



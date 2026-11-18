from datetime import datetime, timedelta, timezone
from functools import partial
from threading import Event, Lock
from time import perf_counter

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.security import create_access_token, decode_token, hash_password
from app.core.signing import sign_path
from app.schemas import Role, User
from app.tests.conftest import TestSessionLocal, test_engine

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)


@pytest.fixture
def model_file_urls(tmp_path, monkeypatch):
    import app.main as main

    Image.new("RGB", (8, 8), "blue").save(tmp_path / "private.png")
    monkeypatch.setattr(main, "_MODEL_FILES_ROOT", str(tmp_path.resolve()))
    monkeypatch.setattr(main, "_MODEL_THUMBS_ROOT", str((tmp_path / "thumbs").resolve()))
    return (
        "/storage/model-files/private.png",
        "/storage/model-files/thumb/private.png?size=160",
    )


@pytest.fixture
def file_user(client):
    password = "SyntheticFileUser!2026"
    with TestSessionLocal() as db:
        role = Role(name="File viewer", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="File viewer",
            email="file-viewer@example.com",
            password_hash=hash_password(password),
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(user)
        db.commit()
        user_id = user.id
    login = client.post(
        "/api/auth/login-json",
        json={"email": "file-viewer@example.com", "password": password, "factory_code": "MIL"},
    )
    assert login.status_code == 200, login.text
    return user_id, client.cookies.get(settings.AUTH_COOKIE_NAME)


def _auth_headers(client, token, transport):
    client.cookies.clear()
    if transport == "cookie":
        client.cookies.set(settings.AUTH_COOKIE_NAME, token)
        return {}
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
def test_active_user_can_read_model_files(client, file_user, model_file_urls, transport):
    _, token = file_user
    headers = _auth_headers(client, token, transport)
    for url in model_file_urls:
        response = client.get(url, headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("image/")


@pytest.mark.parametrize("route_index", [0, 1], ids=["file", "thumbnail"])
@pytest.mark.parametrize("validator", ["if-none-match", "if-modified-since"])
def test_model_file_cache_revalidates_after_auth(client, file_user, model_file_urls, route_index, validator):
    user_id, token = file_user
    headers = _auth_headers(client, token, "cookie")
    url = model_file_urls[route_index]
    first = client.get(url, headers=headers)
    assert first.status_code == 200
    conditional_headers = {**headers, validator: first.headers["etag" if validator == "if-none-match" else "last-modified"]}
    active = client.get(url, headers=conditional_headers)
    assert active.status_code == 304
    assert active.content == b""
    assert first.headers["cache-control"] == active.headers["cache-control"] == "private, no-cache, must-revalidate"

    with TestSessionLocal() as db:
        db.get(User, user_id).is_active = False
        db.commit()
    revoked = client.get(url, headers=conditional_headers)
    assert revoked.status_code == 401
    assert revoked.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
@pytest.mark.parametrize("revocation", ["disabled", "deleted", "credentials_rotated"])
@pytest.mark.parametrize("route_index", [0, 1], ids=["file", "thumbnail"])
def test_revoked_user_cannot_read_model_files(
    client, file_user, model_file_urls, transport, revocation, route_index,
):
    user_id, token = file_user
    headers = _auth_headers(client, token, transport)
    # Warm the thumbnail cache too: a cached file must still require current auth.
    for url in model_file_urls:
        assert client.get(url, headers=headers).status_code == 200

    with TestSessionLocal() as db:
        user = db.get(User, user_id)
        if revocation == "disabled":
            user.is_active = False
        elif revocation == "deleted":
            db.delete(user)
        else:
            user.tokens_valid_from = datetime.fromtimestamp(decode_token(token)["iat"] + 1, timezone.utc)
        db.commit()

    assert client.get("/api/auth/me", headers=headers).status_code == 401
    response = client.get(model_file_urls[route_index], headers=headers)
    assert response.status_code == 401, response.text
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("credential", ["missing", "invalid", "expired"])
def test_model_files_reject_missing_invalid_or_expired_cookie(client, file_user, model_file_urls, credential):
    user_id, _ = file_user
    client.cookies.clear()
    if credential == "invalid":
        client.cookies.set(settings.AUTH_COOKIE_NAME, "invalid-token")
    elif credential == "expired":
        token = create_access_token(user_id, extra={"exp": int(datetime.now(timezone.utc).timestamp()) - 60})
        client.cookies.set(settings.AUTH_COOKIE_NAME, token)
    for url in model_file_urls:
        assert client.get(url).status_code == 401


def test_new_token_after_credential_rotation_can_read_model_files(client, file_user, model_file_urls):
    user_id, _ = file_user
    now = datetime.now(timezone.utc)
    with TestSessionLocal() as db:
        db.get(User, user_id).tokens_valid_from = now - timedelta(seconds=30)
        db.commit()
    old_token = create_access_token(user_id, extra={"iat": int((now - timedelta(minutes=1)).timestamp())})
    for token, expected in [(old_token, 401), (create_access_token(user_id), 200)]:
        headers = _auth_headers(client, token, "cookie")
        for url in model_file_urls:
            assert client.get(url, headers=headers).status_code == expected


def test_model_auth_releases_connection_before_reading_files(client, file_user, model_file_urls, monkeypatch):
    import app.main as main

    original = main._model_file_path_if_exists

    def checked_path(name):
        assert test_engine.pool.checkedout() == 0
        return original(name)

    monkeypatch.setattr(main, "_model_file_path_if_exists", checked_path)
    for url in model_file_urls:
        assert client.get(url).status_code == 200


def test_signed_model_url_does_not_replace_session_auth(client, model_file_urls):
    for url in model_file_urls:
        assert client.get(sign_path(url)).status_code == 401


def test_sales_attachment_signed_link_policy_is_preserved(client, file_user, tmp_path, monkeypatch):
    import app.main as main

    document = tmp_path / "attachment.txt"
    document.write_text("synthetic attachment", encoding="utf-8")
    monkeypatch.setattr(main, "_SALES_ORDER_FILES_ROOT", str(tmp_path.resolve()))
    path = "/storage/sales-order-files/attachment.txt"
    signed_url = sign_path(path)
    user_id, _ = file_user
    with TestSessionLocal() as db:
        db.get(User, user_id).is_active = False
        db.commit()

    # Signed sales links are bearer capabilities, independent of the session.
    assert client.get(signed_url).status_code == 200
    client.cookies.clear()
    assert client.get(signed_url).text == "synthetic attachment"
    assert client.get(path).status_code == 403
    assert client.get(sign_path(path, ttl_seconds=-60)).status_code == 403
    assert client.get(signed_url + "tampered").status_code == 403


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
def test_model_files_remain_company_wide(client, file_user, model_file_urls, factory):
    user_id, _ = file_user
    with TestSessionLocal() as db:
        db.get(User, user_id).factory_code = factory
        db.commit()
    token = create_access_token(user_id, extra={"factory_code": factory})
    headers = _auth_headers(client, token, "bearer")
    # Every factory can read the exact same model file and thumbnail, without
    # model permissions or ownership restrictions.
    for url in model_file_urls:
        assert client.get(url, headers=headers).status_code == 200


@pytest.mark.parametrize("database", ["sqlite", "postgresql"])
def test_model_image_burst_releases_authentication_pool(
    request, client, file_user, model_file_urls, monkeypatch, database,
):
    """A pending image must not need a second worker turn to release its connection."""
    import app.main as main
    from app.core.deps import get_db
    from app.db import session as session_module

    user_id, token = file_user
    if database == "postgresql":
        from app.tests import pg_approved_instance

        # Preserve the approved-instance identity and lifecycle checks, while
        # exercising the same 8+4 connection budget as the serving workers.
        monkeypatch.setattr(pg_approved_instance, "create_engine", partial(
            create_engine, pool_size=8, max_overflow=4, pool_timeout=1,
        ))
        pg_sessions = request.getfixturevalue("pg_sessions")
        pool_engine = pg_sessions.kw["bind"]
        with pg_sessions() as db:
            user = User(name="Image burst", email="image-burst@example.invalid",
                        password_hash="unused", factory_code="MIL", is_active=True)
            db.add(user)
            db.commit()
            user_id = user.id
        token = create_access_token(user_id, extra={"factory_code": "MIL"})
    else:
        pool_engine = create_engine(test_engine.url, connect_args={"check_same_thread": False},
                                    pool_size=8, max_overflow=4, pool_timeout=1)

    # Warm both filesystem paths before introducing the constrained pool.
    headers = {"Authorization": f"Bearer {file_user[1]}"}
    warm = [client.get(url, headers=headers) for url in model_file_urls]
    assert [response.status_code for response in warm] == [200, 200]
    headers = {"Authorization": f"Bearer {token}"}
    attempts = 0
    attempts_lock = Lock()
    workers_started = Event()

    class BurstSession(Session):
        def get(self, entity, ident, **kwargs):
            nonlocal attempts
            if entity is User:
                with attempts_lock:
                    attempts += 1
                    if attempts >= 40:
                        workers_started.set()
                user = super().get(entity, ident, **kwargs)
                assert workers_started.wait(5), "The bounded burst did not fill the 40 worker slots"
                return user
            return super().get(entity, ident, **kwargs)

    sessions = sessionmaker(bind=pool_engine, class_=BurstSession, autoflush=False, expire_on_commit=False)

    def pooled_db():
        with sessions() as db:
            yield db

    monkeypatch.setattr(session_module, "SessionLocal", sessions)
    monkeypatch.setitem(main.app.dependency_overrides, get_db, pooled_db)

    async def burst():
        limiter = anyio.to_thread.current_default_thread_limiter()
        original_tokens = limiter.total_tokens
        limiter.total_tokens = 40
        transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
        responses = [None] * 80
        durations = [0.0] * 80
        try:
            # Thread creation is outside the pool checkout budget. Start every
            # worker without a database connection before the measured burst;
            # BurstSession still holds checkouts until all 40 auth calls start.
            warm_workers = 0
            warm_lock = Lock()
            warm_started = Event()

            def warm_worker():
                nonlocal warm_workers
                with warm_lock:
                    warm_workers += 1
                    if warm_workers == 40:
                        warm_started.set()
                assert warm_started.wait(5), "The worker prewarm did not fill the 40 slots"

            with anyio.fail_after(10):
                async with anyio.create_task_group() as group:
                    for _ in range(40):
                        group.start_soon(anyio.to_thread.run_sync, warm_worker)
            assert warm_workers == 40

            async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as http:
                async def read_image(index):
                    started = perf_counter()
                    extra = {"If-None-Match": warm[1].headers["etag"]} if index % 2 else {}
                    responses[index] = await http.get(model_file_urls[index % 2], headers=extra)
                    durations[index] = perf_counter() - started

                with anyio.fail_after(20):
                    async with anyio.create_task_group() as group:
                        for index in range(80):
                            group.start_soon(read_image, index)
                assert [response.status_code for response in responses] == [200, 304] * 40
                assert pool_engine.pool.checkedout() == 0
                recovery = await http.get("/api/notifications/summary")
                assert recovery.status_code == 200, recovery.text
                assert recovery.json() == {"count": 0, "rows": []}
        finally:
            limiter.total_tokens = original_tokens
        print(f"{database}: 80 image reads, p95={sorted(durations)[75]:.3f}s, zero pool timeouts; API recovery passed")

    try:
        anyio.run(burst)
        assert attempts == 81  # Eighty images plus the recovery API authentication.
        assert pool_engine.pool.checkedout() == 0
    finally:
        if database == "sqlite":
            pool_engine.dispose()


@pytest.mark.parametrize("valid_bearer", [False, True])
def test_model_image_preserves_bearer_precedence(client, file_user, model_file_urls, valid_bearer):
    _, token = file_user
    client.cookies.set(settings.AUTH_COOKIE_NAME, "invalid-cookie" if valid_bearer else token)
    headers = {"Authorization": f"Bearer {token if valid_bearer else 'invalid-bearer'}"}
    for url in model_file_urls:
        response = client.get(url, headers=headers)
        assert response.status_code == (200 if valid_bearer else 401)
    assert test_engine.pool.checkedout() == 0


@pytest.mark.parametrize("denial", ["unassigned_factory", "inactive_band"])
def test_model_image_preserves_scope_denials(client, file_user, model_file_urls, denial):
    user_id, token = file_user
    if denial == "unassigned_factory":
        token = create_access_token(user_id, extra={"factory_code": "ECO"})
    else:
        with TestSessionLocal() as db:
            db.get(User, user_id).sewing_band_id = 999999
            db.commit()
    for url in model_file_urls:
        response = client.get(url, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403, response.text
        assert response.headers["cache-control"] == "private, no-store"
    assert test_engine.pool.checkedout() == 0


def test_model_image_authentication_error_releases_its_session(file_user, model_file_urls, monkeypatch):
    import app.main as main
    from app.db import session as session_module

    closed = []

    class FailingSession(Session):
        def get(self, entity, ident, **kwargs):
            super().get(entity, ident, **kwargs)
            raise RuntimeError("Injected authentication failure after database checkout")

        def close(self):
            super().close()
            closed.append(True)

    monkeypatch.setattr(session_module, "SessionLocal", sessionmaker(bind=test_engine, class_=FailingSession))
    with TestClient(main.app, raise_server_exceptions=False) as http:
        response = http.get(model_file_urls[0], headers={"Authorization": f"Bearer {file_user[1]}"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert closed == [True]
    assert test_engine.pool.checkedout() == 0

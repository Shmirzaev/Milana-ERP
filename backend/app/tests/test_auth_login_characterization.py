"""Current browser and bearer login contracts, before service extraction."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes import auth
from app.core.config import settings
from app.core.security import decode_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas import Role, User
from app.tests.conftest import TestSessionLocal
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)

PASSWORD = "AuthBaseline!2026"


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def login_database(request):
    if request.param == "sqlite":
        yield TestSessionLocal
        return
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as exc:
        require_or_skip(exc)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options="-ctimezone=UTC")
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        finalize_target(target, engine)


@pytest.fixture
def h(login_database):
    factory = login_database
    with factory() as db:
        role = Role(name=f"Auth baseline {uuid4().hex}", permissions=["finance.view"])
        db.add(role)
        db.flush()
        users = {}
        for active in (True, False):
            user = User(name="Auth baseline", email=f"auth-{uuid4().hex}@example.com",
                        password_hash=hash_password(PASSWORD), role_id=role.id,
                        factory_code="MIL", extra_permissions=["factory:ECO:finance.view"],
                        is_active=active)
            db.add(user)
            db.flush()
            users[active] = (user.id, user.email)
        db.commit()

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    try:
        yield factory, users, TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides[get_db] = previous


def activity(h):
    factory, users, _ = h
    with factory() as db:
        user = db.get(User, users[True][0])
        return user.last_login_at, user.last_seen_at


@pytest.mark.parametrize("path,kind", [
    ("/api/auth/login", "form"), ("/api/session/login", "form"),
    ("/api/auth/login-json", "json"), ("/api/session/login-json", "json"),
    ("/api/auth/token", "bearer"),
])
def test_success_commits_activity_and_preserves_token_transport(h, path, kind):
    _, users, client = h
    before = activity(h)
    if kind == "json":
        response = client.post(path, json={"email": users[True][1], "password": PASSWORD, "factory_code": "ECO"})
    else:
        response = client.post(path, data={"username": users[True][1], "password": PASSWORD})
    assert response.status_code == 200, response.text
    after = activity(h)
    assert after[0] is not None and after[1] is not None and after != before
    if kind == "bearer":
        assert "set-cookie" not in response.headers
        assert response.json()["token_type"] == "bearer"
        assert decode_token(response.json()["access_token"])["sub"] == str(users[True][0])
    else:
        assert response.json() == {"message": "logged_in"}
        assert "access_token" not in response.text
        cookie = response.cookies[settings.AUTH_COOKIE_NAME]
        assert decode_token(cookie)["sub"] == str(users[True][0])
        if kind == "json":
            assert decode_token(cookie)["factory_code"] == "ECO"
        assert "httponly" in response.headers["set-cookie"].lower()
        assert "samesite=lax" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize("case,status,detail", [
    ("missing", 401, "Invalid credentials"),
    ("wrong", 401, "Invalid credentials"),
    ("inactive", 401, "Invalid credentials"),
    ("wrong-before-factory", 401, "Invalid credentials"),
    ("unknown-factory", 400, "Factory must be MIL, BST, or ECO"),
    ("unassigned-factory", 403, "This account is not assigned to the selected factory"),
])
def test_refusal_order_detail_and_no_activity_or_cookie(h, case, status, detail):
    _, users, client = h
    email = users[False][1] if case == "inactive" else users[True][1]
    if case == "missing":
        email = f"missing-{uuid4().hex}@example.com"
    password = "wrong" if case in ("wrong", "wrong-before-factory") else PASSWORD
    factory_code = "XYZ" if case in ("unknown-factory", "wrong-before-factory") else "BST" if case == "unassigned-factory" else "MIL"
    before = activity(h)
    response = client.post("/api/auth/login-json", json={"email": email, "password": password, "factory_code": factory_code})
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert "set-cookie" not in response.headers
    assert activity(h) == before


def test_five_failures_lock_out_even_correct_password_before_lookup(h):
    _, users, client = h
    email = users[True][1]
    before = activity(h)
    for _ in range(5):
        response = client.post("/api/auth/login", data={"username": email, "password": "wrong"})
        assert (response.status_code, response.json()) == (401, {"detail": "Invalid credentials"})
    blocked = client.post("/api/auth/login", data={"username": email, "password": PASSWORD})
    assert (blocked.status_code, blocked.json()) == (429, {"detail": "Too many failed login attempts. Try again later."})
    assert int(blocked.headers["retry-after"]) > 0
    assert activity(h) == before


def test_shared_store_outage_returns_clean_503_without_activity(h, monkeypatch):
    _, users, client = h
    before = activity(h)

    def unavailable():
        raise ConnectionError("test store unavailable")

    monkeypatch.setattr(auth, "get_shared_counter_store", unavailable)
    response = client.post("/api/auth/login-json", json={"email": users[True][1], "password": PASSWORD, "factory_code": "MIL"})
    assert (response.status_code, response.json()) == (503, {"detail": "Authentication is temporarily unavailable. Try again later."})
    assert activity(h) == before

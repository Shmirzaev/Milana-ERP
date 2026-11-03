"""IDN-01 factory-switch baseline; current behavior, before service extraction."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import create_access_token, decode_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas import AuditLog, Role, User
from app.tests.conftest import TestSessionLocal
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def switch_database(request):
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
def h(switch_database):
    factory = switch_database
    with factory() as db:
        role = Role(name=f"IDN01 {uuid4().hex}", permissions=["planning.production"])
        db.add(role)
        db.flush()
        user = User(
            name="IDN01 fixture", email=f"idn01-{uuid4().hex}@example.com",
            password_hash="test-only", role_id=role.id, factory_code="MIL",
            extra_permissions=["finance.view", "factory:ECO:cutting.records", "factory:ECO:usluga.manage"],
            access_policy={"ECO": {"allow": ["usluga.view"], "deny": ["usluga.manage"]}},
            is_active=True,
        )
        db.add(user)
        db.commit()
        user_id = user.id

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    try:
        yield factory, user_id, TestClient(app)
    finally:
        app.dependency_overrides[get_db] = previous


def bearer(user_id, factory="MIL"):
    return {"Authorization": f"Bearer {create_access_token(user_id, {'factory_code': factory})}"}


def switch_with_expected_effects(h, code, *, path="/api/auth/switch-factory", headers=None, expected_audit=None):
    factory, user_id, client = h
    writes = []
    engine = factory.kw["bind"]

    def record_write(_connection, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    with factory() as db:
        before = db.query(AuditLog).count()
        user = db.get(User, user_id)
        assigned = (user.factory_code, user.extra_permissions, user.access_policy, user.tokens_valid_from)
    started = datetime.now(timezone.utc) - timedelta(seconds=5)
    event.listen(engine, "before_cursor_execute", record_write)
    try:
        response = client.post(path, json={"factory_code": code}, headers=headers or {})
    finally:
        event.remove(engine, "before_cursor_execute", record_write)
    with factory() as db:
        user = db.get(User, user_id)
        assert (user.factory_code, user.extra_permissions, user.access_policy, user.tokens_valid_from) == assigned
        entries = db.query(AuditLog).order_by(AuditLog.id).all()[before:]
        if expected_audit:
            # Decided after #382: a real factory change now writes exactly one audit row.
            old_factory, new_factory = expected_audit
            assert response.status_code == 200
            assert len(entries) == 1
            entry = entries[0]
            assert (entry.user_id, entry.action, entry.entity_type, entry.entity_id) == (
                user_id, "switch_factory", "User", user_id,
            )
            assert entry.old_value_json == {"factory_code": old_factory}
            assert entry.new_value_json == {"factory_code": new_factory}
            assert entry.entry_hash
            when = entry.created_at.replace(tzinfo=timezone.utc) if entry.created_at.tzinfo is None else entry.created_at
            assert started <= when <= datetime.now(timezone.utc) + timedelta(seconds=5)
            assert len(writes) == 1 and writes[0].lstrip().upper().startswith("INSERT INTO AUDIT_LOGS")
        else:
            assert entries == []
            assert writes == [], "refused or unchanged selection must not write"
    return response


@pytest.mark.parametrize("path", ["/api/auth/switch-factory", "/api/session/switch-factory"])
def test_allowed_switch_reissues_cookie_with_selected_claim_and_scoped_grants(h, path):
    _, user_id, client = h
    response = switch_with_expected_effects(h, " eco ", path=path, headers=bearer(user_id))
    # The raw length guard runs before normalization, so use a three-character code.
    assert response.status_code == 422
    assert response.json() == {"detail": "Factory code must be 1 to 3 characters"}

    response = switch_with_expected_effects(h, "eco", path=path, headers=bearer(user_id), expected_audit=("MIL", "ECO"))
    assert response.status_code == 200, response.text
    assert response.json() == {"message": "logged_in"}
    cookie = response.cookies[settings.AUTH_COOKIE_NAME]
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie and "path=/" in set_cookie
    assert decode_token(cookie)["factory_code"] == "ECO"
    client.cookies.clear()
    client.cookies.set(settings.AUTH_COOKIE_NAME, cookie)
    me = client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["factory_code"] == "ECO"
    assert me.json()["assigned_factory_code"] == "MIL"
    assert me.json()["available_factories"] == ["MIL", "ECO"]
    assert me.json()["permissions"] == ["cutting.records", "usluga.view"]
    assert me.json()["access_configured"] is True


def test_normalization_and_primary_permissions_on_return(h):
    _, user_id, client = h
    switch_with_expected_effects(h, "ECO", headers=bearer(user_id), expected_audit=("MIL", "ECO"))
    response = switch_with_expected_effects(h, " mil ", headers=bearer(user_id, "ECO"))
    assert response.status_code == 422
    response = switch_with_expected_effects(h, "mil", headers=bearer(user_id, "ECO"), expected_audit=("ECO", "MIL"))
    assert response.status_code == 200
    assert decode_token(response.cookies[settings.AUTH_COOKIE_NAME])["factory_code"] == "MIL"
    client.cookies.clear()
    me = client.get("/api/auth/me", headers=bearer(user_id, "MIL"))
    assert me.status_code == 200
    assert me.json()["permissions"] == ["planning.production", "finance.view"]


def test_reselecting_current_factory_does_not_add_a_switch_audit(h):
    _, user_id, _ = h
    response = switch_with_expected_effects(h, "mil", headers=bearer(user_id))
    assert response.status_code == 200
    assert decode_token(response.cookies[settings.AUTH_COOKIE_NAME])["factory_code"] == "MIL"


@pytest.mark.parametrize("code,status,detail", [
    ("BST", 403, "This account is not assigned to the selected factory"),
    ("", 422, "Factory code must be 1 to 3 characters"),
    ("MILX", 422, "Factory code must be 1 to 3 characters"),
    ("XYZ", 400, "Factory must be MIL, BST, or ECO"),
    ("   ", 400, "Factory must be MIL, BST, or ECO"),
])
def test_refused_factory_has_exact_error_and_no_new_cookie(h, code, status, detail):
    _, user_id, client = h
    response = switch_with_expected_effects(h, code, headers=bearer(user_id))
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert "set-cookie" not in response.headers


def test_policy_denies_only_secondary_grant_and_factory_becomes_unavailable(h):
    factory, user_id, _ = h
    with factory() as db:
        user = db.get(User, user_id)
        user.extra_permissions = ["factory:ECO:usluga.manage"]
        user.access_policy = {"ECO": {"deny": ["usluga.manage"]}}
        db.commit()
    response = switch_with_expected_effects(h, "ECO", headers=bearer(user_id))
    assert (response.status_code, response.json()) == (
        403, {"detail": "This account is not assigned to the selected factory"})
    assert "set-cookie" not in response.headers


def test_inactive_and_missing_auth_refuse_before_switch_validation(h):
    factory, user_id, client = h
    client.cookies.clear()
    missing = switch_with_expected_effects(h, "MILX")
    assert (missing.status_code, missing.json()) == (401, {"detail": "Not authenticated"})
    with factory() as db:
        db.get(User, user_id).is_active = False
        db.commit()
    inactive = switch_with_expected_effects(h, "MILX", headers=bearer(user_id))
    assert (inactive.status_code, inactive.json()) == (401, {"detail": "Inactive or unknown user"})
    assert "set-cookie" not in inactive.headers


@pytest.mark.parametrize("token_kind", ["malformed", "expired"])
def test_invalid_token_refuses_before_factory_selection(h, token_kind):
    _, user_id, client = h
    client.cookies.clear()
    token = (
        "not-a-jwt" if token_kind == "malformed" else
        create_access_token(user_id, {
            "factory_code": "MIL",
            "exp": int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp()),
        })
    )
    response = switch_with_expected_effects(h, "ECO", headers={"Authorization": f"Bearer {token}"})
    assert (response.status_code, response.json()) == (401, {"detail": "Invalid token"})
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
def test_old_token_retains_factory_until_its_grant_is_revoked(h, transport):
    factory, user_id, client = h
    old = create_access_token(user_id, {"factory_code": "ECO"})
    client.cookies.clear()
    if transport == "cookie":
        client.cookies.set(settings.AUTH_COOKIE_NAME, old)
        headers = None
    else:
        headers = {"Authorization": f"Bearer {old}"}
    switched = switch_with_expected_effects(h, "MIL", headers=headers, expected_audit=("ECO", "MIL"))
    assert switched.status_code == 200, switched.text
    new = switched.cookies[settings.AUTH_COOKIE_NAME]
    assert decode_token(new)["factory_code"] == "MIL"
    assert decode_token(old)["factory_code"] == "ECO"
    if transport == "cookie":
        client.cookies.clear()
        client.cookies.set(settings.AUTH_COOKIE_NAME, old)
        replay = client.get("/api/session/me")
    else:
        # The newly issued MIL cookie is present, but the old ECO bearer wins.
        replay = client.get("/api/session/me", headers={"Authorization": f"Bearer {old}"})
    assert replay.status_code == 200, replay.text
    assert replay.json()["factory_code"] == "ECO"
    assert replay.json()["permissions"] == ["cutting.records", "usluga.view"]

    with factory() as db:
        user = db.get(User, user_id)
        user.extra_permissions = ["finance.view"]
        user.access_policy = None
        db.commit()
    refused = client.get("/api/session/me", headers={"Authorization": f"Bearer {old}"} if transport == "bearer" else {})
    assert (refused.status_code, refused.json()) == (
        403, {"detail": "This account is not assigned to the selected factory"})
    client.cookies.clear()
    client.cookies.set(settings.AUTH_COOKIE_NAME, new)
    assert client.get("/api/session/me").json()["factory_code"] == "MIL"


def test_credential_cutoff_rejects_pre_rotation_factory_token(h):
    factory, user_id, _ = h
    old = create_access_token(user_id, {"factory_code": "ECO"})
    with factory() as db:
        db.get(User, user_id).tokens_valid_from = datetime.now(timezone.utc) + timedelta(seconds=1)
        db.commit()
    response = switch_with_expected_effects(h, "MIL", headers={"Authorization": f"Bearer {old}"})
    assert (response.status_code, response.json()) == (401, {"detail": "Token expired, please sign in again"})
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("body", [{}, {"factory_code": 7}])
def test_request_shape_is_validated_without_cookie(h, body):
    _, user_id, client = h
    client.cookies.clear()
    response = client.post("/api/auth/switch-factory", json=body, headers=bearer(user_id))
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "factory_code"]
    assert "set-cookie" not in response.headers

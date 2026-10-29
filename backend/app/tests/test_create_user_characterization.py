"""RF-009 create_user baseline; no extraction or new access policy is approved."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas import AuditLog, Department, PasswordResetToken, Role, User
from app.tests.conftest import TestSessionLocal
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)

PASSWORD = "BaselineUser!2026"


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def creation_database(request):
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
        # This operation uses only mapped identity columns, not migration-only generated columns.
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        finalize_target(target, engine)


@pytest.fixture(scope="module")
def actor_password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def h(creation_database, actor_password_hash, monkeypatch):
    factory = creation_database
    actors, roles = {}, {}
    with factory() as db:
        for key, permissions in {
            "manager": ["admin.users", "finance.view"],
            "wildcard": ["*"], "super": ["*", "admin.super"],
            "ordinary": ["finance.view"],
            "scoped": ["admin.users", "finance.view", "inventory.materials_only"],
            "eco_manager": ["admin.users", "finance.view"],
            "reader": ["finance.view"], "sales": ["sales.orders"],
        }.items():
            role = Role(name=f"RF009 {key} {uuid4().hex}", permissions=permissions)
            db.add(role)
            db.flush()
            roles[key] = role.id
            if key in {"reader", "sales"}:
                continue
            actor = User(name=f"RF009 {key}", email=f"{uuid4().hex}@example.com",
                         password_hash=actor_password_hash, role_id=role.id,
                         factory_code="ECO" if key == "eco_manager" else "MIL", is_active=True)
            db.add(actor)
            db.flush()
            actors[key] = (actor.id, {"Authorization": "Bearer " + create_access_token(
                actor.id, {"factory_code": actor.factory_code})})
        department = Department(name=f"RF009 department {uuid4().hex}", code=f"QA{uuid4().hex[:12]}")
        db.add(department)
        db.commit()
        department_id = department.id

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    messages = []

    def send(email, name, url):
        messages.append((email, name, url))
        return True

    monkeypatch.setattr("app.models.password_reset_service.send_password_setup_email", send)
    try:
        yield SimpleNamespace(db=factory, actors=actors, roles=roles, department=department_id,
                              email=f"rf009-{uuid4().hex}@example.com", messages=messages,
                              client=TestClient(app))
    finally:
        app.dependency_overrides[get_db] = previous


def payload(h, **changes):
    return {"name": "Baseline user", "email": h.email, "password": PASSWORD, **changes}


def create(h, actor="super", **changes):
    h.before = counts(h)
    return h.client.post("/api/users", headers=h.actors[actor][1], json=payload(h, **changes))


def counts(h):
    with h.db() as db:
        return tuple(db.query(model).count() for model in (User, PasswordResetToken, AuditLog))


def assert_refusal(h, changes, status, detail, actor="super"):
    before = counts(h)
    result = create(h, actor, **changes)
    assert result.status_code == status, result.text
    assert result.json() == {"detail": detail}
    assert counts(h) == before
    assert h.messages == []


def assert_created(h, result, *, actor="super", expected=None, setup=False):
    assert result.status_code == 201, result.text
    body = result.json()
    assert counts(h) == (h.before[0] + 1, h.before[1] + int(setup), h.before[2] + 1)
    # Independent literal UserOut fields; only generated ID/time are variable.
    golden = {"name": "Baseline user", "email": h.email, "role_id": None,
              "department_id": None, "factory_code": "MIL", "extra_permissions": [],
              "access_policy": None, "is_active": True, "last_login_at": None,
              "last_seen_at": None, **(expected or {})}
    assert body == {"id": body["id"], "created_at": body["created_at"], **golden}
    assert isinstance(body["id"], int) and body["id"] > 0
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z)?", body["created_at"])
    with h.db() as db:
        user = db.get(User, body["id"])
        for key, value in golden.items():
            assert getattr(user, key) == value
        assert user.password_hash != PASSWORD
        assert user.tokens_valid_from is None
        assert user.sewing_band_id is None
        stamp = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
        assert stamp.replace(tzinfo=None) == user.created_at.replace(tzinfo=None)
        assert body["created_at"].endswith("Z") == (db.bind.dialect.name == "postgresql")
        audit = db.query(AuditLog).filter_by(action="create", entity_type="User", entity_id=user.id).one()
        assert audit.user_id == h.actors[actor][0]
        assert audit.old_value_json is None
        assert audit.new_value_json == {
            "email": golden["email"], "password_setup_email_queued": setup,
            "role_id": golden["role_id"], "factory_code": golden["factory_code"],
            "extra_permissions": golden["extra_permissions"], "access_policy": golden["access_policy"],
        }
        assert re.fullmatch(r"[a-f0-9]{64}", audit.entry_hash)
        assert db.query(PasswordResetToken).filter_by(user_id=user.id).count() == int(setup)
        assert PASSWORD not in json.dumps(audit.new_value_json)
        assert user.password_hash not in result.text
    return body["id"]


def login_me(h, password=PASSWORD, factory="MIL", email=None):
    h.client.cookies.clear()
    response = h.client.post("/api/auth/login-json", json={
        "email": email or h.email, "password": password, "factory_code": factory,
    })
    assert response.status_code == 200, response.text
    assert response.json() == {"message": "logged_in"}
    me = h.client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    return me.json()


def test_create_persists_full_contract_audit_and_effective_permissions(h):
    result = create(h, name="  Baseline user  ", email=f"  {h.email.upper()}  ",
                    role_id=h.roles["reader"], department_id=h.department,
                    extra_permissions=[" sales.orders ", "sales.orders", ""],
                    access_policy={"MIL": {"allow": ["planning.view", "planning.view"], "deny": ["finance.view"]}})
    uid = assert_created(h, result, expected={
        "name": "  Baseline user  ", "role_id": h.roles["reader"], "department_id": h.department,
        "extra_permissions": ["sales.orders"],
        "access_policy": {"MIL": {"allow": ["planning.view"], "deny": ["finance.view"]}},
    })
    with h.db() as db:
        assert verify_password(PASSWORD, db.get(User, uid).password_hash)
    me = login_me(h)
    assert me["permissions"] == ["sales.orders", "planning.view"]
    assert me["factory_code"] == "MIL"
    assert me["department"] is not None


@pytest.mark.parametrize("actor", ["manager", "wildcard", "super"])
@pytest.mark.parametrize("active", [True, False])
def test_authorized_creators_may_set_active_flag_with_no_role(h, actor, active):
    result = create(h, actor, is_active=active)
    uid = assert_created(h, result, actor=actor, expected={"is_active": active})
    with h.db() as db:
        assert verify_password(PASSWORD, db.get(User, uid).password_hash)
    if active:
        assert login_me(h)["permissions"] == []
    else:
        response = h.client.post("/api/auth/token", data={"username": h.email, "password": PASSWORD})
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid credentials"}


@pytest.mark.parametrize("field", ["role_id", "extra_permissions", "access_policy", "is_active", "factory_code"])
def test_ordinary_user_cannot_set_any_privileged_field(h, field):
    values = {"role_id": h.roles["reader"], "extra_permissions": ["finance.view"],
              "access_policy": {"MIL": {"allow": ["finance.view"]}}, "is_active": False, "factory_code": "MIL"}
    assert_refusal(h, {field: values[field]}, 403,
                   "Missing permission. Need any of: ['admin.users', '*']", actor="ordinary")


@pytest.mark.parametrize("actor,role,status,detail", [
    ("manager", "reader", 201, None), ("wildcard", "reader", 201, None),
    ("super", "wildcard", 201, None), ("super", "super", 201, None),
    ("manager", "sales", 403, "You cannot grant permissions you don't hold: ['sales.orders']"),
    ("manager", "wildcard", 403, "Only a super admin can assign administrator roles"),
    ("wildcard", "wildcard", 403, "Only a super admin can assign administrator roles"),
    ("manager", "super", 403, "Only a super admin can assign administrator roles"),
    ("wildcard", "super", 403, "Only a super admin can assign administrator roles"),
])
def test_role_grant_boundary(h, actor, role, status, detail):
    if status != 201:
        assert_refusal(h, {"role_id": h.roles[role]}, status, detail, actor)
    else:
        result = create(h, actor, role_id=h.roles[role])
        assert_created(h, result, actor=actor, expected={"role_id": h.roles[role]})
        assert login_me(h)["permissions"] == {"reader": ["finance.view"], "wildcard": ["*"], "super": ["*", "admin.super"]}[role]


@pytest.mark.parametrize("actor,grants,status,detail", [
    ("manager", ["finance.view"], 201, None),
    ("super", ["*", "admin.super"], 201, None),
    ("super", ["legacy.custom"], 201, None),
    ("manager", ["sales.orders"], 403, "You cannot grant permissions you don't hold: ['sales.orders']"),
    ("manager", ["*"], 403, "Only a super admin can grant administrator access"),
    ("wildcard", ["admin.super"], 403, "Only a super admin can grant administrator access"),
    ("wildcard", ["*"], 403, "Only a super admin can grant administrator access"),
    ("manager", ["factory:ECO:finance.view"], 403, "Only Super Admin can configure another factory"),
    ("wildcard", ["factory:ECO:finance.view"], 403, "Only Super Admin can configure another factory"),
    ("manager", ["factory:BAD:finance.view"], 400, "Factory must be MIL, BST, or ECO"),
    ("manager", ["factory:MIL:"], 400, "Invalid factory permission"),
])
def test_extra_permission_grant_boundary(h, actor, grants, status, detail):
    if status != 201:
        assert_refusal(h, {"extra_permissions": grants}, status, detail, actor)
    else:
        result = create(h, actor, extra_permissions=grants)
        assert_created(h, result, actor=actor, expected={"extra_permissions": grants})
        assert login_me(h)["permissions"] == grants


def test_super_scoped_grant_allows_secondary_factory_without_leaking_primary_role(h):
    result = create(h, role_id=h.roles["reader"], extra_permissions=["factory:ECO:cutting.records"])
    assert_created(h, result, expected={"role_id": h.roles["reader"], "extra_permissions": ["factory:ECO:cutting.records"]})
    assert login_me(h)["permissions"] == ["finance.view"]
    assert login_me(h, factory="ECO")["permissions"] == ["cutting.records"]


def test_own_factory_scoped_grant_is_stored_but_primary_role_remains_authoritative(h):
    result = create(h, "manager", extra_permissions=["factory:MIL:finance.view"])
    assert_created(h, result, actor="manager", expected={"extra_permissions": ["factory:MIL:finance.view"]})
    assert login_me(h)["permissions"] == []


@pytest.mark.parametrize("actor,factory,allow,deny,status,detail", [
    ("manager", "MIL", ["finance.view"], [], 201, None),
    ("super", "ECO", ["finance.view"], [], 201, None),
    ("super", "MIL", ["admin.super"], [], 201, None),
    ("wildcard", "MIL", ["sales.orders"], [], 201, None),
    ("manager", "MIL", ["sales.orders"], [], 403, "You cannot grant permissions you don't hold"),
    ("manager", "MIL", ["admin.super"], [], 403, "Only Super Admin can grant administrator access"),
    ("wildcard", "MIL", ["*"], [], 403, "Only Super Admin can grant administrator access"),
    ("manager", "ECO", ["finance.view"], [], 403, "Only Super Admin can configure another factory"),
    ("wildcard", "ECO", [], ["finance.view"], 403, "Only Super Admin can configure another factory"),
    ("super", "ECO", ["admin.super"], [], 400, "Super Admin access is configured in the primary factory only"),
    ("scoped", "MIL", ["finance.view"], [], 403, "You cannot remove your own inventory scope from another account"),
    ("scoped", "MIL", ["finance.view", "inventory.materials_only"], [], 201, None),
])
def test_access_policy_grant_boundary(h, actor, factory, allow, deny, status, detail):
    policy = {factory: {"allow": allow, "deny": deny}}
    if status != 201:
        assert_refusal(h, {"access_policy": policy}, status, detail, actor)
    else:
        result = create(h, actor, access_policy=policy)
        assert_created(h, result, actor=actor, expected={"access_policy": policy})
        assert login_me(h, factory=factory)["permissions"] == allow


@pytest.mark.parametrize("actor,factory,status", [
    ("manager", " mil ", 201), ("manager", "ECO", 403), ("wildcard", "BST", 403),
    ("super", "BST", 201), ("super", " eco ", 201), ("eco_manager", "", 201),
])
def test_factory_assignment_boundary(h, actor, factory, status):
    if status != 201:
        assert_refusal(h, {"factory_code": factory}, status, "Only Super Admin can assign another factory", actor)
    else:
        expected = "ECO" if actor == "eco_manager" else factory.strip().upper()
        result = create(h, actor, factory_code=factory)
        assert_created(h, result, actor=actor, expected={"factory_code": expected})
        assert login_me(h, factory=expected)["permissions"] == []


def test_omitted_factory_defaults_to_mil_even_for_eco_manager(h):
    assert_refusal(h, {}, 403, "Only Super Admin can assign another factory", "eco_manager")


@pytest.mark.parametrize("changes,status,detail", [
    ({"password": "short1"}, 400, "Password must be at least 12 characters."),
    ({"password": "Abcdefghijkl"}, 400, "Password must include a number."),
    ({"password": "123456789012"}, 400, "Password must include a letter."),
    ({"password": " Abcdef123456"}, 400, "Password must not start or end with spaces."),
    ({"password": "password123"}, 400, "Password must be at least 12 characters, not use a shared default password."),
    ({"role_id": 2000000000}, 404, "Role not found"),
    ({"department_id": 2000000000}, 404, "Department not found"),
    ({"factory_code": "BAD"}, 400, "Factory must be MIL, BST, or ECO"),
    ({"name": "N" * 129}, 422, "User name must be at most 128 characters"),
    ({"email": "a" * 244 + "@example.com"}, 422, "User email must be at most 255 characters"),
    ({"password": "short1", "role_id": 2000000000}, 400, "Password must be at least 12 characters."),
    ({"department_id": 2000000000, "name": "N" * 129}, 404, "Department not found"),
])
def test_refusal_detail_and_atomicity(h, changes, status, detail):
    assert_refusal(h, changes, status, detail)


@pytest.mark.parametrize("name", ["N" * 128, "Я" * 128, "", " padded "])
def test_name_boundary_and_legacy_empty_name(h, name):
    result = create(h, name=name)
    assert_created(h, result, expected={"name": name})


def test_email_boundary_counts_normalized_value(h):
    email = "a" * 243 + "@example.com"
    assert len(email) == 255
    result = create(h, email=" " + email.upper() + " ")
    assert_created(h, result, expected={"email": email})


def test_duplicate_normalized_email_precedes_factory_validation_without_writes(h):
    assert_created(h, create(h))
    before = counts(h)
    response = create(h, email=" " + h.email.upper() + " ", factory_code="BAD", password=None)
    assert response.status_code == 400
    assert response.json() == {"detail": "Email already exists"}
    assert counts(h) == before
    assert h.messages == []


@pytest.mark.parametrize("password", ["Abcdef123456", "A" * 72 + "LongSuffix!2026"])
def test_credentials_preserve_minimum_length_and_beyond_bcrypt_limit(h, password):
    uid = assert_created(h, create(h, password=password))
    with h.db() as db:
        encoded = db.get(User, uid).password_hash
        assert encoded.startswith("$bcrypt-sha256$")
        assert verify_password(password, encoded)
        assert not verify_password(password + "different", encoded)
    assert login_me(h, password=password)["permissions"] == []


@pytest.mark.parametrize("active", [True, False])
@pytest.mark.parametrize("password", ["omitted", None, ""])
def test_passwordless_setup_token_contract(h, active, password):
    body = payload(h, is_active=active)
    if password == "omitted":
        del body["password"]
    else:
        body["password"] = password
    before = datetime.now(timezone.utc)
    h.before = counts(h)
    result = h.client.post("/api/users", headers=h.actors["super"][1], json=body)
    uid = assert_created(h, result, expected={"is_active": active}, setup=active)
    assert len(h.messages) == int(active)
    with h.db() as db:
        user = db.get(User, uid)
        assert not verify_password(PASSWORD, user.password_hash)
        if active:
            email, name, url = h.messages[0]
            assert (email, name) == (h.email, "Baseline user")
            assert urlparse(url).path == "/reset-password"
            raw = parse_qs(urlparse(url).query)["token"][0]
            token = db.query(PasswordResetToken).filter_by(user_id=uid).one()
            assert token.token_hash == hashlib.sha256(raw.encode()).hexdigest()
            assert token.used_at is None
            assert before + timedelta(minutes=59) < token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) + timedelta(minutes=61)
            audit = db.query(AuditLog).filter_by(action="create", entity_type="User", entity_id=uid).one()
            assert raw not in result.text + json.dumps(audit.new_value_json) + user.password_hash
            assert token.token_hash not in result.text
    denied = h.client.post("/api/auth/token", data={"username": h.email, "password": PASSWORD})
    assert denied.status_code == 401
    assert denied.json() == {"detail": "Invalid credentials"}


def test_setup_is_scheduled_and_delivered_only_after_single_commit(h, monkeypatch):
    timeline = []
    original = BackgroundTasks.add_task

    def scheduled(self, *args, **kwargs):
        assert timeline == ["before_commit", "after_commit"]
        timeline.append("scheduled")
        return original(self, *args, **kwargs)

    def sender(email, name, url):
        assert timeline == ["before_commit", "after_commit", "scheduled"]
        with h.db() as db:
            user = db.query(User).filter_by(email=email).one()
            assert db.query(PasswordResetToken).filter_by(user_id=user.id).count() == 1
            assert db.query(AuditLog).filter_by(action="create", entity_type="User", entity_id=user.id).count() == 1
        timeline.append("delivered")
        return True

    def before_commit(db):
        assert timeline == []
        timeline.append("before_commit")

    def after_commit(db):
        timeline.append("after_commit")

    monkeypatch.setattr(BackgroundTasks, "add_task", scheduled)
    monkeypatch.setattr("app.models.password_reset_service.send_password_setup_email", sender)
    event.listen(h.db.class_, "before_commit", before_commit)
    event.listen(h.db.class_, "after_commit", after_commit)
    try:
        result = create(h, password=None)
    finally:
        event.remove(h.db.class_, "before_commit", before_commit)
        event.remove(h.db.class_, "after_commit", after_commit)
    assert_created(h, result, setup=True)
    assert timeline == ["before_commit", "after_commit", "scheduled", "delivered"]


def test_commit_failure_rolls_back_user_token_audit_and_never_schedules_email(h, monkeypatch):
    before = counts(h)
    queued = []
    original = BackgroundTasks.add_task

    def schedule(self, *args, **kwargs):
        queued.append(args)
        return original(self, *args, **kwargs)

    def fail_commit(db):
        raise RuntimeError("Synthetic commit failure")

    monkeypatch.setattr(BackgroundTasks, "add_task", schedule)
    event.listen(h.db.class_, "before_commit", fail_commit)
    try:
        result = TestClient(app, raise_server_exceptions=False).post(
            "/api/users", headers=h.actors["super"][1], json=payload(h, password=None))
    finally:
        event.remove(h.db.class_, "before_commit", fail_commit)
    assert result.status_code == 500
    assert result.json() == {"detail": "Internal server error"}
    assert counts(h) == before
    assert h.messages == queued == []


@pytest.mark.parametrize("inactive", [False, True])
def test_missing_or_inactive_actor_cannot_create(h, inactive):
    headers = {}
    if inactive:
        with h.db() as db:
            db.get(User, h.actors["manager"][0]).is_active = False
            db.commit()
        headers = h.actors["manager"][1]
    before = counts(h)
    response = h.client.post("/api/users", headers=headers, json=payload(h))
    assert response.status_code == 401
    assert response.json() == {"detail": "Inactive or unknown user" if inactive else "Not authenticated"}
    assert counts(h) == before
    assert h.messages == []


@pytest.mark.parametrize("actor", ["manager", "wildcard", "super"])
def test_super_admin_role_name_is_privileged_even_without_permission_tokens(h, actor):
    with h.db() as db:
        role = Role(name=" " * (len(actor) + 1) + "Super Admin  ", permissions=[])
        db.add(role)
        db.commit()
        role_id = role.id
    if actor == "super":
        assert_created(h, create(h, actor, role_id=role_id), actor=actor, expected={"role_id": role_id})
        assert login_me(h)["permissions"] == []
    else:
        assert_refusal(h, {"role_id": role_id}, 403, "Only a super admin can assign administrator roles", actor)


@pytest.mark.parametrize("policy,detail", [
    ({"BAD": {"allow": ["finance.view"]}}, {
        "type": "literal_error", "loc": ["body", "access_policy", "BAD", "[key]"],
        "msg": "Input should be 'MIL', 'BST' or 'ECO'", "input": "BAD",
        "ctx": {"expected": "'MIL', 'BST' or 'ECO'"}}),
    ({"MIL": {"allow": ["not.real"]}}, {
        "type": "value_error", "loc": ["body", "access_policy", "MIL"],
        "msg": "Value error, Unknown permissions: ['not.real']", "input": {"allow": ["not.real"]},
        "ctx": {"error": {}}}),
    ({"MIL": {"allow": ["finance.view"], "deny": ["finance.view"]}}, {
        "type": "value_error", "loc": ["body", "access_policy", "MIL"],
        "msg": "Value error, A permission cannot be both allowed and denied",
        "input": {"allow": ["finance.view"], "deny": ["finance.view"]}, "ctx": {"error": {}}}),
    ({"MIL": {"unexpected": True}}, {
        "type": "extra_forbidden", "loc": ["body", "access_policy", "MIL", "unexpected"],
        "msg": "Extra inputs are not permitted", "input": True}),
])
def test_invalid_policy_detail_preserves_all_rows(h, policy, detail):
    assert_refusal(h, {"access_policy": policy}, 422, [detail])


@pytest.mark.parametrize("field,error_type,message", [
    ("role_id", None, None), ("access_policy", None, None),
    ("extra_permissions", "list_type", "Input should be a valid list"),
    ("is_active", "bool_type", "Input should be a valid boolean"),
    ("factory_code", "string_type", "Input should be a valid string"),
])
def test_privileged_field_explicit_null_contract(h, field, error_type, message):
    if error_type is None:
        assert_created(h, create(h, **{field: None}))
    else:
        assert_refusal(h, {field: None}, 422, [{
            "type": error_type, "loc": ["body", field], "msg": message, "input": None,
        }])


def test_policy_deny_overrides_explicit_extra_grant(h):
    policy = {"MIL": {"allow": [], "deny": ["finance.view"]}}
    assert_created(h, create(h, extra_permissions=["finance.view"], access_policy=policy),
                   expected={"extra_permissions": ["finance.view"], "access_policy": policy})
    assert login_me(h)["permissions"] == []


def test_client_supplied_credential_and_server_owned_fields_are_ignored(h):
    result = create(h, id=2000000000, password_hash="client-selected-hash",
                    tokens_valid_from="2099-01-01T00:00:00Z", last_login_at="2099-01-01T00:00:00Z",
                    last_seen_at="2099-01-01T00:00:00Z", sewing_band_id=2000000000)
    uid = assert_created(h, result)
    assert uid != 2000000000
    with h.db() as db:
        assert verify_password(PASSWORD, db.get(User, uid).password_hash)
    assert login_me(h)["permissions"] == []


def test_current_admin_ui_payload_preserves_empty_policy_and_setup_login(h):
    h.before = counts(h)
    response = h.client.post("/api/users", headers=h.actors["manager"][1], json={
        "name": "Baseline user", "email": h.email, "role_id": None, "department_id": None,
        "factory_code": "MIL", "is_active": True, "access_policy": {},
    })
    uid = assert_created(h, response, actor="manager", expected={"access_policy": {}}, setup=True)
    assert len(h.messages) == 1
    raw = parse_qs(urlparse(h.messages[0][2]).query)["token"][0]
    reset = h.client.post("/api/auth/reset-password", json={
        "token": raw, "new_password": PASSWORD, "confirm_new_password": PASSWORD,
    })
    assert reset.status_code == 200, reset.text
    assert reset.json() == {"message": "password_reset"}
    with h.db() as db:
        user = db.get(User, uid)
        assert user.access_policy == {}
        assert verify_password(PASSWORD, user.password_hash)
        assert user.tokens_valid_from is not None
        token = db.query(PasswordResetToken).filter_by(user_id=uid).one()
        assert token.token_hash == hashlib.sha256(raw.encode()).hexdigest()
        assert token.used_at is not None
    assert login_me(h)["permissions"] == []

import asyncio
import json

import pytest
from starlette.requests import Request

from app.api.routes import admin
from app.core import proxy_trust
from app.core.config import settings
from app.core.request_body_limit import AuthRequestBodyLimitMiddleware
from app.core.security import verify_password
from app.db.session import SessionLocal
from app.models import AuditLog, PasswordResetToken, User
from app.schemas.catalog import UserUpdate
from app.services.password_reset import create_password_reset_token, password_reset_hash
from app.services.credentials import validate_credential_runtime_configuration


ORIGINAL_PASSWORD = "BoundaryOriginal!2026"
REPLACEMENT_PASSWORD = "BoundaryReplacement!2026"
WEAK_PASSWORD = "short1"


def _request(
    *, peer: str, headers: dict[str, str] | list[tuple[str, str]] | None = None, scheme: str = "http",
) -> Request:
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers.items() if isinstance(headers, dict) else headers or [])
    ]
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (peer, 50000),
        "scheme": scheme,
        "server": ("erp.example", 80),
        "query_string": b"",
    })


def _create_user(client, auth_headers, *, email: str, password: str = ORIGINAL_PASSWORD) -> int:
    response = client.post(
        "/api/users",
        headers=auth_headers,
        json={"name": "SEC09 target", "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _login(client, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/token", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _reset_link(user_id: int) -> str:
    with SessionLocal() as db:
        token = create_password_reset_token(db, db.get(User, user_id))
        db.commit()
        return token


def test_forwarding_headers_default_to_fail_closed_for_private_and_loopback_peers(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    headers = {"x-forwarded-for": "198.51.100.10", "x-forwarded-proto": "https"}
    for peer in ("127.0.0.1", "10.20.30.40"):
        request = _request(peer=peer, headers=headers)
        assert proxy_trust.client_ip(request) == peer
        assert proxy_trust.effective_request_scheme(request) == "http"


def test_forwarding_chain_strips_only_explicit_trusted_hops(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,10.0.0.0/8")
    request = _request(
        peer="127.0.0.1",
        headers={
            "x-forwarded-for": "198.51.100.10, 10.20.30.40",
            "x-forwarded-proto": "http, https",
        },
    )
    assert proxy_trust.client_ip(request) == "198.51.100.10"
    assert proxy_trust.effective_request_scheme(request) == "https"

    malformed = _request(
        peer="127.0.0.1",
        headers={"x-forwarded-for": "198.51.100.10, not-an-ip"},
    )
    assert proxy_trust.client_ip(malformed) == "127.0.0.1"

    empty_hop = _request(
        peer="127.0.0.1",
        headers={"x-forwarded-for": "198.51.100.10,,10.20.30.40"},
    )
    assert proxy_trust.client_ip(empty_hop) == "127.0.0.1"


def test_duplicate_forwarding_fields_use_the_proxy_appended_hop(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    fields = [
        ("x-forwarded-for", "203.0.113.66"),  # untrusted client input
        ("x-forwarded-proto", "http"),
        ("x-forwarded-for", "198.51.100.10"),  # trusted proxy appends this field
        ("x-forwarded-proto", "https"),
    ]
    trusted = _request(peer="127.0.0.1", headers=fields)
    assert proxy_trust.client_ip(trusted) == "198.51.100.10"
    assert proxy_trust.effective_request_scheme(trusted) == "https"

    direct = _request(peer="192.0.2.7", headers=fields)
    assert proxy_trust.client_ip(direct) == "192.0.2.7"
    assert proxy_trust.effective_request_scheme(direct) == "http"

    for last_hop in ("", "not-an-ip"):
        malformed = _request(peer="127.0.0.1", headers=[
            ("x-forwarded-for", "203.0.113.66"),
            ("x-forwarded-for", last_hop),
        ])
        assert proxy_trust.client_ip(malformed) == "127.0.0.1"


def test_untrusted_forwarded_https_cannot_mark_login_cookie_secure(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    with TestClient(app, client=("8.8.8.8", 50000)) as direct_client:
        response = direct_client.post(
            "/api/auth/login",
            data={"username": "admin@example.com", "password": "test-admin-password-123!"},
            headers={"x-forwarded-proto": "https"},
        )
    assert response.status_code == 200, response.text
    attributes = response.headers["set-cookie"].lower().split(";")
    assert " secure" not in attributes


def test_hosted_proxy_configuration_requires_one_explicit_owner(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_CIDRS"):
        proxy_trust.validate_proxy_runtime_configuration(strict_security_required=True)

    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
    with pytest.raises(RuntimeError, match="FORWARDED_ALLOW_IPS"):
        proxy_trust.validate_proxy_runtime_configuration(strict_security_required=True)

    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "")
    proxy_trust.validate_proxy_runtime_configuration(strict_security_required=True)


@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "::/0", "10.20.30.40/16"])
def test_hosted_proxy_configuration_rejects_unbounded_or_noncanonical_networks(monkeypatch, cidr):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", cidr)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "")

    with pytest.raises(RuntimeError, match="must contain valid, non-default IP networks"):
        proxy_trust.validate_proxy_runtime_configuration(strict_security_required=True)


def test_hosted_runtime_rejects_weak_configured_or_demo_credentials(monkeypatch):
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", WEAK_PASSWORD)
    monkeypatch.setattr(settings, "AI_MONITOR_PASSWORD", "")
    monkeypatch.setattr(settings, "SEED_DEMO_USERS", False)
    with pytest.raises(RuntimeError, match="INITIAL_ADMIN_PASSWORD"):
        validate_credential_runtime_configuration(strict_security_required=True)

    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", ORIGINAL_PASSWORD)
    monkeypatch.setattr(settings, "SEED_DEMO_USERS", True)
    with pytest.raises(RuntimeError, match="SEED_DEMO_USERS"):
        validate_credential_runtime_configuration(strict_security_required=True)


def test_public_auth_body_limit_preserves_exact_boundary_and_validation(client, monkeypatch):
    limit = 256
    monkeypatch.setenv("AUTH_REQUEST_MAX_BYTES", str(limit))
    prefix = b'{"email":"missing@example.com","password":"x","factory_code":"MIL","padding":"'
    suffix = b'"}'
    exact = prefix + (b"x" * (limit - len(prefix) - len(suffix))) + suffix
    assert len(exact) == limit

    accepted = client.post("/api/auth/login-json", content=exact, headers={"content-type": "application/json"})
    assert accepted.status_code == 401, accepted.text
    oversized = client.post(
        "/api/auth/login-json",
        content=exact + b" ",
        headers={"content-type": "application/json"},
    )
    assert oversized.status_code == 413
    assert oversized.json() == {"detail": "Request body too large"}
    multipart_login = client.post(
        "/api/auth/login",
        content=b"x" * (limit + 1),
        headers={"content-type": "multipart/form-data; boundary=synthetic"},
    )
    assert multipart_login.status_code == 413

    malformed = client.post(
        "/api/auth/login-json",
        content=b"{",
        headers={"content-type": "application/json"},
    )
    assert malformed.status_code == 422

    # Authenticated state-changing routes are intentionally outside the public
    # parser cap, so missing credentials still win over body validation.
    protected = client.post(
        "/api/auth/change-password",
        content=exact + b" ",
        headers={"content-type": "application/json"},
    )
    assert protected.status_code == 401
    protected_upload = client.post(
        "/api/settings/company-logo/upload",
        files={"file": ("large.png", b"x" * (limit + 1), "image/png")},
    )
    assert protected_upload.status_code == 401


@pytest.mark.parametrize("extra_bytes,expected_status", [(0, 204), (1, 413)])
def test_auth_body_limit_counts_chunked_streams_without_buffering(
    monkeypatch, extra_bytes, expected_status,
):
    limit = 8
    monkeypatch.setenv("AUTH_REQUEST_MAX_BYTES", str(limit))
    received: list[bytes] = []

    async def inner(scope, receive, send):
        while True:
            message = await receive()
            received.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    chunks = [
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.request", "body": b"5678" + (b"9" * extra_bytes), "more_body": False},
    ]
    sent = []

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/reset-password",
        "headers": [(b"content-type", b"application/json")],
    }
    asyncio.run(AuthRequestBodyLimitMiddleware(inner)(scope, receive, send))
    assert next(message["status"] for message in sent if message["type"] == "http.response.start") == expected_status
    if extra_bytes:
        assert received == [b"1234", b""]
    else:
        assert received == [b"1234", b"5678"]


def test_installed_auth_body_middleware_rejects_chunked_oversize_before_route(
    monkeypatch,
):
    from app.main import app

    monkeypatch.setenv("AUTH_REQUEST_MAX_BYTES", "8")
    chunks = [
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.request", "body": b"56789", "more_body": False},
    ]
    sent = []

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/auth/reset-password",
        "raw_path": b"/api/auth/reset-password",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    assert next(message["status"] for message in sent if message["type"] == "http.response.start") == 413


def test_weak_password_policy_matches_all_credential_workflows_without_writes(client, auth_headers):
    user_id = _create_user(client, auth_headers, email="policy-target@example.com")
    token = _reset_link(user_id)
    target_headers = _login(client, "policy-target@example.com", ORIGINAL_PASSWORD)
    with SessionLocal() as db:
        before_audits = db.query(AuditLog).count()
        original_hash = db.get(User, user_id).password_hash

    responses = [
        client.post(
            "/api/users",
            headers=auth_headers,
            json={"name": "Weak create", "email": "weak-create@example.com", "password": WEAK_PASSWORD},
        ),
        client.patch(f"/api/users/{user_id}", headers=auth_headers, json={"password": WEAK_PASSWORD}),
        client.post(
            "/api/auth/change-password",
            headers=target_headers,
            json={
                "current_password": ORIGINAL_PASSWORD,
                "new_password": WEAK_PASSWORD,
                "confirm_new_password": WEAK_PASSWORD,
            },
        ),
        client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": WEAK_PASSWORD, "confirm_new_password": WEAK_PASSWORD},
        ),
    ]
    assert {response.status_code for response in responses} == {400}
    assert len({response.json()["detail"] for response in responses}) == 1

    with SessionLocal() as db:
        assert db.query(User).filter(User.email == "weak-create@example.com").first() is None
        assert db.get(User, user_id).password_hash == original_hash
        assert db.query(PasswordResetToken).filter_by(token_hash=password_reset_hash(token)).one().used_at is None
        assert db.query(AuditLog).count() == before_audits


@pytest.mark.parametrize("workflow", ["self", "admin"])
def test_non_reset_password_changes_invalidate_outstanding_reset_links(
    client, auth_headers, workflow,
):
    email = f"invalidate-{workflow}@example.com"
    user_id = _create_user(client, auth_headers, email=email)
    token = _reset_link(user_id)

    if workflow == "self":
        response = client.post(
            "/api/auth/change-password",
            headers=_login(client, email, ORIGINAL_PASSWORD),
            json={
                "current_password": ORIGINAL_PASSWORD,
                "new_password": REPLACEMENT_PASSWORD,
                "confirm_new_password": REPLACEMENT_PASSWORD,
            },
        )
        expected_action = "change_password"
    else:
        response = client.patch(
            f"/api/users/{user_id}",
            headers=auth_headers,
            json={"password": REPLACEMENT_PASSWORD},
        )
        expected_action = "update"
    assert response.status_code == 200, response.text

    stale_reset = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "StaleResetAttempt!2026", "confirm_new_password": "StaleResetAttempt!2026"},
    )
    assert stale_reset.status_code == 400
    assert _login(client, email, REPLACEMENT_PASSWORD)

    with SessionLocal() as db:
        reset_row = db.query(PasswordResetToken).filter_by(token_hash=password_reset_hash(token)).one()
        assert reset_row.used_at is not None
        audit = db.query(AuditLog).filter_by(
            action=expected_action,
            entity_type="User",
            entity_id=user_id,
        ).order_by(AuditLog.id.desc()).first()
        assert audit is not None
        serialized = json.dumps(audit.new_value_json or {})
        assert (audit.new_value_json or {}).get("credential_changed") is True
        assert (audit.new_value_json or {}).get("reset_links_invalidated") is True
        assert REPLACEMENT_PASSWORD not in serialized
        assert token not in serialized


def test_successful_reset_writes_metadata_only_audit(client, auth_headers):
    email = "reset-audit@example.com"
    user_id = _create_user(client, auth_headers, email=email)
    token = _reset_link(user_id)
    response = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": REPLACEMENT_PASSWORD, "confirm_new_password": REPLACEMENT_PASSWORD},
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert verify_password(REPLACEMENT_PASSWORD, user.password_hash)
        audit = db.query(AuditLog).filter_by(
            action="reset_password",
            entity_type="User",
            entity_id=user_id,
        ).one()
        serialized = json.dumps(audit.new_value_json or {})
        assert audit.new_value_json == {
            "credential_changed": True,
            "reset_links_invalidated": True,
        }
        assert token not in serialized
        assert REPLACEMENT_PASSWORD not in serialized


def test_admin_password_commit_failure_rolls_back_password_token_and_audit(
    client, auth_headers, monkeypatch,
):
    user_id = _create_user(client, auth_headers, email="admin-rollback@example.com")
    token = _reset_link(user_id)
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()

        def fail_commit():
            db.flush()
            raise RuntimeError("synthetic credential commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic credential commit failure"):
            admin.update_user(
                user_id,
                UserUpdate(password=REPLACEMENT_PASSWORD),
                db,
                actor,
            )
        db.rollback()

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert verify_password(ORIGINAL_PASSWORD, user.password_hash)
        assert not verify_password(REPLACEMENT_PASSWORD, user.password_hash)
        assert db.query(PasswordResetToken).filter_by(token_hash=password_reset_hash(token)).one().used_at is None
        assert db.query(AuditLog).filter_by(
            action="update",
            entity_type="User",
            entity_id=user_id,
        ).count() == 0


def test_seeded_configured_password_rotation_uses_same_credential_cutoff(
    client, monkeypatch,
):
    from app.db.seed import seed

    with SessionLocal() as db:
        user = db.query(User).filter_by(email="admin@example.com").one()
        user_id = user.id
        token = create_password_reset_token(db, user)
        db.commit()

    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", REPLACEMENT_PASSWORD)
    seed()

    stale_reset = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "StaleSeedReset!2026", "confirm_new_password": "StaleSeedReset!2026"},
    )
    assert stale_reset.status_code == 400
    assert _login(client, "admin@example.com", REPLACEMENT_PASSWORD)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user.tokens_valid_from is not None
        assert db.query(PasswordResetToken).filter_by(token_hash=password_reset_hash(token)).one().used_at is not None
        audit = db.query(AuditLog).filter_by(
            action="configured_password_sync",
            entity_type="User",
            entity_id=user_id,
        ).one()
        serialized = json.dumps(audit.new_value_json or {})
        assert audit.user_id is None
        assert audit.new_value_json == {
            "credential_changed": True,
            "reset_links_invalidated": True,
            "source": "INITIAL_ADMIN_PASSWORD",
        }
        assert token not in serialized
        assert REPLACEMENT_PASSWORD not in serialized

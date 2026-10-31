"""Frozen python-jose vectors preserve session policy and rollback wire format."""
import base64
import hashlib
import hmac
import importlib.metadata
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import jwt
import pytest

from app.core import security
from app.core.config import settings
from app.db.session import SessionLocal
from app.schemas import User

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "legacy_jose_tokens.json").read_text())
VALID = VECTORS["valid"]
CUTOFF = [case for case in VALID if case["algorithm"] == "HS256" and case["factory"] == "BST"]


@pytest.fixture
def compatibility_settings(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", VECTORS["key"])
    monkeypatch.setattr(settings, "JWT_ALGORITHM", "HS256")


@pytest.fixture
def compatibility_user(compatibility_settings):
    with SessionLocal() as db:
        db.add(User(id=424242, name="JWT compatibility fixture", email="jwt-compatibility@example.com",
                    password_hash="fixture-only", is_active=True, factory_code="MIL", extra_permissions=[]))
        db.commit()
    return 424242


def _case_id(case):
    return f'{case["algorithm"]}-{case["factory"]}-{type(case["iat"]).__name__}'


def _token(case, issuer):
    if issuer == "legacy":
        return case["token"]
    extra = {key: value for key, value in case["claims"].items() if key != "sub"}
    return security.create_access_token(424242, extra)


def _request(client, token, transport):
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"} if transport == "bearer" else {}
    if transport == "cookie":
        client.cookies.set(settings.AUTH_COOKIE_NAME, token)
    return client.get("/api/auth/me", headers=headers)


@pytest.mark.parametrize("case", VALID, ids=_case_id)
def test_legacy_tokens_preserve_claims_and_new_tokens_match_legacy_bytes(compatibility_settings, monkeypatch, case):
    monkeypatch.setattr(settings, "JWT_ALGORITHM", case["algorithm"])
    assert security.decode_token(case["token"]) == case["claims"]
    assert type(security.decode_token(case["token"])["iat"]) is type(case["iat"])
    assert _token(case, "new") == case["token"], "Rollback wire contract changed"


@pytest.mark.parametrize("issuer", ["legacy", "new"])
@pytest.mark.parametrize("transport", ["cookie", "bearer"])
@pytest.mark.parametrize("case", VALID, ids=_case_id)
def test_old_and_new_sessions_keep_factory_context(client, compatibility_user, monkeypatch, issuer, transport, case):
    monkeypatch.setattr(settings, "JWT_ALGORITHM", case["algorithm"])
    with SessionLocal() as db:
        db.get(User, compatibility_user).factory_code = case["factory"]
        db.commit()
    response = _request(client, _token(case, issuer), transport)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == compatibility_user
    assert response.json()["factory_code"] == case["factory"]


@pytest.mark.parametrize("issuer", ["legacy", "new"])
@pytest.mark.parametrize("transport", ["cookie", "bearer"])
@pytest.mark.parametrize("case", CUTOFF, ids=_case_id)
@pytest.mark.parametrize("cutoff", [1699999999.5, 1700000000, 1700000000.125, 1700000000.25, 1700000000.5])
def test_cutoff_comparison_remains_unchanged(client, compatibility_user, issuer, transport, case, cutoff):
    with SessionLocal() as db:
        user = db.get(User, compatibility_user)
        user.factory_code = "BST"
        user.tokens_valid_from = datetime.fromtimestamp(cutoff, timezone.utc)
        db.commit()
    response = _request(client, _token(case, issuer), transport)
    assert response.status_code == (200 if case["iat"] >= cutoff else 401), response.text


@pytest.fixture
def frozen_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(VECTORS["now"], timezone.utc)

    monkeypatch.setattr(security, "datetime", Clock)
    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)


@pytest.mark.parametrize("case", VECTORS["edges"], ids=lambda case: case["name"])
def test_decoder_matches_frozen_legacy_validation(compatibility_settings, frozen_clock, case):
    if case["accepted"]:
        assert security.decode_token(case["token"]) == case["claims"]
    else:
        with pytest.raises((ValueError, TypeError, OverflowError)):
            security.decode_token(case["token"])


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
@pytest.mark.parametrize("kind", ["expired", "bad-signature", "malformed", "wrong-algorithm", "bad-json", "nested-json"])
def test_invalid_tokens_remain_unauthorized(client, compatibility_user, transport, kind):
    token = next(case["token"] for case in VALID if case["algorithm"] == "HS256")
    if kind == "expired":
        token = security.create_access_token(compatibility_user, {"exp": 1})
    elif kind == "bad-signature":
        header, payload, signature = token.split(".")
        token = ".".join([header, payload, ("A" if signature[0] != "A" else "B") + signature[1:]])
    elif kind == "malformed":
        token = "not-a-jwt"
    elif kind == "wrong-algorithm":
        token = next(case["token"] for case in VALID if case["algorithm"] == "HS384")
    else:
        payload = b"{invalid" if kind == "bad-json" else b"[" * 1100 + b"0" + b"]" * 1100
        header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=")
        body = header + b"." + base64.urlsafe_b64encode(payload).rstrip(b"=")
        signature = hmac.new(VECTORS["key"].encode(), body, hashlib.sha256).digest()
        token = (body + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()
    assert _request(client, token, transport).status_code == 401


def test_issuance_keeps_precision_and_lifetime(compatibility_settings, frozen_clock):
    claims = security.decode_token(security.create_access_token(424242, {"factory_code": "ECO"}))
    assert claims == {"sub": "424242", "iat": VECTORS["now"],
                      "exp": int(VECTORS["now"] + settings.JWT_EXPIRES_MINUTES * 60), "factory_code": "ECO"}
    assert isinstance(claims["iat"], float) and isinstance(claims["exp"], int)


def test_resolved_runtime_excludes_jose_and_ecdsa():
    assert importlib.metadata.version("PyJWT") == "2.15.0"
    for distribution, module in [("python-jose", "jose"), ("ecdsa", "ecdsa")]:
        with pytest.raises(importlib.metadata.PackageNotFoundError):
            importlib.metadata.version(distribution)
        assert importlib.util.find_spec(module) is None

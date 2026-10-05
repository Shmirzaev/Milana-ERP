from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import IdempotencyRecord, User
from app.services.factory_scope import FACTORY_CODES, selected_factory_code

_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_IDENTITY = "idempotency_identity"


def bind_idempotency_identity(db: Session, user: User) -> None:
    """Bind the verified actor after authentication and factory authorization.

    Direct callers outside FastAPI must explicitly establish this context too;
    loaded users and Python function names are not authentication evidence.
    """
    if user.id is None or user.id <= 0:
        raise HTTPException(401, "An authenticated user is required for request replay")
    db.info[_IDENTITY] = (int(user.id), selected_factory_code(user))


def _identity(db: Session) -> tuple[int, str]:
    identity = db.info.get(_IDENTITY)
    if (not isinstance(identity, tuple) or len(identity) != 2
            or type(identity[0]) is not int or identity[0] <= 0
            or identity[1] not in FACTORY_CODES):
        raise HTTPException(401, "An authenticated user and factory are required for request replay")
    return identity


def _scoped_operation(scope: str, identity: tuple[int, str]) -> str:
    # Keep the supplied key and a readable operation prefix. The digest includes
    # the FULL explicit scope, so truncating its prefix never aliases operations.
    encoded = json.dumps(["fn06-v2", scope, *identity], separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"{scope[:60]}:v2:{digest}"  # at most 128 characters


def _legacy_factory(scope: str, response: dict) -> str | None:
    # Only server-persisted evidence establishes a historical factory. Do not
    # infer it from today's user assignment or from an incoming request payload.
    if scope.startswith("purchasing.receive:"):
        factory = scope.split(":")[1]
        if factory in FACTORY_CODES:
            return factory
    factory = response.get("factory_code")
    return factory if factory in FACTORY_CODES else None


def normalize_idempotency_key(raw_key: str | None) -> str | None:
    key = str(raw_key or "").strip()
    if not key:
        return None
    if not _KEY_RE.fullmatch(key):
        raise HTTPException(400, "Idempotency-Key must be 1-128 characters using letters, numbers, '.', '_', ':', or '-'")
    return key


def request_fingerprint(payload: Any) -> str:
    encoded = json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def replay_idempotent_response(
    db: Session,
    *,
    scope: str,
    key: str | None,
    payload: Any,
) -> dict | None:
    normalized_key = normalize_idempotency_key(key)
    if not normalized_key:
        return None

    identity = _identity(db)
    scoped_operation = _scoped_operation(scope, identity)
    if db.get_bind().dialect.name == "postgresql":
        # Acquire before the replay read and business writes, and retain through
        # commit/rollback. Other users/factories have independent lock identities.
        encoded = json.dumps(["milana-idempotency-v2", scoped_operation, normalized_key], separators=(",", ":"))
        lock_id = int.from_bytes(hashlib.sha256(encoded.encode()).digest()[:8], signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})

    fingerprint = request_fingerprint(payload)
    row = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.scope == scoped_operation, IdempotencyRecord.key == normalized_key)
        .populate_existing()
        .first()
    )
    if not row:
        legacy = (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.scope == scope, IdempotencyRecord.key == normalized_key)
            .populate_existing()
            .first()
        )
        if not legacy:
            return None
        if legacy.user_id is None:
            raise HTTPException(409, "Legacy retry ownership is unknown; review the original operation before retrying")
        if legacy.user_id != identity[0]:
            return None  # A known different owner cannot occupy this namespace.
        factory = _legacy_factory(scope, legacy.response_json)
        if factory is None:
            raise HTTPException(409, "Legacy retry factory is unknown; review the original operation before retrying")
        if factory != identity[1]:
            return None
        row = legacy
    if row.user_id != identity[0]:
        raise HTTPException(409, "Saved retry ownership is inconsistent; review the original operation before retrying")
    if row.request_hash != fingerprint:
        raise HTTPException(409, "Idempotency-Key was already used with a different request payload")
    return row.response_json


def store_idempotent_response(
    db: Session,
    *,
    scope: str,
    key: str | None,
    payload: Any,
    response: Any,
    user: User | None,
    status_code: int = 200,
) -> None:
    normalized_key = normalize_idempotency_key(key)
    if not normalized_key:
        return

    identity = _identity(db)
    if user is None or user.id != identity[0] or selected_factory_code(user) != identity[1]:
        raise HTTPException(401, "Saved retry identity must match the authenticated user and factory")
    fingerprint = request_fingerprint(payload)
    row = IdempotencyRecord(
        scope=_scoped_operation(scope, identity),
        key=normalized_key,
        request_hash=fingerprint,
        response_json=jsonable_encoder(response),
        status_code=status_code,
        user_id=user.id if user else None,
    )
    db.add(row)
    db.flush()

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.integration_auth import OneCIntegrationIdentity
from app.models import IdempotencyRecord
from app.services.idempotency import normalize_idempotency_key, request_fingerprint


def _scope(identity: OneCIntegrationIdentity) -> str:
    return f"integrations.1c:{identity.client_id}"


def replay_integration_response(
    db: Session,
    *,
    identity: OneCIntegrationIdentity,
    key: str | None,
    payload: Any,
    required: bool,
) -> dict | None:
    normalized_key = normalize_idempotency_key(key)
    if normalized_key is None:
        if required:
            raise HTTPException(400, "Idempotency-Key is required for 1C synchronization")
        return None

    scope = _scope(identity)
    if db.get_bind().dialect.name == "postgresql":
        lock_payload = json.dumps(["milana-integration-idempotency", scope, normalized_key], separators=(",", ":"))
        lock_id = int.from_bytes(hashlib.sha256(lock_payload.encode()).digest()[:8], signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})

    fingerprint = request_fingerprint(payload)
    row = (
        db.query(
            IdempotencyRecord.user_id,
            IdempotencyRecord.request_hash,
            IdempotencyRecord.response_json,
        )
        .filter(IdempotencyRecord.scope == scope, IdempotencyRecord.key == normalized_key)
        .populate_existing()
        .first()
    )
    if row is None:
        return None
    if row.user_id is not None:
        raise HTTPException(409, "Idempotency-Key belongs to a different actor")
    if row.request_hash != fingerprint:
        raise HTTPException(409, "Idempotency-Key was already used with a different request payload")
    return row.response_json


def store_integration_response(
    db: Session,
    *,
    identity: OneCIntegrationIdentity,
    key: str | None,
    payload: Any,
    response: Any,
) -> None:
    normalized_key = normalize_idempotency_key(key)
    if normalized_key is None:
        return
    db.add(IdempotencyRecord(
        scope=_scope(identity),
        key=normalized_key,
        request_hash=request_fingerprint(payload),
        response_json=jsonable_encoder(response),
        status_code=200,
        user_id=None,
    ))
    db.flush()

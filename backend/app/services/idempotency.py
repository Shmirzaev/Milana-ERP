from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models import IdempotencyRecord, User

_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


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

    fingerprint = request_fingerprint(payload)
    row = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.scope == scope, IdempotencyRecord.key == normalized_key)
        .first()
    )
    if not row:
        return None
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

    fingerprint = request_fingerprint(payload)
    row = IdempotencyRecord(
        scope=scope,
        key=normalized_key,
        request_hash=fingerprint,
        response_json=jsonable_encoder(response),
        status_code=status_code,
        user_id=user.id if user else None,
    )
    db.add(row)
    db.flush()

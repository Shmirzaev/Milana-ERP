"""Schema-owned persistence for the shared `idempotency_records` row.

The mapped `IdempotencyRecord` class stays in `app.schemas.core`; it is
imported, never redefined, and the mapping metadata is untouched. This module
owns only the mapped insert.

Identity binding, key normalization, request fingerprints, the PostgreSQL
advisory lock and the replay/lookup policy stay in the business service
`app.models.idempotency_service`.

The helper uses the Session it is given. It never commits, never begins or
nests a transaction, never swallows an error, and never imports a service or a
route. The outer business operation owns the transaction.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.schemas.core import IdempotencyRecord


def insert_idempotency_record(
    db: Session,
    *,
    scope: str,
    key: str,
    request_hash: str,
    response_json: Any,
    status_code: int,
    user_id: int | None,
) -> IdempotencyRecord:
    """Construct, stage and flush one `idempotency_records` row.

    The caller has already normalized the key, computed the request
    fingerprint and bound the operation scope to the authenticated identity.
    """
    row = IdempotencyRecord(
        scope=scope,
        key=key,
        request_hash=request_hash,
        response_json=response_json,
        status_code=status_code,
        user_id=user_id,
    )
    db.add(row)
    db.flush()
    return row

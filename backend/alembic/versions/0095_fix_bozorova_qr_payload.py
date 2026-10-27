"""Correct uppercase Bozorova family names inside issued QR payloads.

Revision ID: 0095_fix_bozorova_qr_payload
Revises: 0094_fix_bozorova_name
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op


revision = "0095_fix_bozorova_qr_payload"
down_revision = "0094_fix_bozorova_name"
branch_labels = None
depends_on = None


OLD_VALUE = "BOZORVA NARGIZA"
NEW_VALUE = "BOZOROVA NARGIZA"


def _entry_hash(*, previous: str | None, old_value: dict, new_value: dict) -> str:
    payload = {
        "prev_hash": previous,
        "user_id": None,
        "action": "correct_qr_payload_name",
        "entity_type": "PayrollQrLabel",
        "entity_id": None,
        "old_value": old_value,
        "new_value": new_value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE audit_logs IN SHARE ROW EXCLUSIVE MODE"))
    count = int(
        connection.execute(
            sa.text("SELECT COUNT(*) FROM payroll_qr_labels WHERE payload LIKE '%' || :old_value || '%'"),
            {"old_value": OLD_VALUE},
        ).scalar_one()
    )
    if not count:
        return

    connection.execute(
        sa.text(
            "UPDATE payroll_qr_labels SET payload = replace(payload, :old_value, :new_value), updated_at = NOW() "
            "WHERE payload LIKE '%' || :old_value || '%'"
        ),
        {"old_value": OLD_VALUE, "new_value": NEW_VALUE},
    )
    remaining = int(
        connection.execute(
            sa.text("SELECT COUNT(*) FROM payroll_qr_labels WHERE payload LIKE '%' || :old_value || '%'"),
            {"old_value": OLD_VALUE},
        ).scalar_one()
    )
    if remaining:
        raise RuntimeError(f"Uppercase Bozorova QR correction left {remaining} payloads unchanged")

    previous_hash = connection.execute(
        sa.text("SELECT entry_hash FROM audit_logs WHERE entry_hash IS NOT NULL ORDER BY id DESC LIMIT 1")
    ).scalar_one_or_none()
    old_value = {"sewing_line_name": OLD_VALUE}
    new_value = {"sewing_line_name": NEW_VALUE, "corrected_payloads": count}
    connection.execute(
        sa.text(
            "INSERT INTO audit_logs "
            "(user_id, action, entity_type, entity_id, old_value_json, new_value_json, prev_hash, entry_hash) "
            "VALUES (NULL, 'correct_qr_payload_name', 'PayrollQrLabel', NULL, CAST(:old_value AS json), CAST(:new_value AS json), :prev_hash, :entry_hash)"
        ),
        {
            "old_value": json.dumps(old_value, separators=(",", ":")),
            "new_value": json.dumps(new_value, separators=(",", ":")),
            "prev_hash": previous_hash,
            "entry_hash": _entry_hash(previous=previous_hash, old_value=old_value, new_value=new_value),
        },
    )


def downgrade() -> None:
    # Do not restore a known misspelling into already-issued QR payloads.
    pass

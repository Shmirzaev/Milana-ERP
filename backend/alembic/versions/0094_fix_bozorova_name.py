"""Correct Bozorova Nargiza's sewing-line name in operational data.

Revision ID: 0094_fix_bozorova_name
Revises: 0093_payroll_reversal
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op


revision = "0094_fix_bozorova_name"
down_revision = "0093_payroll_reversal"
branch_labels = None
depends_on = None


OLD_NAME = "Bozorva Nargiza"
NEW_NAME = "Bozorova Nargiza"


def _scalar_count(connection: sa.Connection, sql: str) -> int:
    return int(connection.execute(sa.text(sql), {"old_name": OLD_NAME}).scalar_one())


def _entry_hash(*, previous: str | None, old_value: dict, new_value: dict) -> str:
    payload = {
        "prev_hash": previous,
        "user_id": None,
        "action": "correct_name",
        "entity_type": "SewingLine",
        "entity_id": None,
        "old_value": old_value,
        "new_value": new_value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def upgrade() -> None:
    connection = op.get_bind()

    # Serialize this correction with application audit writes so the new entry
    # links to the latest hash and operational snapshots change atomically.
    connection.execute(sa.text("LOCK TABLE audit_logs IN SHARE ROW EXCLUSIVE MODE"))

    counts = {
        "sewing_flows": _scalar_count(
            connection,
            "SELECT COUNT(*) FROM sewing_flows WHERE name = :old_name",
        ),
        "sewing_daily_reports": _scalar_count(
            connection,
            "SELECT COUNT(*) FROM sewing_daily_reports WHERE line_name = :old_name",
        ),
        "payroll_qr_labels_name": _scalar_count(
            connection,
            "SELECT COUNT(*) FROM payroll_qr_labels WHERE sewing_line_name = :old_name",
        ),
        "payroll_qr_labels_payload": _scalar_count(
            connection,
            "SELECT COUNT(*) FROM payroll_qr_labels WHERE payload ILIKE '%' || :old_name || '%'",
        ),
        "payroll_records": _scalar_count(
            connection,
            "SELECT COUNT(*) FROM payroll_records WHERE CAST(raw_work_json AS text) LIKE '%' || :old_name || '%'",
        ),
        "idempotency_records": _scalar_count(
            connection,
            "SELECT COUNT(*) FROM idempotency_records WHERE CAST(response_json AS text) LIKE '%' || :old_name || '%'",
        ),
    }

    connection.execute(
        sa.text("UPDATE sewing_flows SET name = :new_name, updated_at = NOW() WHERE name = :old_name"),
        {"old_name": OLD_NAME, "new_name": NEW_NAME},
    )
    connection.execute(
        sa.text("UPDATE sewing_daily_reports SET line_name = :new_name, updated_at = NOW() WHERE line_name = :old_name"),
        {"old_name": OLD_NAME, "new_name": NEW_NAME},
    )
    connection.execute(
        sa.text("UPDATE payroll_qr_labels SET sewing_line_name = :new_name, updated_at = NOW() WHERE sewing_line_name = :old_name"),
        {"old_name": OLD_NAME, "new_name": NEW_NAME},
    )
    connection.execute(
        sa.text(
            "UPDATE payroll_qr_labels "
            "SET payload = replace(replace(payload, :old_name, :new_name), upper(:old_name), upper(:new_name)), updated_at = NOW() "
            "WHERE payload ILIKE '%' || :old_name || '%'"
        ),
        {"old_name": OLD_NAME, "new_name": NEW_NAME},
    )
    connection.execute(
        sa.text(
            "UPDATE payroll_records SET raw_work_json = CAST(replace(CAST(raw_work_json AS text), :old_name, :new_name) AS json), "
            "updated_at = NOW() WHERE CAST(raw_work_json AS text) LIKE '%' || :old_name || '%'"
        ),
        {"old_name": OLD_NAME, "new_name": NEW_NAME},
    )
    connection.execute(
        sa.text(
            "UPDATE idempotency_records SET response_json = CAST(replace(CAST(response_json AS text), :old_name, :new_name) AS json) "
            "WHERE CAST(response_json AS text) LIKE '%' || :old_name || '%'"
        ),
        {"old_name": OLD_NAME, "new_name": NEW_NAME},
    )

    remaining = sum(
        (
            _scalar_count(connection, "SELECT COUNT(*) FROM sewing_flows WHERE name = :old_name"),
            _scalar_count(connection, "SELECT COUNT(*) FROM sewing_daily_reports WHERE line_name = :old_name"),
            _scalar_count(connection, "SELECT COUNT(*) FROM payroll_qr_labels WHERE sewing_line_name = :old_name"),
            _scalar_count(connection, "SELECT COUNT(*) FROM payroll_qr_labels WHERE payload ILIKE '%' || :old_name || '%'"),
            _scalar_count(connection, "SELECT COUNT(*) FROM payroll_records WHERE CAST(raw_work_json AS text) LIKE '%' || :old_name || '%'"),
            _scalar_count(connection, "SELECT COUNT(*) FROM idempotency_records WHERE CAST(response_json AS text) LIKE '%' || :old_name || '%'"),
        )
    )
    if remaining:
        raise RuntimeError(f"Bozorova name correction left {remaining} operational values unchanged")

    if sum(counts.values()):
        previous_hash = connection.execute(
            sa.text("SELECT entry_hash FROM audit_logs WHERE entry_hash IS NOT NULL ORDER BY id DESC LIMIT 1")
        ).scalar_one_or_none()
        old_value = {"name": OLD_NAME}
        new_value = {"name": NEW_NAME, "corrected_rows": counts}
        connection.execute(
            sa.text(
                "INSERT INTO audit_logs "
                "(user_id, action, entity_type, entity_id, old_value_json, new_value_json, prev_hash, entry_hash) "
                "VALUES (NULL, 'correct_name', 'SewingLine', NULL, CAST(:old_value AS json), CAST(:new_value AS json), :prev_hash, :entry_hash)"
            ),
            {
                "old_value": json.dumps(old_value, separators=(",", ":")),
                "new_value": json.dumps(new_value, separators=(",", ":")),
                "prev_hash": previous_hash,
                "entry_hash": _entry_hash(previous=previous_hash, old_value=old_value, new_value=new_value),
            },
        )


def downgrade() -> None:
    # A spelling correction is intentionally irreversible: a rollback must not
    # reintroduce the incorrect family name into payroll or issued QR labels.
    pass

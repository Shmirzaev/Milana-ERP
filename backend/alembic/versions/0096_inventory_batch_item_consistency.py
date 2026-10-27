"""Keep batch-linked inventory records on the batch's current material.

Revision ID: 0096_batch_item_consistency
Revises: 0095_fix_bozorova_qr_payload
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op


revision = "0096_batch_item_consistency"
down_revision = "0095_fix_bozorova_qr_payload"
branch_labels = None
depends_on = None


LINKED_TABLES = {
    "material_reservations": "stock_batch_id",
    "model_bom": "stock_batch_id",
    "waste_records": "batch_id",
    "stock_movements": "batch_id",
}


def _entry_hash(*, previous: str | None, old_value: dict, new_value: dict) -> str:
    payload = {
        "prev_hash": previous,
        "user_id": None,
        "action": "repair_batch_item_links",
        "entity_type": "StockBatchItemLink",
        "entity_id": None,
        "old_value": old_value,
        "new_value": new_value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mismatch_count(connection: sa.Connection, table: str, batch_column: str) -> int:
    return int(
        connection.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {table} linked "
                f"JOIN stock_batches batch ON batch.id = linked.{batch_column} "
                "WHERE linked.item_id <> batch.item_id"
            )
        ).scalar_one()
    )


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE audit_logs, material_reservations, model_bom, waste_records, "
            "stock_movements, stock_batches IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    counts = {
        table: _mismatch_count(connection, table, batch_column)
        for table, batch_column in LINKED_TABLES.items()
    }
    if not sum(counts.values()):
        return

    for table, batch_column in LINKED_TABLES.items():
        updated_at = ", updated_at = NOW()" if table != "stock_movements" else ""
        connection.execute(
            sa.text(
                f"UPDATE {table} AS linked SET item_id = batch.item_id{updated_at} "
                f"FROM stock_batches AS batch WHERE batch.id = linked.{batch_column} "
                "AND linked.item_id <> batch.item_id"
            )
        )

    remaining = {
        table: _mismatch_count(connection, table, batch_column)
        for table, batch_column in LINKED_TABLES.items()
    }
    if sum(remaining.values()):
        raise RuntimeError(f"Batch item consistency repair left mismatches: {remaining}")

    previous_hash = connection.execute(
        sa.text("SELECT entry_hash FROM audit_logs WHERE entry_hash IS NOT NULL ORDER BY id DESC LIMIT 1")
    ).scalar_one_or_none()
    old_value = {"mismatched_rows": counts}
    new_value = {"corrected_rows": counts, "remaining_mismatches": remaining}
    connection.execute(
        sa.text(
            "INSERT INTO audit_logs "
            "(user_id, action, entity_type, entity_id, old_value_json, new_value_json, prev_hash, entry_hash) "
            "VALUES (NULL, 'repair_batch_item_links', 'StockBatchItemLink', NULL, "
            "CAST(:old_value AS json), CAST(:new_value AS json), :prev_hash, :entry_hash)"
        ),
        {
            "old_value": json.dumps(old_value, separators=(",", ":")),
            "new_value": json.dumps(new_value, separators=(",", ":")),
            "prev_hash": previous_hash,
            "entry_hash": _entry_hash(previous=previous_hash, old_value=old_value, new_value=new_value),
        },
    )


def downgrade() -> None:
    # Restoring mismatched item links would reintroduce negative inventory.
    pass

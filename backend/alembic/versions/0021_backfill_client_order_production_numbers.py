"""backfill client production numbers from sales orders

Revision ID: 0021_order_number_backfill
Revises: 0020_model_image_file_data
Create Date: 2026-06-17
"""
from __future__ import annotations

from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "0021_order_number_backfill"
down_revision = "0020_model_image_file_data"
branch_labels = None
depends_on = None


def _fit(value: str, suffix: str = "") -> str:
    max_len = 64
    if len(value) + len(suffix) <= max_len:
        return f"{value}{suffix}"
    return f"{value[: max_len - len(suffix)]}{suffix}"


def _unique_target(base: str, row_id: int, used: set[str]) -> str:
    candidate = _fit(base)
    if candidate not in used:
        return candidate

    suffix = f"-{row_id}"
    candidate = _fit(base, suffix)
    if candidate not in used:
        return candidate

    counter = 2
    while True:
        suffix = f"-{row_id}-{counter}"
        candidate = _fit(base, suffix)
        if candidate not in used:
            return candidate
        counter += 1


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "production_orders" not in tables or "sales_orders" not in tables:
        return

    rows = bind.execute(
        sa.text(
            """
            SELECT po.id, po.production_no, po.sales_order_id, so.order_no
            FROM production_orders po
            JOIN sales_orders so ON so.id = po.sales_order_id
            WHERE po.sales_order_id IS NOT NULL
            ORDER BY po.sales_order_id ASC, po.id ASC
            """
        )
    ).mappings().all()
    if not rows:
        return

    used = {
        str(value)
        for (value,) in bind.execute(sa.text("SELECT production_no FROM production_orders")).all()
        if value is not None
    }
    for row in rows:
        current = row["production_no"]
        if current is not None:
            used.discard(str(current))

    by_sales_order: dict[int, list] = defaultdict(list)
    for row in rows:
        by_sales_order[int(row["sales_order_id"])].append(row)

    updates: list[tuple[int, str]] = []
    for group in by_sales_order.values():
        for index, row in enumerate(group, start=1):
            base = str(row["order_no"])
            target_base = base if index == 1 else f"{base}-{index}"
            target = _unique_target(target_base, int(row["id"]), used)
            used.add(target)
            if str(row["production_no"]) != target:
                updates.append((int(row["id"]), target))

    if not updates:
        return

    tmp_prefix = "__order_unify_tmp_"
    for row_id, _target in updates:
        bind.execute(
            sa.text("UPDATE production_orders SET production_no = :tmp WHERE id = :id"),
            {"id": row_id, "tmp": _fit(f"{tmp_prefix}{row_id}")},
        )

    for row_id, target in updates:
        bind.execute(
            sa.text("UPDATE production_orders SET production_no = :target WHERE id = :id"),
            {"id": row_id, "target": target},
        )


def downgrade():
    # Historical PO-* values cannot be reconstructed safely after a data backfill.
    pass

"""use simple sequential branded order numbers

Revision ID: 0048_simple_branded_numbers
Revises: 0047_branded_planning_orders
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "0048_simple_branded_numbers"
down_revision = "0047_branded_planning_orders"
branch_labels = None
depends_on = None


def _rows(bind):
    return bind.execute(
        sa.text(
            """
            SELECT id, created_at
            FROM branded_planning_orders
            ORDER BY CASE WHEN created_at IS NULL THEN 0 ELSE 1 END, created_at, id
            """
        )
    ).mappings().all()


def upgrade():
    bind = op.get_bind()
    if "branded_planning_orders" not in set(sa.inspect(bind).get_table_names()):
        return

    rows = _rows(bind)
    for row in rows:
        bind.execute(
            sa.text("UPDATE branded_planning_orders SET order_no = :temporary WHERE id = :id"),
            {"temporary": f"__order_{row['id']}__", "id": row["id"]},
        )
    for sequence, row in enumerate(rows, start=1):
        bind.execute(
            sa.text("UPDATE branded_planning_orders SET order_no = :order_no WHERE id = :id"),
            {"order_no": f"{sequence:04d}", "id": row["id"]},
        )


def downgrade():
    bind = op.get_bind()
    if "branded_planning_orders" not in set(sa.inspect(bind).get_table_names()):
        return

    rows = _rows(bind)
    for row in rows:
        bind.execute(
            sa.text("UPDATE branded_planning_orders SET order_no = :temporary WHERE id = :id"),
            {"temporary": f"__order_{row['id']}__", "id": row["id"]},
        )

    counters: dict[int, int] = {}
    for row in rows:
        created_at = row["created_at"] or datetime.now(timezone.utc)
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        year = int(created_at.year)
        counters[year] = counters.get(year, 0) + 1
        bind.execute(
            sa.text("UPDATE branded_planning_orders SET order_no = :order_no WHERE id = :id"),
            {"order_no": f"BPO-{year}-{counters[year]:04d}", "id": row["id"]},
        )

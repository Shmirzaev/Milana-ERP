"""group branded production under numbered planning orders

Revision ID: 0047_branded_planning_orders
Revises: 0046_add_eco_cotton_cutting
Create Date: 2026-07-15
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "0047_branded_planning_orders"
down_revision = "0046_add_eco_cotton_cutting"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "branded_planning_orders" not in set(inspector.get_table_names()):
        op.create_table(
            "branded_planning_orders",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("order_no", sa.String(length=64), nullable=False),
            sa.Column("ordered_for_type", sa.String(length=32), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=True),
            sa.Column("ordered_for_name", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=32), server_default="open", nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint(
                "ordered_for_type IN ('customer', 'milana', 'eco_cotton', 'besttex')",
                name="ck_branded_planning_orders_ordered_for_type",
            ),
            sa.CheckConstraint(
                "status IN ('open', 'closed', 'cancelled')",
                name="ck_branded_planning_orders_status",
            ),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("order_no"),
        )
        op.create_index("ix_branded_planning_orders_order_no", "branded_planning_orders", ["order_no"], unique=True)
        op.create_index("ix_branded_planning_orders_customer_id", "branded_planning_orders", ["customer_id"])

    inspector = sa.inspect(bind)
    production_columns = {column.get("name") for column in inspector.get_columns("production_orders")}
    if "planning_order_id" not in production_columns:
        op.add_column(
            "production_orders",
            sa.Column("planning_order_id", sa.Integer(), sa.ForeignKey("branded_planning_orders.id"), nullable=True),
        )
    production_indexes = {index.get("name") for index in sa.inspect(bind).get_indexes("production_orders")}
    if "ix_production_orders_planning_order_id" not in production_indexes:
        op.create_index("ix_production_orders_planning_order_id", "production_orders", ["planning_order_id"])

    existing_numbers = [
        str(row[0])
        for row in bind.execute(sa.text("SELECT order_no FROM branded_planning_orders")).all()
        if row[0]
    ]
    counters: dict[int, int] = {}
    for order_no in existing_numbers:
        parts = order_no.rsplit("-", 2)
        if len(parts) != 3 or parts[0] != "BPO":
            continue
        try:
            year, sequence = int(parts[1]), int(parts[2])
        except (TypeError, ValueError):
            continue
        counters[year] = max(counters.get(year, 0), sequence)

    legacy_rows = bind.execute(
        sa.text(
            """
            SELECT id, created_at, created_by
            FROM production_orders
            WHERE production_type = 'branded_stock' AND planning_order_id IS NULL
            ORDER BY created_at, id
            """
        )
    ).mappings().all()
    for row in legacy_rows:
        created_at = row["created_at"] or datetime.now(timezone.utc)
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        year = int(created_at.year)
        counters[year] = counters.get(year, 0) + 1
        order_no = f"BPO-{year}-{counters[year]:04d}"
        planning_order_id = bind.execute(
            sa.text(
                """
                INSERT INTO branded_planning_orders
                    (order_no, ordered_for_type, ordered_for_name, status, notes, created_by, created_at, updated_at)
                VALUES
                    (:order_no, 'milana', 'Milana', 'open', 'Created for legacy branded production',
                     :created_by, :created_at, :created_at)
                RETURNING id
                """
            ),
            {"order_no": order_no, "created_by": row["created_by"], "created_at": created_at},
        ).scalar_one()
        bind.execute(
            sa.text("UPDATE production_orders SET planning_order_id = :planning_order_id WHERE id = :production_order_id"),
            {"planning_order_id": planning_order_id, "production_order_id": row["id"]},
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "production_orders" in set(inspector.get_table_names()):
        indexes = {index.get("name") for index in inspector.get_indexes("production_orders")}
        if "ix_production_orders_planning_order_id" in indexes:
            op.drop_index("ix_production_orders_planning_order_id", table_name="production_orders")
        columns = {column.get("name") for column in inspector.get_columns("production_orders")}
        if "planning_order_id" in columns:
            op.drop_column("production_orders", "planning_order_id")
    if "branded_planning_orders" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("branded_planning_orders")

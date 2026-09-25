"""Capture unit cost when a stock batch is consumed."""

from alembic import op
import sqlalchemy as sa


revision = "0133_movement_cost_snapshot"
down_revision = "0132_department_soft_delete"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("stock_movements") as batch:
        batch.add_column(sa.Column("unit_cost_at_movement", sa.Numeric(12, 4), nullable=True))
        batch.create_check_constraint(
            "ck_stock_movements_snapshot_cost_nonnegative",
            "unit_cost_at_movement IS NULL OR unit_cost_at_movement >= 0",
        )


def downgrade():
    with op.batch_alter_table("stock_movements") as batch:
        batch.drop_constraint("ck_stock_movements_snapshot_cost_nonnegative", type_="check")
        batch.drop_column("unit_cost_at_movement")

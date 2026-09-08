"""Saved, non-adjusting finished-goods physical counts."""

from alembic import op
import sqlalchemy as sa

revision = "0114_warehouse_stocktake"
down_revision = "0113_variant_selling_price"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "warehouse_stocktakes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_key", sa.String(36), nullable=False, unique=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "warehouse_stocktake_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stocktake_id", sa.Integer(), sa.ForeignKey("warehouse_stocktakes.id"), nullable=False),
        sa.Column("identity", sa.String(80), nullable=False),
        sa.Column("package_id", sa.Integer()),
        sa.Column("expected", sa.Boolean(), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("final_snapshot", sa.JSON()),
        sa.Column("scan_code", sa.String(512)),
        sa.Column("scanned_at", sa.DateTime(timezone=True)),
        sa.Column("scanned_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("stocktake_id", "identity", name="uq_stocktake_identity"),
    )
    op.create_index("ix_warehouse_stocktake_rows_stocktake_id", "warehouse_stocktake_rows", ["stocktake_id"])
    op.create_index("ix_warehouse_stocktake_rows_package_id", "warehouse_stocktake_rows", ["package_id"])


def downgrade():
    op.drop_table("warehouse_stocktake_rows")
    op.drop_table("warehouse_stocktakes")

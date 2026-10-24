"""Customer-owned whole-pack holds for future shipments."""
from alembic import op
import sqlalchemy as sa

revision = "0139_warehouse_pack_reservations"
down_revision = "0138_ismail_schema_contract"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "warehouse_pack_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("package_id", sa.Integer(), sa.ForeignKey("packages.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reserved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.UniqueConstraint("package_id", name="uq_warehouse_pack_reservations_package"),
        sa.CheckConstraint("quantity > 0", name="ck_warehouse_pack_reservations_quantity"),
    )
    op.create_index("ix_warehouse_pack_reservations_customer_id", "warehouse_pack_reservations", ["customer_id"])


def downgrade():
    # Never discard active claims: restoring stock must be an explicit audited action.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM warehouse_pack_reservations")).scalar():
        raise RuntimeError("Release active warehouse pack reservations before downgrading")
    op.drop_table("warehouse_pack_reservations")

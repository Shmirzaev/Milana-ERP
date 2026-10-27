"""Immutable evidence for warehouse count adjustments and extra physical receipts."""

from alembic import op
import sqlalchemy as sa

revision = "0117_package_quantity_evidence"
down_revision = "0116_pack_sales_dispatch"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "package_quantity_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("package_id", sa.Integer(), sa.ForeignKey("packages.id"), nullable=False),
        sa.Column("shipment_id", sa.Integer(), sa.ForeignKey("shipments.id"), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("extra_receipt_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("extra_receipt_quantity >= 0", name="ck_package_quantity_extra_receipt_nonnegative"),
    )
    op.create_index("ix_package_quantity_adjustments_package_id", "package_quantity_adjustments", ["package_id"])
    op.create_index("ix_package_quantity_adjustments_shipment_id", "package_quantity_adjustments", ["shipment_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE TRIGGER immutable_package_quantity_adjustments
            BEFORE UPDATE OR DELETE ON package_quantity_adjustments
            FOR EACH ROW EXECUTE FUNCTION reject_package_evidence_change()""")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM package_quantity_adjustments")).scalar():
        raise RuntimeError("Cannot remove recorded physical quantity adjustment evidence")
    op.drop_table("package_quantity_adjustments")

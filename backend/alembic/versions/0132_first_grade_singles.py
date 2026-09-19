"""Classify individual First Grade stock and retain deleted shipment evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0132_first_grade_singles"
down_revision = "0131_sewing_corrections"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("packages", sa.Column("stock_kind", sa.String(16), nullable=False, server_default="standard"))
    op.create_index("ix_packages_stock_kind", "packages", ["stock_kind"])
    op.create_check_constraint("ck_packages_stock_kind", "packages", "stock_kind IN ('standard', 'first_grade')")
    op.create_check_constraint("ck_packages_single_quantity", "packages", "stock_kind != 'first_grade' OR (total_quantity <= 1 AND capacity = 1)")
    op.add_column("shipments", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    # Refuse a downgrade that would silently mix singles back into pack stock.
    if op.get_bind().execute(sa.text("SELECT 1 FROM packages WHERE stock_kind = 'first_grade' LIMIT 1")).first():
        raise RuntimeError("First Grade inventory must be reconciled before schema downgrade")
    op.drop_column("shipments", "deleted_at")
    op.drop_constraint("ck_packages_single_quantity", "packages", type_="check")
    op.drop_constraint("ck_packages_stock_kind", "packages", type_="check")
    op.drop_index("ix_packages_stock_kind", "packages")
    op.drop_column("packages", "stock_kind")

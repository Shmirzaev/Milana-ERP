"""Preserve complete ECO receiving details without changing existing balances."""
from alembic import op
import sqlalchemy as sa

revision = "0154_eco_receipt_details"
down_revision = ("0151_eco_accessory_approval", "0150_package_customer_release")
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("eco_material_batches", sa.Column("receipt_details", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("factory_fabric_transfer_lines", sa.Column("receipt_details", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    db = op.get_bind()
    for table in ("eco_material_batches", "factory_fabric_transfer_lines"):
        rows = db.execute(sa.text(f"SELECT receipt_details FROM {table}")).scalars()
        if any(value not in (None, "{}", {}) for value in rows):
            raise RuntimeError("ECO receipt details exist; export and reconcile them before downgrade")
    op.drop_column("factory_fabric_transfer_lines", "receipt_details")
    op.drop_column("eco_material_batches", "receipt_details")

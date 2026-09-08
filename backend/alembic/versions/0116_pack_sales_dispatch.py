"""Persist requested physical packs and the reviewed shipment invoice snapshot."""

from alembic import op
import sqlalchemy as sa

revision = "0116_pack_sales_dispatch"
down_revision = "0115_package_print_runs"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sales_order_items") as batch:
        batch.add_column(sa.Column("requested_pack_count", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "ck_sales_order_items_requested_packs_positive",
            "requested_pack_count IS NULL OR requested_pack_count > 0",
        )
    op.add_column("shipments", sa.Column("dispatch_snapshot", sa.JSON(), nullable=True))


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT count(*) FROM shipments WHERE dispatch_snapshot IS NOT NULL")).scalar():
        raise RuntimeError("Cannot remove recorded shipment invoice snapshots")
    if connection.execute(sa.text("SELECT count(*) FROM sales_order_items WHERE requested_pack_count IS NOT NULL")).scalar():
        raise RuntimeError("Cannot remove requested physical pack counts")
    op.drop_column("shipments", "dispatch_snapshot")
    with op.batch_alter_table("sales_order_items") as batch:
        batch.drop_constraint("ck_sales_order_items_requested_packs_positive", type_="check")
        batch.drop_column("requested_pack_count")

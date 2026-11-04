"""Separate Eco material balances and two-sided Milana fabric transfer ledger."""
from alembic import op
import sqlalchemy as sa

revision = "0150_eco_inventory_transfers"
down_revision = "0149_besttex_cutting_access"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("eco_material_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("batch_no", sa.String(64), nullable=False),
        sa.Column("color", sa.String(64)), sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("reserved_quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("source_stock_batch_id", sa.Integer(), sa.ForeignKey("stock_batches.id")),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint("kind IN ('fabric', 'accessory')", name="ck_eco_material_batches_kind"),
        sa.CheckConstraint("quantity >= 0 AND reserved_quantity >= 0 AND reserved_quantity <= quantity", name="ck_eco_material_batches_balance"))
    op.create_index("ix_eco_material_batches_item_id", "eco_material_batches", ["item_id"])
    op.create_table("eco_material_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("eco_material_batches.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False), sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("production_order_id", sa.Integer(), sa.ForeignKey("production_orders.id")),
        sa.Column("reference_type", sa.String(64)), sa.Column("reference_id", sa.Integer()), sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint("kind IN ('receive', 'transfer_receipt', 'consume', 'issue')", name="ck_eco_material_movements_kind"),
        sa.CheckConstraint("quantity > 0", name="ck_eco_material_movements_positive"))
    op.create_index("ix_eco_material_movements_batch_id", "eco_material_movements", ["batch_id"])
    op.create_index("ix_eco_material_movements_production_order_id", "eco_material_movements", ["production_order_id"])
    op.create_table("factory_fabric_transfers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="in_transit"), sa.Column("notes", sa.Text()),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("dispatched_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint("status IN ('in_transit', 'partially_received', 'received')", name="ck_factory_fabric_transfers_status"))
    op.create_table("factory_fabric_transfer_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transfer_id", sa.Integer(), sa.ForeignKey("factory_fabric_transfers.id"), nullable=False),
        sa.Column("source_batch_id", sa.Integer(), sa.ForeignKey("stock_batches.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("item_name", sa.String(255), nullable=False), sa.Column("batch_no", sa.String(64), nullable=False),
        sa.Column("color", sa.String(64)), sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("received_quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.CheckConstraint("quantity > 0 AND received_quantity >= 0 AND received_quantity <= quantity", name="ck_factory_fabric_transfer_lines_quantity"))
    op.create_index("ix_factory_fabric_transfer_lines_transfer_id", "factory_fabric_transfer_lines", ["transfer_id"])


def downgrade():
    # Never silently discard stock or dispatch/receipt evidence.
    connection = op.get_bind()
    for name in ("eco_material_batches", "eco_material_movements", "factory_fabric_transfers", "factory_fabric_transfer_lines"):
        if connection.execute(sa.text(f"SELECT count(*) FROM {name}")).scalar():
            raise RuntimeError("Eco inventory contains business evidence; reconcile it before schema downgrade")
    op.drop_table("factory_fabric_transfer_lines")
    op.drop_table("factory_fabric_transfers")
    op.drop_table("eco_material_movements")
    op.drop_table("eco_material_batches")

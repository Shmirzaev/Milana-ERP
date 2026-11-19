"""ECO order requirements, approved allocations and issued quantities."""
from alembic import op
import sqlalchemy as sa

revision = "0151_eco_accessory_approval"
down_revision = "0150_eco_inventory_transfers"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("eco_accessory_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("production_order_id", sa.Integer(), sa.ForeignKey("production_orders.id"), nullable=False, unique=True),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=False),
        sa.Column("planning_order_id", sa.Integer(), sa.ForeignKey("branded_planning_orders.id"), nullable=False),
        sa.Column("planned_quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("approval_notes", sa.Text()),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint("status IN ('draft','pending','approved','issued')", name="ck_eco_accessory_plan_status"),
        sa.CheckConstraint("revision > 0 AND planned_quantity >= 0", name="ck_eco_accessory_plan_revision"))
    op.create_table("eco_accessory_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("eco_accessory_plans.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(14,4), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.UniqueConstraint("plan_id", "item_id"),
        sa.CheckConstraint("quantity > 0", name="ck_eco_accessory_req_qty"))
    op.create_index("ix_eco_accessory_requirements_plan_id", "eco_accessory_requirements", ["plan_id"])
    op.create_table("eco_accessory_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("requirement_id", sa.Integer(), sa.ForeignKey("eco_accessory_requirements.id"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("eco_material_batches.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(14,4), nullable=False),
        sa.Column("issued_quantity", sa.Numeric(14,4), nullable=False),
        sa.UniqueConstraint("requirement_id", "batch_id"),
        sa.CheckConstraint("quantity > 0 AND issued_quantity >= 0 AND issued_quantity <= quantity", name="ck_eco_accessory_allocation_qty"))
    op.create_index("ix_eco_accessory_allocations_requirement_id", "eco_accessory_allocations", ["requirement_id"])
    op.create_index("ix_eco_accessory_allocations_batch_id", "eco_accessory_allocations", ["batch_id"])


def downgrade():
    # Never silently erase approval/issue evidence, even on an isolated rollback.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM eco_accessory_plans")).scalar():
        raise RuntimeError("ECO accessory history exists; retain schema and roll back application only")
    op.drop_table("eco_accessory_allocations")
    op.drop_table("eco_accessory_requirements")
    op.drop_table("eco_accessory_plans")

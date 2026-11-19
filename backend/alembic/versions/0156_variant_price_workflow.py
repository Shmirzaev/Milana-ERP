"""Explicit variant pricing contributions/approval; preserve historical rows."""
from alembic import op
import sqlalchemy as sa

revision = "0156_variant_price_workflow"
down_revision = "0155_eco_gate_merge"
branch_labels = None
depends_on = None


def upgrade():
    columns = [
        sa.Column("active_model_id", sa.Integer(), nullable=True),
        sa.Column("workflow_state", sa.String(32), nullable=False, server_default="legacy"),
        sa.Column("factory_code", sa.String(3)),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("materials_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("passport_snapshot_json", sa.JSON()),
        sa.Column("purchasing_submitted_at", sa.DateTime(timezone=True)),
        sa.Column("accessories_submitted_at", sa.DateTime(timezone=True)),
        sa.Column("no_accessories_reason", sa.Text()),
        sa.Column("printing_cost", sa.Numeric(14, 4)),
        sa.Column("correction_team", sa.String(16)),
        sa.Column("correction_reason", sa.Text()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by_id", sa.Integer()),
        sa.Column("approval_snapshot_json", sa.JSON()),
        sa.Column("price_baseline_json", sa.JSON()),
    ]
    for column in columns:
        op.add_column("price_calculation_requests", column)
    op.create_foreign_key("fk_price_active_model", "price_calculation_requests", "models", ["active_model_id"], ["id"])
    op.create_foreign_key("fk_price_approved_by", "price_calculation_requests", "users", ["approved_by_id"], ["id"])
    op.create_unique_constraint("uq_price_active_model", "price_calculation_requests", ["active_model_id"])
    op.create_check_constraint("ck_price_workflow_state", "price_calculation_requests", "workflow_state IN ('legacy', 'collecting', 'awaiting_finance', 'approved', 'cancelled')")
    op.create_check_constraint("ck_price_active_variant", "price_calculation_requests", "active_model_id IS NULL OR active_model_id = model_id")
    op.create_index("ix_price_calculation_requests_workflow_state", "price_calculation_requests", ["workflow_state"])
    op.create_index("ix_price_calculation_requests_factory_code", "price_calculation_requests", ["factory_code"])
    # Grant the existing Finance role explicitly; finance.view alone does not
    # grant confirmation. Preserve every existing role permission and deny rule.
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("permissions", sa.JSON))
    connection = op.get_bind()
    for row in connection.execute(sa.select(roles.c.id, roles.c.permissions).where(roles.c.name == "Finance")):
        permissions = list(row.permissions or [])
        if "price_calculation.approve" not in permissions:
            connection.execute(roles.update().where(roles.c.id == row.id).values(permissions=[*permissions, "price_calculation.approve"]))


def downgrade():
    # Do not remove approvals/history through an automatic destructive rollback.
    raise RuntimeError("Variant pricing history requires a reviewed data-preserving rollback; use a forward-compatible image")

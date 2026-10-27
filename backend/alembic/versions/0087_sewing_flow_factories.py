"""Separate Milana and Eco Cotton sewing line data.

Revision ID: 0087_sewing_flow_factories
Revises: 0086_paid_operation_factories
"""

from alembic import op
import sqlalchemy as sa


revision = "0087_sewing_flow_factories"
down_revision = "0086_paid_operation_factories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sewing_flows", sa.Column("factory_code", sa.String(length=16), nullable=True))
    op.execute("UPDATE sewing_flows SET factory_code = 'MIL' WHERE factory_code IS NULL")
    op.alter_column("sewing_flows", "factory_code", nullable=False, server_default="MIL")
    op.drop_constraint("sewing_flows_name_key", "sewing_flows", type_="unique")
    op.drop_constraint("sewing_flows_code_key", "sewing_flows", type_="unique")
    op.create_unique_constraint("uq_sewing_flows_factory_name", "sewing_flows", ["factory_code", "name"])
    op.create_unique_constraint("uq_sewing_flows_factory_code", "sewing_flows", ["factory_code", "code"])
    op.create_check_constraint(
        "ck_sewing_flows_factory_code",
        "sewing_flows",
        "factory_code IN ('MIL', 'BST', 'ECO')",
    )
    op.create_index("ix_sewing_flows_factory_code", "sewing_flows", ["factory_code"])
    op.execute(
        """
        INSERT INTO sewing_flows
            (factory_code, name, code, description, capacity_per_day, supervisor_id, is_active, created_at, updated_at)
        SELECT
            'ECO', name, code, 'ECO sewing flow ' || name, capacity_per_day, NULL, is_active, NOW(), NOW()
        FROM sewing_flows
        WHERE factory_code = 'MIL'
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM sewing_flows WHERE factory_code = 'ECO'")
    op.drop_index("ix_sewing_flows_factory_code", table_name="sewing_flows")
    op.drop_constraint("ck_sewing_flows_factory_code", "sewing_flows", type_="check")
    op.drop_constraint("uq_sewing_flows_factory_code", "sewing_flows", type_="unique")
    op.drop_constraint("uq_sewing_flows_factory_name", "sewing_flows", type_="unique")
    op.create_unique_constraint("sewing_flows_code_key", "sewing_flows", ["code"])
    op.create_unique_constraint("sewing_flows_name_key", "sewing_flows", ["name"])
    op.drop_column("sewing_flows", "factory_code")

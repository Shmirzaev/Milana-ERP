"""limit default active sewing flows

Revision ID: 0037_limit_default_sewing_flows
Revises: 0036_reset_zero_storage_transfer
Create Date: 2026-07-08
"""
from alembic import op


revision = "0037_limit_default_sewing_flows"
down_revision = "0036_reset_zero_storage_transfer"
branch_labels = None
depends_on = None


EXTRA_DEFAULT_FLOW_CODES = tuple(f"SEW-{i:02d}" for i in range(11, 31))


def _quoted_codes() -> str:
    return ", ".join(f"'{code}'" for code in EXTRA_DEFAULT_FLOW_CODES)


def upgrade():
    op.execute(
        f"""
        UPDATE sewing_flows
        SET is_active = false
        WHERE code IN ({_quoted_codes()})
        """
    )


def downgrade():
    op.execute(
        f"""
        UPDATE sewing_flows
        SET is_active = true
        WHERE code IN ({_quoted_codes()})
        """
    )

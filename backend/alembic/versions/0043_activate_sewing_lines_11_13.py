"""activate sewing lines 11 12 13

Revision ID: 0043_activate_sewing_lines_11_13
Revises: 0042_sewing_assignment_batches
Create Date: 2026-07-10
"""
from alembic import op


revision = "0043_activate_sewing_lines_11_13"
down_revision = "0042_sewing_assignment_batches"
branch_labels = None
depends_on = None


LINES = (
    ("Line 11", "SEW-11"),
    ("Line 12", "SEW-12"),
    ("Line 13", "SEW-13"),
)


def upgrade():
    values = ", ".join(
        f"('{name}', '{code}', 'Sewing flow {name}', 200, true)"
        for name, code in LINES
    )
    op.execute(
        f"""
        INSERT INTO sewing_flows (name, code, description, capacity_per_day, is_active)
        VALUES {values}
        ON CONFLICT (code) DO UPDATE
        SET is_active = true,
            updated_at = now()
        """
    )


def downgrade():
    codes = ", ".join(f"'{code}'" for _, code in LINES)
    op.execute(
        f"""
        UPDATE sewing_flows
        SET is_active = false,
            updated_at = now()
        WHERE code IN ({codes})
        """
    )

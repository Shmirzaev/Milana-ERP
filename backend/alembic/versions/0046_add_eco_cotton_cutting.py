"""add Eco Cotton cutting department

Revision ID: 0046_add_eco_cotton_cutting
Revises: 0045_add_eco_cotton_departments
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0046_add_eco_cotton_cutting"
down_revision = "0045_add_eco_cotton_departments"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO departments (name, code, created_at, updated_at)
            SELECT 'Eco Cotton Cutting', 'ECT', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (SELECT 1 FROM departments WHERE code = 'ECT')
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO warehouses (name, type, department_id, created_at, updated_at)
            SELECT 'Eco Cotton Cutting Floor', 'eco_cotton_cutting', d.id,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM departments d
            WHERE d.code = 'ECT'
              AND NOT EXISTS (
                  SELECT 1 FROM warehouses WHERE type = 'eco_cotton_cutting'
              )
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM warehouses WHERE type = 'eco_cotton_cutting'"))
    bind.execute(sa.text("DELETE FROM departments WHERE code = 'ECT'"))

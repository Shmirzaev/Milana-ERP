"""add Eco Cotton sewing and packaging departments

Revision ID: 0045_add_eco_cotton_departments
Revises: 0044_consolidate_sewing_lines
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0045_add_eco_cotton_departments"
down_revision = "0044_consolidate_sewing_lines"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for name, code in (
        ("Eco Cotton Sewing Factory", "ECO"),
        ("Eco Cotton Packaging", "ECP"),
    ):
        bind.execute(
            sa.text(
                """
                INSERT INTO departments (name, code, created_at, updated_at)
                SELECT :name, :code, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                WHERE NOT EXISTS (SELECT 1 FROM departments WHERE code = :code)
                """
            ),
            {"name": name, "code": code},
        )

    bind.execute(
        sa.text(
            """
            INSERT INTO warehouses (name, type, department_id, created_at, updated_at)
            SELECT 'Eco Cotton Packaging Floor', 'eco_cotton_packaging', d.id,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM departments d
            WHERE d.code = 'ECP'
              AND NOT EXISTS (
                  SELECT 1 FROM warehouses WHERE type = 'eco_cotton_packaging'
              )
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM warehouses WHERE type = 'eco_cotton_packaging'"))
    bind.execute(sa.text("DELETE FROM departments WHERE code IN ('ECO', 'ECP')"))

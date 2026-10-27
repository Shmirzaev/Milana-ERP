"""add unique employee staff number

Revision ID: 0083_employee_number
Revises: 0082_sewing_size_quantities
"""

import sqlalchemy as sa
from alembic import op


revision = "0083_employee_number"
down_revision = "0082_sewing_size_quantities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("employee_no", sa.String(length=32), nullable=True))
    op.create_index("ix_employees_employee_no", "employees", ["employee_no"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_employees_employee_no", table_name="employees")
    op.drop_column("employees", "employee_no")

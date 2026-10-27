"""Retain the owner-approved four-decimal employee salary rounding."""
from alembic import op
import sqlalchemy as sa

revision = "0136_employee_salary_precision"
down_revision = "0135_usluga_paid_processes"
branch_labels = None
depends_on = None


def upgrade():
    # Keep the existing ten integer digits; only widen fractional precision.
    with op.batch_alter_table("employees") as batch:
        batch.alter_column("salary", existing_type=sa.Numeric(12, 2),
                           type_=sa.Numeric(14, 4), existing_nullable=True)


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("Employee salary downgrade requires an online precision check")
    employee_id = op.get_bind().execute(sa.text(
        "SELECT id FROM employees WHERE salary != ROUND(salary, 2) LIMIT 1"
    )).scalar()
    if employee_id is not None:
        raise RuntimeError(
            f"Cannot downgrade employee salary precision: employee {employee_id} has "
            "a salary requiring four decimals. Reconcile these values explicitly first."
        )
    with op.batch_alter_table("employees") as batch:
        batch.alter_column("salary", existing_type=sa.Numeric(14, 4),
                           type_=sa.Numeric(12, 2), existing_nullable=True)

"""add payroll adjustment types

Revision ID: 0027_payroll_adjustment_types
Revises: 0026_forecast_recommendations
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa


revision = "0027_payroll_adjustment_types"
down_revision = "0026_forecast_recommendations"
branch_labels = None
depends_on = None


def _has_check(inspector, table_name: str, name: str) -> bool:
    return any(check.get("name") == name for check in inspector.get_check_constraints(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "payroll_adjustments" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("payroll_adjustments")}
    if "adjustment_type" not in columns:
        op.add_column(
            "payroll_adjustments",
            sa.Column("adjustment_type", sa.String(length=16), nullable=False, server_default="bonus"),
        )

    inspector = sa.inspect(bind)
    if bind.dialect.name != "sqlite" and not _has_check(inspector, "payroll_adjustments", "ck_payroll_adjustments_type"):
        op.create_check_constraint(
            "ck_payroll_adjustments_type",
            "payroll_adjustments",
            "adjustment_type IN ('bonus', 'deduction')",
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "payroll_adjustments" not in tables:
        return

    if bind.dialect.name != "sqlite" and _has_check(inspector, "payroll_adjustments", "ck_payroll_adjustments_type"):
        op.drop_constraint("ck_payroll_adjustments_type", "payroll_adjustments", type_="check")

    columns = {column["name"] for column in inspector.get_columns("payroll_adjustments")}
    if "adjustment_type" in columns and bind.dialect.name != "sqlite":
        op.drop_column("payroll_adjustments", "adjustment_type")

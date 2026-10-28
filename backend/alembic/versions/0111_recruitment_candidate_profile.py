"""Add the minimal recruitment candidate profile fields.

Revision ID: 0111_recruitment_profile
Revises: 0110_hr_workspace
"""

from alembic import op
import sqlalchemy as sa


revision = "0111_recruitment_profile"
down_revision = "0110_hr_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "hr_recruitment_candidates"
    op.add_column(table, sa.Column("department_id", sa.Integer(), nullable=True))
    op.add_column(table, sa.Column("first_name", sa.String(100), nullable=True))
    op.add_column(table, sa.Column("last_name", sa.String(100), nullable=True))
    op.add_column(table, sa.Column("middle_name", sa.String(100), nullable=True))
    op.add_column(table, sa.Column("date_of_birth", sa.Date(), nullable=True))
    op.add_column(table, sa.Column("gender", sa.String(16), nullable=True))
    op.add_column(table, sa.Column("nationality", sa.String(80), nullable=True))
    op.add_column(table, sa.Column("country", sa.String(80), nullable=True))
    op.add_column(table, sa.Column("region", sa.String(120), nullable=True))
    op.add_column(table, sa.Column("district", sa.String(120), nullable=True))
    op.add_column(table, sa.Column("address", sa.String(255), nullable=True))
    op.add_column(table, sa.Column("passport_number", sa.String(32), nullable=True))
    op.add_column(table, sa.Column("passport_issued_by", sa.String(255), nullable=True))
    op.add_column(table, sa.Column("passport_issue_date", sa.Date(), nullable=True))
    op.add_column(table, sa.Column("passport_expiry_date", sa.Date(), nullable=True))
    op.add_column(table, sa.Column("pinfl", sa.String(14), nullable=True))
    op.create_foreign_key(
        "fk_hr_recruitment_candidates_department_id", table, "departments", ["department_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_hr_recruitment_candidates_department_id", table, ["department_id"])
    op.create_index("ix_hr_recruitment_candidates_pinfl", table, ["pinfl"])
    op.create_index(
        "uq_hr_recruitment_candidates_factory_pinfl", table, ["factory_code", "pinfl"], unique=True,
        postgresql_where=sa.text("pinfl IS NOT NULL"),
    )


def downgrade() -> None:
    table = "hr_recruitment_candidates"
    op.drop_index("uq_hr_recruitment_candidates_factory_pinfl", table_name=table)
    op.drop_index("ix_hr_recruitment_candidates_pinfl", table_name=table)
    op.drop_index("ix_hr_recruitment_candidates_department_id", table_name=table)
    op.drop_constraint("fk_hr_recruitment_candidates_department_id", table, type_="foreignkey")
    for column in (
        "pinfl", "passport_expiry_date", "passport_issue_date", "passport_issued_by", "passport_number",
        "address", "district", "region", "country", "nationality", "gender", "date_of_birth",
        "middle_name", "last_name", "first_name", "department_id",
    ):
        op.drop_column(table, column)

"""add details_json field to models

Revision ID: 0004_model_details_json
Revises: 0003_plan_expense_fields
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_model_details_json"
down_revision = "0003_plan_expense_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("models", sa.Column("details_json", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("models", "details_json")

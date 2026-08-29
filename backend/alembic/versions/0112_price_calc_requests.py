"""add collaborative price calculation requests

Revision ID: 0112_price_calc_requests
Revises: 0111_recruitment_profile
"""

from alembic import op
import sqlalchemy as sa


revision = "0112_price_calc_requests"
down_revision = "0111_recruitment_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_calculation_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kroy_no", sa.String(length=32), nullable=True),
        sa.Column("cutting_passport_id", sa.Integer(), sa.ForeignKey("cutting_passports.id"), nullable=True),
        sa.Column("fabric_width_m", sa.Numeric(14, 4), nullable=True),
        sa.Column("lay_length_m", sa.Numeric(14, 4), nullable=True),
        sa.Column("size_count", sa.Integer(), nullable=True),
        sa.Column("gramage", sa.Numeric(14, 6), nullable=True),
        sa.Column("binding_kg_per_piece", sa.Numeric(14, 6), nullable=True),
        sa.Column("fabric_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("sewing_cost", sa.Numeric(14, 4), nullable=True),
        sa.Column("purchasing_updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("accessories_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("accessories_updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cost_price_uzs", sa.Numeric(18, 2), nullable=True),
        sa.Column("selling_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("profit_percentage", sa.Numeric(8, 2), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(14, 4), nullable=True),
        sa.Column("finance_updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_price_calculation_requests_model_id", "price_calculation_requests", ["model_id"])
    op.create_index("ix_price_calculation_requests_created_by_id", "price_calculation_requests", ["created_by_id"])
    op.create_index("ix_price_calculation_requests_kroy_no", "price_calculation_requests", ["kroy_no"])


def downgrade() -> None:
    op.drop_index("ix_price_calculation_requests_kroy_no", table_name="price_calculation_requests")
    op.drop_index("ix_price_calculation_requests_created_by_id", table_name="price_calculation_requests")
    op.drop_index("ix_price_calculation_requests_model_id", table_name="price_calculation_requests")
    op.drop_table("price_calculation_requests")

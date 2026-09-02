"""store selling price on each exact model variant

Revision ID: 0113_variant_selling_price
Revises: 0112_price_calc_requests
"""

from alembic import op
import sqlalchemy as sa


revision = "0113_variant_selling_price"
down_revision = "0112_price_calc_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("models", sa.Column("selling_price", sa.Numeric(14, 4), nullable=True))
    op.add_column("models", sa.Column("selling_price_currency", sa.String(length=3), nullable=True))
    op.add_column("models", sa.Column("selling_price_source", sa.String(length=32), nullable=True))
    op.add_column(
        "models",
        sa.Column(
            "selling_price_request_id",
            sa.Integer(),
            sa.ForeignKey(
                "price_calculation_requests.id",
                name="fk_models_selling_price_request_id",
                use_alter=True,
            ),
            nullable=True,
        ),
    )
    op.add_column("models", sa.Column("selling_price_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_models_selling_price_request_id", "models", ["selling_price_request_id"])


def downgrade() -> None:
    op.drop_index("ix_models_selling_price_request_id", table_name="models")
    op.drop_column("models", "selling_price_updated_at")
    op.drop_column("models", "selling_price_request_id")
    op.drop_column("models", "selling_price_source")
    op.drop_column("models", "selling_price_currency")
    op.drop_column("models", "selling_price")

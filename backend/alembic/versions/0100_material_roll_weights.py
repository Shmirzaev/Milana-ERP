"""store individual material roll weights

Revision ID: 0100_material_roll_weights
Revises: 0099_payroll_qr_edit_split
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0100_material_roll_weights"
down_revision = "0099_payroll_qr_edit_split"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_batches",
        sa.Column(
            "roll_weights_kg",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("stock_batches", "roll_weights_kg")

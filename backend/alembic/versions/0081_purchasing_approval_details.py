"""persist purchasing approval and active-order details

Revision ID: 0081_purchasing_approval_details
Revises: 0080_piecework_assignments
"""

import sqlalchemy as sa
from alembic import op


revision = "0081_purchasing_approval_details"
down_revision = "0080_piecework_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_request_lines", sa.Column("material_name", sa.String(length=255), nullable=True))
    op.add_column("purchase_request_lines", sa.Column("photo_url", sa.String(length=500), nullable=True))
    op.add_column("purchase_order_lines", sa.Column("supplier_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_purchase_order_lines_supplier_id",
        "purchase_order_lines",
        "suppliers",
        ["supplier_id"],
        ["id"],
    )
    op.add_column("purchase_order_lines", sa.Column("material_name", sa.String(length=255), nullable=True))
    op.add_column("purchase_order_lines", sa.Column("photo_url", sa.String(length=500), nullable=True))

    op.execute("""
        UPDATE purchase_request_lines AS line
        SET material_name = item.name,
            photo_url = item.image_url
        FROM items AS item
        WHERE item.id = line.item_id
          AND (line.material_name IS NULL OR line.photo_url IS NULL)
    """)


def downgrade() -> None:
    op.drop_column("purchase_order_lines", "photo_url")
    op.drop_column("purchase_order_lines", "material_name")
    op.drop_constraint("fk_purchase_order_lines_supplier_id", "purchase_order_lines", type_="foreignkey")
    op.drop_column("purchase_order_lines", "supplier_id")
    op.drop_column("purchase_request_lines", "photo_url")
    op.drop_column("purchase_request_lines", "material_name")

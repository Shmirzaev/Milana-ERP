"""add item composition json

Revision ID: 0029_item_composition_json
Revises: 0028_idempotency
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "0029_item_composition_json"
down_revision = "0028_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("items")}
    if "composition_json" not in columns:
        if bind.dialect.name == "postgresql":
            op.add_column(
                "items",
                sa.Column(
                    "composition_json",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'::json"),
                ),
            )
        else:
            op.add_column(
                "items",
                sa.Column("composition_json", sa.JSON(), nullable=False, server_default="[]"),
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("items")}
    if "composition_json" in columns:
        op.drop_column("items", "composition_json")

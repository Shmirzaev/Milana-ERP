"""add batch link to packages

Revision ID: 0009_package_batch_link
Revises: 0008_stock_batch_fields
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_package_batch_link"
down_revision = "0008_stock_batch_fields"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "packages" not in tables:
        return

    columns = {c["name"] for c in inspector.get_columns("packages")}
    if "production_batch_id" not in columns:
        op.add_column("packages", sa.Column("production_batch_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_packages_production_batch_id",
            "packages",
            "production_batches",
            ["production_batch_id"],
            ["id"],
        )
        op.create_index(op.f("ix_packages_production_batch_id"), "packages", ["production_batch_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "packages" not in tables:
        return

    columns = {c["name"] for c in inspector.get_columns("packages")}
    if "production_batch_id" in columns:
        indexes = inspector.get_indexes("packages")
        if any(ix.get("name") == op.f("ix_packages_production_batch_id") for ix in indexes):
            op.drop_index(op.f("ix_packages_production_batch_id"), table_name="packages")
        fks = inspector.get_foreign_keys("packages")
        fk_names = [fk.get("name") for fk in fks if "production_batch_id" in (fk.get("constrained_columns") or [])]
        for fk_name in fk_names:
            if fk_name:
                op.drop_constraint(fk_name, "packages", type_="foreignkey")
        op.drop_column("packages", "production_batch_id")

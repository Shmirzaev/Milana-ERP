"""add legacy finished-goods receipt evidence and package barcode aliases

Revision ID: 0069_legacy_finished_goods
Revises: 0068_daily_sewing_two_parts
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0069_legacy_finished_goods"
down_revision = "0068_daily_sewing_two_parts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "legacy_stock_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=32), nullable=False),
        sa.Column("source_warehouse_id", sa.String(length=64), nullable=False),
        sa.Column("source_warehouse_name", sa.String(length=255), nullable=True),
        sa.Column("source_record_id", sa.String(length=128), nullable=False),
        sa.Column("source_checksum", sa.String(length=64), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("imported_by", sa.Integer(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["imported_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_system",
            "source_warehouse_id",
            "source_record_id",
            name="uq_legacy_stock_receipts_source_record",
        ),
    )

    op.add_column("packages", sa.Column("legacy_receipt_id", sa.Integer(), nullable=True))
    op.alter_column("packages", "production_order_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key(
        "fk_packages_legacy_receipt_id",
        "packages",
        "legacy_stock_receipts",
        ["legacy_receipt_id"],
        ["id"],
    )
    op.create_index("ix_packages_legacy_receipt_id", "packages", ["legacy_receipt_id"], unique=True)
    op.create_check_constraint(
        "ck_packages_source_evidence",
        "packages",
        "production_order_id IS NOT NULL OR legacy_receipt_id IS NOT NULL",
    )

    op.create_table(
        "package_barcode_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("code_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("package_id", "code", name="uq_package_barcode_alias_package_code"),
    )
    op.create_index("ix_package_barcode_aliases_package_id", "package_barcode_aliases", ["package_id"])
    op.create_index("ix_package_barcode_aliases_code", "package_barcode_aliases", ["code"])


def downgrade():
    op.drop_index("ix_package_barcode_aliases_code", table_name="package_barcode_aliases")
    op.drop_index("ix_package_barcode_aliases_package_id", table_name="package_barcode_aliases")
    op.drop_table("package_barcode_aliases")
    op.drop_constraint("ck_packages_source_evidence", "packages", type_="check")
    op.drop_index("ix_packages_legacy_receipt_id", table_name="packages")
    op.drop_constraint("fk_packages_legacy_receipt_id", "packages", type_="foreignkey")
    op.alter_column("packages", "production_order_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("packages", "legacy_receipt_id")
    op.drop_table("legacy_stock_receipts")

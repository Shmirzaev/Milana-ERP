"""add shipment scan logs

Revision ID: 0007_shipment_scan_logs
Revises: 0006_production_batches
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_shipment_scan_logs"
down_revision = "0006_production_batches"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "shipment_scan_logs" not in tables:
        op.create_table(
            "shipment_scan_logs",
            sa.Column("shipment_id", sa.Integer(), nullable=False),
            sa.Column("package_id", sa.Integer(), nullable=True),
            sa.Column("scanned_code", sa.String(length=128), nullable=False),
            sa.Column("scan_result", sa.String(length=32), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("scanned_by", sa.Integer(), nullable=True),
            sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["package_id"], ["packages.id"]),
            sa.ForeignKeyConstraint(["scanned_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_shipment_scan_logs_shipment_id"), "shipment_scan_logs", ["shipment_id"], unique=False)
        op.create_index(op.f("ix_shipment_scan_logs_package_id"), "shipment_scan_logs", ["package_id"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "shipment_scan_logs" in tables:
        op.drop_index(op.f("ix_shipment_scan_logs_package_id"), table_name="shipment_scan_logs")
        op.drop_index(op.f("ix_shipment_scan_logs_shipment_id"), table_name="shipment_scan_logs")
        op.drop_table("shipment_scan_logs")

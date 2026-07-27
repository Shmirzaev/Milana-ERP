"""add payroll QR issuance and return tracking

Revision ID: 0053_payroll_qr_control
Revises: 0052_packaging_receipts
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0053_payroll_qr_control"
down_revision = "0052_packaging_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payroll_records", sa.Column("original_scan_uid", sa.String(length=128), nullable=True))
    op.create_index("ix_payroll_records_original_scan_uid", "payroll_records", ["original_scan_uid"])
    op.execute("UPDATE payroll_records SET original_scan_uid = scan_uid WHERE scan_uid IS NOT NULL")

    op.create_table(
        "payroll_qr_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("label_uid", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("production_order_id", sa.Integer(), nullable=True),
        sa.Column("sales_order_id", sa.Integer(), nullable=True),
        sa.Column("work_order_id", sa.Integer(), nullable=True),
        sa.Column("production_batch_id", sa.Integer(), nullable=True),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("production_no", sa.String(length=64), nullable=True),
        sa.Column("sales_order_no", sa.String(length=64), nullable=True),
        sa.Column("batch_no", sa.String(length=64), nullable=True),
        sa.Column("model_code", sa.String(length=64), nullable=True),
        sa.Column("operation_section", sa.String(length=64), nullable=True),
        sa.Column("operation_code", sa.String(length=64), nullable=True),
        sa.Column("operation_name", sa.String(length=255), nullable=True),
        sa.Column("size", sa.String(length=32), nullable=True),
        sa.Column("copy_index", sa.Integer(), server_default="1", nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("rate_per_piece", sa.Numeric(14, 4), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="UZS", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="available", nullable=False),
        sa.Column("payroll_record_id", sa.Integer(), nullable=True),
        sa.Column("issued_by", sa.Integer(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_by", sa.Integer(), nullable=True),
        sa.Column("return_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_payroll_qr_labels_quantity_nonnegative"),
        sa.CheckConstraint("rate_per_piece >= 0", name="ck_payroll_qr_labels_rate_nonnegative"),
        sa.CheckConstraint("return_count >= 0", name="ck_payroll_qr_labels_return_count_nonnegative"),
        sa.CheckConstraint("status IN ('available', 'scanned')", name="ck_payroll_qr_labels_status"),
        sa.ForeignKeyConstraint(["issued_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"]),
        sa.ForeignKeyConstraint(["payroll_record_id"], ["payroll_records.id"]),
        sa.ForeignKeyConstraint(["production_batch_id"], ["production_batches.id"]),
        sa.ForeignKeyConstraint(["production_order_id"], ["production_orders.id"]),
        sa.ForeignKeyConstraint(["returned_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"]),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label_uid", name="uq_payroll_qr_labels_label_uid"),
    )
    for column in (
        "label_uid",
        "production_order_id",
        "sales_order_id",
        "work_order_id",
        "production_batch_id",
        "sales_order_no",
        "status",
        "payroll_record_id",
    ):
        op.create_index(f"ix_payroll_qr_labels_{column}", "payroll_qr_labels", [column])

    op.execute(
        """
        INSERT INTO payroll_qr_labels (
            label_uid, production_order_id, sales_order_id, work_order_id,
            production_batch_id, model_id, production_no, sales_order_no,
            batch_no, model_code, operation_section, operation_code,
            operation_name, size, copy_index, quantity, rate_per_piece,
            currency, status, payroll_record_id, issued_by, issued_at,
            last_scanned_at, returned_at, return_count, created_at, updated_at
        )
        SELECT
            pr.scan_uid, pr.production_order_id, pr.sales_order_id, pr.work_order_id,
            pr.production_batch_id, pr.model_id, pr.production_no, pr.sales_order_no,
            pr.batch_no, pr.model_code, pr.operation_section, pr.operation_code,
            pr.operation_name, pr.raw_work_json ->> 'size', 1,
            pr.quantity, pr.rate_per_piece, pr.currency,
            CASE WHEN pr.status = 'voided' THEN 'available' ELSE 'scanned' END,
            CASE WHEN pr.status = 'voided' THEN NULL ELSE pr.id END,
            pr.scanned_by, pr.created_at, pr.scanned_at,
            CASE WHEN pr.status = 'voided' THEN pr.updated_at ELSE NULL END,
            CASE WHEN pr.status = 'voided' THEN 1 ELSE 0 END,
            pr.created_at, pr.updated_at
        FROM payroll_records pr
        WHERE pr.scan_uid IS NOT NULL
        ON CONFLICT (label_uid) DO NOTHING
        """
    )


def downgrade():
    for column in (
        "payroll_record_id",
        "status",
        "sales_order_no",
        "production_batch_id",
        "work_order_id",
        "sales_order_id",
        "production_order_id",
        "label_uid",
    ):
        op.drop_index(f"ix_payroll_qr_labels_{column}", table_name="payroll_qr_labels")
    op.drop_table("payroll_qr_labels")
    op.drop_index("ix_payroll_records_original_scan_uid", table_name="payroll_records")
    op.drop_column("payroll_records", "original_scan_uid")

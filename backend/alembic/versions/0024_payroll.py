"""add payroll persistence

Revision ID: 0024_payroll
Revises: 0023_purchasing
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa


revision = "0024_payroll"
down_revision = "0023_purchasing"
branch_labels = None
depends_on = None


def _create_index_if_missing(inspector, name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if name not in indexes:
        op.create_index(name, table_name, columns, unique=unique)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "payroll_periods" not in tables:
        op.create_table(
            "payroll_periods",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("period_no", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "status IN ('draft', 'open', 'locked', 'approved', 'paid', 'cancelled')",
                name="ck_payroll_periods_status",
            ),
            sa.UniqueConstraint("period_no", name="uq_payroll_periods_period_no"),
        )
    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, "ix_payroll_periods_period_no", "payroll_periods", ["period_no"], unique=True)

    if "payroll_records" not in tables:
        op.create_table(
            "payroll_records",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("payroll_period_id", sa.Integer(), sa.ForeignKey("payroll_periods.id"), nullable=True),
            sa.Column("scan_uid", sa.String(length=128), nullable=True),
            sa.Column("dedupe_key", sa.String(length=64), nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
            sa.Column("employee_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("production_order_id", sa.Integer(), sa.ForeignKey("production_orders.id"), nullable=True),
            sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_orders.id"), nullable=True),
            sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=True),
            sa.Column("production_batch_id", sa.Integer(), sa.ForeignKey("production_batches.id"), nullable=True),
            sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=True),
            sa.Column("production_no", sa.String(length=64), nullable=True),
            sa.Column("sales_order_no", sa.String(length=64), nullable=True),
            sa.Column("batch_no", sa.String(length=64), nullable=True),
            sa.Column("model_code", sa.String(length=64), nullable=True),
            sa.Column("operation_section", sa.String(length=64), nullable=True),
            sa.Column("operation_code", sa.String(length=64), nullable=True),
            sa.Column("operation_name", sa.String(length=255), nullable=True),
            sa.Column("quantity", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("rate_per_piece", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="UZS"),
            sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("scanned_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False, server_default="payroll_scan"),
            sa.Column("raw_employee_json", sa.JSON(), nullable=True),
            sa.Column("raw_work_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="recorded"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.CheckConstraint("quantity >= 0", name="ck_payroll_records_quantity_nonnegative"),
            sa.CheckConstraint("rate_per_piece >= 0", name="ck_payroll_records_rate_nonnegative"),
            sa.CheckConstraint("total_amount >= 0", name="ck_payroll_records_total_nonnegative"),
            sa.CheckConstraint("status IN ('recorded', 'voided', 'approved', 'paid')", name="ck_payroll_records_status"),
            sa.UniqueConstraint("scan_uid", name="uq_payroll_records_scan_uid"),
            sa.UniqueConstraint("dedupe_key", name="uq_payroll_records_dedupe_key"),
        )
    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, "ix_payroll_records_payroll_period_id", "payroll_records", ["payroll_period_id"])
    _create_index_if_missing(inspector, "ix_payroll_records_employee_id", "payroll_records", ["employee_id"])
    _create_index_if_missing(inspector, "ix_payroll_records_scan_uid", "payroll_records", ["scan_uid"])
    _create_index_if_missing(inspector, "ix_payroll_records_dedupe_key", "payroll_records", ["dedupe_key"])

    if "payroll_adjustments" not in tables:
        op.create_table(
            "payroll_adjustments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("payroll_period_id", sa.Integer(), sa.ForeignKey("payroll_periods.id"), nullable=True),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="UZS"),
            sa.Column("reason", sa.String(length=255), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("amount >= 0", name="ck_payroll_adjustments_amount_nonnegative"),
        )
    inspector = sa.inspect(bind)
    _create_index_if_missing(inspector, "ix_payroll_adjustments_payroll_period_id", "payroll_adjustments", ["payroll_period_id"])
    _create_index_if_missing(inspector, "ix_payroll_adjustments_employee_id", "payroll_adjustments", ["employee_id"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "payroll_adjustments" in tables:
        op.drop_table("payroll_adjustments")
    if "payroll_records" in tables:
        op.drop_table("payroll_records")
    if "payroll_periods" in tables:
        op.drop_table("payroll_periods")

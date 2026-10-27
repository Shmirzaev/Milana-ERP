"""add secure sewing piecework assignments and acceptances

Revision ID: 0080_piecework_assignments
Revises: 0079_sewing_accepted_defects, 0075_piecework_assignments
"""

import sqlalchemy as sa
from alembic import op


revision = "0080_piecework_assignments"
down_revision = ("0079_sewing_accepted_defects", "0075_piecework_assignments")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "piecework_shifts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("sewing_flow_id", sa.Integer(), sa.ForeignKey("sewing_flows.id"), nullable=False),
        sa.Column("supervisor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('open', 'closed')", name="ck_piecework_shifts_status"),
        sa.UniqueConstraint("work_date", "sewing_flow_id", name="uq_piecework_shifts_date_flow"),
    )
    op.create_index("ix_piecework_shifts_work_date", "piecework_shifts", ["work_date"])
    op.create_index("ix_piecework_shifts_sewing_flow_id", "piecework_shifts", ["sewing_flow_id"])
    op.create_index("ix_piecework_shifts_supervisor_id", "piecework_shifts", ["supervisor_id"])
    op.create_index("ix_piecework_shifts_status", "piecework_shifts", ["status"])

    op.create_table(
        "piecework_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("piecework_shifts.id"), nullable=False),
        sa.Column("production_order_id", sa.Integer(), sa.ForeignKey("production_orders.id"), nullable=False),
        sa.Column("production_batch_id", sa.Integer(), sa.ForeignKey("production_batches.id"), nullable=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=True),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column("operation_section", sa.String(length=64), nullable=False),
        sa.Column("operation_code", sa.String(length=64), nullable=False),
        sa.Column("operation_name", sa.String(length=255), nullable=False),
        sa.Column("size", sa.String(length=32), nullable=False),
        sa.Column("planned_quantity", sa.Integer(), nullable=False),
        sa.Column("accepted_good_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("accepted_defect_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rate_per_piece", sa.Numeric(14, 4), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="UZS", nullable=False),
        sa.Column("standard_seconds", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("source_operation_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="planned", nullable=False),
        sa.Column("assigned_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("planned_quantity > 0", name="ck_piecework_assignments_planned_positive"),
        sa.CheckConstraint("accepted_good_quantity >= 0", name="ck_piecework_assignments_good_nonnegative"),
        sa.CheckConstraint("accepted_defect_quantity >= 0", name="ck_piecework_assignments_defect_nonnegative"),
        sa.CheckConstraint(
            "accepted_good_quantity + accepted_defect_quantity <= planned_quantity",
            name="ck_piecework_assignments_accepted_within_plan",
        ),
        sa.CheckConstraint("rate_per_piece >= 0", name="ck_piecework_assignments_rate_nonnegative"),
        sa.CheckConstraint("standard_seconds >= 0", name="ck_piecework_assignments_seconds_nonnegative"),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'completed', 'cancelled')",
            name="ck_piecework_assignments_status",
        ),
    )
    for column in (
        "shift_id", "production_order_id", "production_batch_id", "work_order_id", "model_id",
        "employee_id", "operation_key", "size", "status",
    ):
        op.create_index(f"ix_piecework_assignments_{column}", "piecework_assignments", [column])

    op.create_table(
        "piecework_acceptances",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("piecework_assignments.id"), nullable=False),
        sa.Column("good_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("defect_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rate_per_piece", sa.Numeric(14, 4), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default="UZS", nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("accepted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payroll_record_id", sa.Integer(), sa.ForeignKey("payroll_records.id"), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="posted", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reversal_reason", sa.String(length=255), nullable=True),
        sa.CheckConstraint("good_quantity >= 0", name="ck_piecework_acceptances_good_nonnegative"),
        sa.CheckConstraint("defect_quantity >= 0", name="ck_piecework_acceptances_defect_nonnegative"),
        sa.CheckConstraint("good_quantity + defect_quantity > 0", name="ck_piecework_acceptances_quantity_positive"),
        sa.CheckConstraint("rate_per_piece >= 0", name="ck_piecework_acceptances_rate_nonnegative"),
        sa.CheckConstraint("total_amount >= 0", name="ck_piecework_acceptances_total_nonnegative"),
        sa.CheckConstraint("status IN ('posted', 'reversed')", name="ck_piecework_acceptances_status"),
        sa.UniqueConstraint("idempotency_key", name="uq_piecework_acceptances_idempotency_key"),
        sa.UniqueConstraint("payroll_record_id", name="uq_piecework_acceptances_payroll_record_id"),
    )
    for column in ("assignment_id", "idempotency_key", "payroll_record_id", "status"):
        op.create_index(f"ix_piecework_acceptances_{column}", "piecework_acceptances", [column])


def downgrade() -> None:
    op.drop_table("piecework_acceptances")
    op.drop_table("piecework_assignments")
    op.drop_table("piecework_shifts")

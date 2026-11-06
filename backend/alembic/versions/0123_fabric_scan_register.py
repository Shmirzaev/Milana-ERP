"""Add an isolated daily fabric roll scan register."""
from alembic import op
import sqlalchemy as sa

revision = "0123_fabric_scan_register"
down_revision = "0122_cutting_material_details"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fabric_scans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("department", sa.String(8), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("roll_number", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("fabric_name", sa.String(255), nullable=False),
        sa.Column("batch_no", sa.String(64), nullable=False),
        sa.Column("color", sa.String(64)),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("operator_name", sa.String(255), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("department", "report_date", "batch_id", "roll_number", "direction", name="uq_fabric_scan_daily_roll"),
        sa.CheckConstraint("direction IN ('received', 'returned')", name="ck_fabric_scan_direction"),
        sa.CheckConstraint("department IN ('CUT', 'ECT')", name="ck_fabric_scan_department"),
        sa.CheckConstraint("roll_number > 0", name="ck_fabric_scan_roll"),
    )
    op.create_index("ix_fabric_scan_department_date", "fabric_scans", ["department", "report_date"])


def downgrade():
    op.drop_index("ix_fabric_scan_department_date", table_name="fabric_scans")
    op.drop_table("fabric_scans")

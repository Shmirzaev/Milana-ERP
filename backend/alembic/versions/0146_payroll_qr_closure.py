"""Keep unscanned payroll labels when Control closes their scan group."""
from alembic import op
import sqlalchemy as sa

revision = "0146_payroll_qr_closure"
down_revision = "0145_packaging_size_entry"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("package_print_runs", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_qr_labels", sa.Column("closure_details", sa.JSON(), nullable=True))
    op.drop_constraint("ck_payroll_qr_labels_status", "payroll_qr_labels", type_="check")
    op.create_check_constraint("ck_payroll_qr_labels_status", "payroll_qr_labels",
                               "status IN ('available', 'scanned', 'superseded', 'closed')")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM package_print_runs WHERE superseded_at IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Preserve corrected print-run evidence before downgrade")
    if op.get_bind().execute(sa.text(
        "SELECT 1 FROM payroll_qr_labels WHERE status = 'closed' OR closure_details IS NOT NULL LIMIT 1"
    )).first():
        raise RuntimeError("Preserve payroll QR closure evidence before downgrade")
    op.drop_constraint("ck_payroll_qr_labels_status", "payroll_qr_labels", type_="check")
    op.create_check_constraint("ck_payroll_qr_labels_status", "payroll_qr_labels",
                               "status IN ('available', 'scanned', 'superseded')")
    op.drop_column("payroll_qr_labels", "closure_details")
    op.drop_column("package_print_runs", "superseded_at")

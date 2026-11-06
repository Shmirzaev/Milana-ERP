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
    if op.get_bind().dialect.name == "postgresql":
        # Preserve every print snapshot. Deletion requires explicit retirement
        # in every historical run, for production and manual packages alike.
        op.execute("""CREATE OR REPLACE FUNCTION protect_printed_package_deletion() RETURNS trigger AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM package_print_run_members m JOIN package_print_runs r ON r.id=m.run_id
                     WHERE m.package_id=OLD.id AND r.deleted_at IS NULL
                       AND NOT r.deleted_package_ids::jsonb @> jsonb_build_array(OLD.id))
          THEN RAISE EXCEPTION 'Retire every printed label before deleting this package'; END IF;
          RETURN OLD;
        END; $$ LANGUAGE plpgsql""")


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
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE OR REPLACE FUNCTION protect_printed_package_deletion() RETURNS trigger AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM package_print_run_members m JOIN package_print_runs r ON r.id=m.run_id
                     WHERE m.package_id=OLD.id AND (OLD.manual_receipt_id IS NULL OR
                       (r.deleted_at IS NULL AND NOT r.deleted_package_ids::jsonb @> jsonb_build_array(OLD.id))))
          THEN RAISE EXCEPTION 'Printed package must have a deleted manual label'; END IF;
          RETURN OLD;
        END; $$ LANGUAGE plpgsql""")

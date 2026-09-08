"""Manual physical receipt evidence and immutable package print-run membership."""
from alembic import op
import sqlalchemy as sa

revision = "0115_package_print_runs"
down_revision = "0114_warehouse_stocktake"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "manual_package_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("receipt_no", sa.String(64), unique=True, nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
    )
    with op.batch_alter_table("packages") as batch:
        batch.add_column(sa.Column("quantity_shortfall", sa.Integer(), server_default="0", nullable=False))
        batch.create_check_constraint("ck_packages_shortfall_nonnegative", "quantity_shortfall >= 0")
        batch.add_column(sa.Column("manual_receipt_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_packages_manual_receipt", "manual_package_receipts", ["manual_receipt_id"], ["id"])
        batch.create_index("ix_packages_manual_receipt_id", ["manual_receipt_id"])
        batch.drop_constraint("ck_packages_source_evidence", type_="check")
        batch.create_check_constraint("ck_packages_source_evidence", "production_order_id IS NOT NULL OR legacy_receipt_id IS NOT NULL OR manual_receipt_id IS NOT NULL")
        batch.create_check_constraint("ck_packages_manual_source", "manual_receipt_id IS NULL OR (production_order_id IS NULL AND legacy_receipt_id IS NULL AND production_batch_id IS NULL AND sales_order_id IS NULL)")
    op.create_table(
        "package_print_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_no", sa.String(64), unique=True, nullable=False),
        sa.Column("code", sa.String(64), unique=True, nullable=False),
        sa.Column("packaging_department_code", sa.String(16), nullable=False),
        sa.Column("package_ids", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("received_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("receipt_location", sa.JSON()),
    )
    op.create_table(
        "package_print_run_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("package_print_runs.id"), nullable=False),
        sa.Column("package_id", sa.Integer(), sa.ForeignKey("packages.id"), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.UniqueConstraint("package_id", name="uq_package_print_run_member_package"),
    )
    op.create_index("ix_package_print_run_members_run_id", "package_print_run_members", ["run_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION reject_package_evidence_change() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Package receipt evidence and print membership are immutable'; END;
        $$ LANGUAGE plpgsql""")
        for table in ("manual_package_receipts", "package_print_run_members"):
            op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_package_evidence_change()")
        op.execute("""CREATE FUNCTION protect_package_print_run() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Print runs are immutable'; END IF;
          IF NEW.run_no IS DISTINCT FROM OLD.run_no OR NEW.code IS DISTINCT FROM OLD.code
             OR NEW.package_ids::text IS DISTINCT FROM OLD.package_ids::text
             OR NEW.packaging_department_code IS DISTINCT FROM OLD.packaging_department_code
             OR NEW.created_by IS DISTINCT FROM OLD.created_by OR NEW.created_at IS DISTINCT FROM OLD.created_at
          THEN RAISE EXCEPTION 'Print run identity is immutable'; END IF;
          IF OLD.received_at IS NOT NULL AND (NEW.received_at IS DISTINCT FROM OLD.received_at
             OR NEW.received_by IS DISTINCT FROM OLD.received_by
             OR NEW.receipt_location::text IS DISTINCT FROM OLD.receipt_location::text)
          THEN RAISE EXCEPTION 'Print run receipt is immutable'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        op.execute("CREATE TRIGGER immutable_package_print_runs BEFORE UPDATE OR DELETE ON package_print_runs FOR EACH ROW EXECUTE FUNCTION protect_package_print_run()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM manual_package_receipts")).scalar():
        raise RuntimeError("Cannot downgrade while manual warehouse receipt evidence exists")
    if op.get_bind().execute(sa.text("SELECT count(*) FROM package_print_runs")).scalar():
        raise RuntimeError("Cannot downgrade while package print-run evidence exists")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER immutable_package_print_runs ON package_print_runs")
        op.execute("DROP FUNCTION protect_package_print_run()")
        for table in ("manual_package_receipts", "package_print_run_members"):
            op.execute(f"DROP TRIGGER immutable_{table} ON {table}")
        op.execute("DROP FUNCTION reject_package_evidence_change()")
    op.drop_table("package_print_run_members")
    op.drop_table("package_print_runs")
    with op.batch_alter_table("packages") as batch:
        batch.drop_constraint("ck_packages_shortfall_nonnegative", type_="check")
        batch.drop_column("quantity_shortfall")
        batch.drop_constraint("ck_packages_manual_source", type_="check")
        batch.drop_constraint("ck_packages_source_evidence", type_="check")
        batch.create_check_constraint("ck_packages_source_evidence", "production_order_id IS NOT NULL OR legacy_receipt_id IS NOT NULL")
        batch.drop_index("ix_packages_manual_receipt_id")
        batch.drop_constraint("fk_packages_manual_receipt", type_="foreignkey")
        batch.drop_column("manual_receipt_id")
    op.drop_table("manual_package_receipts")

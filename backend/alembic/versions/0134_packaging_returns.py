"""Preserve old print manifests while returned packages receive a new print run."""
from alembic import op
import sqlalchemy as sa

revision = "0134_packaging_returns"
down_revision = "0133_storage_customers"
branch_labels = None
depends_on = None

OLD_STATUSES = "'packed', 'handed_over', 'received_in_storage', 'reserved', 'shipped', 'delivered', 'damaged'"


def upgrade():
    op.add_column("package_print_runs", sa.Column("returned_at", sa.DateTime(timezone=True)))
    op.add_column("package_print_runs", sa.Column("returned_by", sa.Integer(), sa.ForeignKey("users.id")))
    op.add_column("package_print_runs", sa.Column("return_reason", sa.String(1000)))
    with op.batch_alter_table("package_print_run_members") as batch:
        batch.drop_constraint("uq_package_print_run_member_package", type_="unique")
        batch.create_unique_constraint("uq_package_print_run_member_run_package", ["run_id", "package_id"])
    with op.batch_alter_table("packages") as batch:
        batch.drop_constraint("ck_packages_status", type_="check")
        batch.create_check_constraint("ck_packages_status", f"status IN ({OLD_STATUSES}, 'returned_to_packaging')")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION protect_package_return() RETURNS trigger AS $$
        BEGIN
          IF OLD.returned_at IS NOT NULL AND (NEW.returned_at IS DISTINCT FROM OLD.returned_at
            OR NEW.returned_by IS DISTINCT FROM OLD.returned_by OR NEW.return_reason IS DISTINCT FROM OLD.return_reason)
          THEN RAISE EXCEPTION 'Package return history is immutable'; END IF;
          IF NEW.returned_at IS NOT NULL AND (NEW.received_at IS NOT NULL OR NEW.returned_by IS NULL OR NEW.return_reason IS NULL)
          THEN RAISE EXCEPTION 'Only unreceived runs may be returned with a reason'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        op.execute("CREATE TRIGGER protect_package_return BEFORE UPDATE ON package_print_runs FOR EACH ROW EXECUTE FUNCTION protect_package_return()")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM package_print_runs WHERE returned_at IS NOT NULL")).scalar():
        raise RuntimeError("Cannot downgrade after a package return; retained manifests require this schema")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER protect_package_return ON package_print_runs")
        op.execute("DROP FUNCTION protect_package_return()")
    with op.batch_alter_table("packages") as batch:
        batch.drop_constraint("ck_packages_status", type_="check")
        batch.create_check_constraint("ck_packages_status", f"status IN ({OLD_STATUSES})")
    with op.batch_alter_table("package_print_run_members") as batch:
        batch.drop_constraint("uq_package_print_run_member_run_package", type_="unique")
        batch.create_unique_constraint("uq_package_print_run_member_package", ["package_id"])
    op.drop_column("package_print_runs", "return_reason")
    op.drop_column("package_print_runs", "returned_by")
    op.drop_column("package_print_runs", "returned_at")

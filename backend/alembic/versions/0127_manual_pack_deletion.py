"""Retain immutable print history when unused manual packs are deleted."""
from alembic import op
import sqlalchemy as sa

revision = "0127_manual_pack_deletion"
down_revision = "0126_payroll_sewing_access"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("package_print_runs", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    # The package ID is historical evidence, not a live-stock reference after deletion.
    fks = sa.inspect(op.get_bind()).get_foreign_keys("package_print_run_members")
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("package_print_run_members", naming_convention=naming) as batch:
        for fk in fks:
            if fk["constrained_columns"] == ["package_id"]:
                batch.drop_constraint(fk["name"] or "fk_package_print_run_members_package_id_packages", type_="foreignkey")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION validate_new_print_member() RETURNS trigger AS $$
        BEGIN
          PERFORM id FROM packages WHERE id = NEW.package_id FOR KEY SHARE;
          IF NOT FOUND THEN RAISE EXCEPTION 'Print member must reference an existing package'; END IF;
          PERFORM id FROM package_print_runs WHERE id = NEW.run_id AND deleted_at IS NULL FOR SHARE;
          IF NOT FOUND THEN RAISE EXCEPTION 'Print run is deleted or missing'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        op.execute("""CREATE TRIGGER validate_new_print_member BEFORE INSERT ON package_print_run_members
            FOR EACH ROW EXECUTE FUNCTION validate_new_print_member()""")
        op.execute("""CREATE FUNCTION protect_printed_package_deletion() RETURNS trigger AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM package_print_run_members m JOIN package_print_runs r ON r.id=m.run_id
                     WHERE m.package_id=OLD.id AND (r.deleted_at IS NULL OR OLD.manual_receipt_id IS NULL))
          THEN RAISE EXCEPTION 'Printed package must belong to a deleted manual receipt'; END IF;
          RETURN OLD;
        END; $$ LANGUAGE plpgsql""")
        op.execute("""CREATE TRIGGER protect_printed_package_deletion BEFORE DELETE ON packages
            FOR EACH ROW EXECUTE FUNCTION protect_printed_package_deletion()""")
        op.execute("""CREATE FUNCTION protect_deleted_print_run() RETURNS trigger AS $$
        BEGIN
          IF OLD.deleted_at IS NOT NULL AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD)
          THEN RAISE EXCEPTION 'Deleted print runs cannot be changed or restored'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        op.execute("""CREATE TRIGGER protect_deleted_print_run BEFORE UPDATE ON package_print_runs
            FOR EACH ROW EXECUTE FUNCTION protect_deleted_print_run()""")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM package_print_runs WHERE deleted_at IS NOT NULL")).scalar():
        raise RuntimeError("Cannot downgrade after manual package deletion; print history must be retained")
    if op.get_bind().dialect.name == "postgresql":
        for table, name in (("package_print_run_members", "validate_new_print_member"),
                            ("packages", "protect_printed_package_deletion"),
                            ("package_print_runs", "protect_deleted_print_run")):
            op.execute(f"DROP TRIGGER {name} ON {table}")
            op.execute(f"DROP FUNCTION {name}()")
    with op.batch_alter_table("package_print_run_members") as batch:
        batch.create_foreign_key("fk_package_print_run_members_package_id_packages", "packages", ["package_id"], ["id"])
    op.drop_column("package_print_runs", "deleted_at")

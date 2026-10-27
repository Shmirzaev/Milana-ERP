"""Retire individual manual labels while retaining immutable shipment evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0128_selected_pack_labels"
down_revision = "0127_manual_pack_deletion"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("package_print_runs", sa.Column("deleted_package_ids", sa.JSON(), nullable=False, server_default="[]"))
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE OR REPLACE FUNCTION protect_printed_package_deletion() RETURNS trigger AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM package_print_run_members m JOIN package_print_runs r ON r.id=m.run_id
                     WHERE m.package_id=OLD.id AND (OLD.manual_receipt_id IS NULL OR
                       (r.deleted_at IS NULL AND NOT r.deleted_package_ids::jsonb @> jsonb_build_array(OLD.id))))
          THEN RAISE EXCEPTION 'Printed package must have a deleted manual label'; END IF;
          RETURN OLD;
        END; $$ LANGUAGE plpgsql""")
        op.execute("""CREATE FUNCTION protect_retired_package_labels() RETURNS trigger AS $$
        BEGIN
          IF NOT NEW.deleted_package_ids::jsonb @> OLD.deleted_package_ids::jsonb
             OR NOT NEW.package_ids::jsonb @> NEW.deleted_package_ids::jsonb
          THEN RAISE EXCEPTION 'Retired labels must remain retired and belong to this run'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        op.execute("""CREATE TRIGGER protect_retired_package_labels BEFORE UPDATE ON package_print_runs
            FOR EACH ROW EXECUTE FUNCTION protect_retired_package_labels()""")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM package_print_runs WHERE CAST(deleted_package_ids AS TEXT) != '[]'")).scalar():
        raise RuntimeError("Cannot downgrade after selected label deletion")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER protect_retired_package_labels ON package_print_runs")
        op.execute("DROP FUNCTION protect_retired_package_labels()")
        op.execute("""CREATE OR REPLACE FUNCTION protect_printed_package_deletion() RETURNS trigger AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM package_print_run_members m JOIN package_print_runs r ON r.id=m.run_id
                     WHERE m.package_id=OLD.id AND (r.deleted_at IS NULL OR OLD.manual_receipt_id IS NULL))
          THEN RAISE EXCEPTION 'Printed package must belong to a deleted manual receipt'; END IF;
          RETURN OLD;
        END; $$ LANGUAGE plpgsql""")
    op.drop_column("package_print_runs", "deleted_package_ids")

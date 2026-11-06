"""Persist the Nastil and actual quantity supplied by a cutting passport."""
from alembic import op
import sqlalchemy as sa

revision = "0141_passport_nastil"
down_revision = "0140_usluga_packaging_nastil"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("production_batches", sa.Column("cutting_passport_id", sa.Integer(), nullable=True))
    op.add_column("production_batches", sa.Column("passport_actual_quantity", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_production_batches_cutting_passport_id_cutting_passports", "production_batches", "cutting_passports", ["cutting_passport_id"], ["id"])
    op.create_unique_constraint("uq_production_batches_cutting_passport_id", "production_batches", ["cutting_passport_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM production_batches WHERE cutting_passport_id IS NOT NULL")).scalar():
        raise RuntimeError("Preserve passport Nastil links before downgrade")
    op.drop_constraint("uq_production_batches_cutting_passport_id", "production_batches", type_="unique")
    op.drop_constraint("fk_production_batches_cutting_passport_id_cutting_passports", "production_batches", type_="foreignkey")
    op.drop_column("production_batches", "passport_actual_quantity")
    op.drop_column("production_batches", "cutting_passport_id")

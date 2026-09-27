"""Record future waste cost currency and batch source without guessing legacy rows."""

from alembic import op
import sqlalchemy as sa


revision = "0136_waste_cost_provenance"
down_revision = "0135_merge_first_grade_audit"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("waste_records") as batch:
        batch.add_column(sa.Column("cost_currency_at_recording", sa.String(3), nullable=True))
        batch.add_column(sa.Column("cost_source_batch_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_waste_records_cost_source_batch_id_stock_batches",
            "stock_batches", ["cost_source_batch_id"], ["id"],
        )


def downgrade():
    recorded_provenance = op.get_bind().execute(sa.text(
        "SELECT 1 FROM waste_records "
        "WHERE cost_currency_at_recording IS NOT NULL "
        "OR cost_source_batch_id IS NOT NULL LIMIT 1"
    )).first()
    if recorded_provenance:
        raise RuntimeError("Refusing to downgrade 0136: recorded waste cost provenance would be lost")
    with op.batch_alter_table("waste_records") as batch:
        batch.drop_constraint("fk_waste_records_cost_source_batch_id_stock_batches", type_="foreignkey")
        batch.drop_column("cost_source_batch_id")
        batch.drop_column("cost_currency_at_recording")

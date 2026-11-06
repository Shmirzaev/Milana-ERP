"""Size confirmations for service packaging and consistent generated Nastil names."""
import re
from alembic import op
import sqlalchemy as sa

revision = "0140_usluga_packaging_nastil"
down_revision = "0139_warehouse_pack_reservations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("work_orders", sa.Column("service_packaging_json", sa.JSON(), nullable=True))
    bind = op.get_bind()
    batches = sa.table("production_batches", sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("batch_index", sa.Integer))
    for row in bind.execute(sa.select(batches.c.id, batches.c.name, batches.c.batch_index)).mappings():
        name = str(row["name"] or "").strip()
        if not name or re.fullmatch(r"(?:Extra\s+)?Batch\s+\d+", name, re.IGNORECASE):
            bind.execute(batches.update().where(batches.c.id == row["id"]).values(name=f'Nastil {row["batch_index"] or 1}'))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM work_orders WHERE service_packaging_json IS NOT NULL")).scalar():
        raise RuntimeError("Preserve service packaging confirmations before downgrade")
    op.drop_column("work_orders", "service_packaging_json")
    # Nastil names are business labels; a downgrade must not erase renamed data.

"""Record packaging size counts without changing Sewing output history."""
from alembic import op
import sqlalchemy as sa

revision = "0145_packaging_size_entry"
down_revision = "0144_passport_meter_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("production_orders", sa.Column("packaging_size_breakdowns", sa.JSON(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text(
        "SELECT 1 FROM production_orders WHERE packaging_size_breakdowns IS NOT NULL LIMIT 1"
    )).first():
        raise RuntimeError("Preserve packaging size evidence before removing its storage")
    op.drop_column("production_orders", "packaging_size_breakdowns")

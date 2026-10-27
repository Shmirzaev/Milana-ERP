"""Store cutting and passport details per selected fabric."""
from alembic import op
import sqlalchemy as sa

revision = "0122_cutting_material_details"
down_revision = "0121_stocktake_scan_snapshot"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cutting_material_usages", sa.Column("details", sa.JSON(), nullable=True))
    op.add_column("cutting_passports", sa.Column("materials", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("cutting_passports", "materials")
    op.drop_column("cutting_material_usages", "details")

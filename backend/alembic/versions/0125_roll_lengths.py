"""Store optional received length for each material roll."""
from alembic import op
import sqlalchemy as sa

revision = "0125_roll_lengths"
down_revision = "0124_material_length"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stock_batches", sa.Column("roll_lengths_m", sa.JSON(), server_default="[]", nullable=False))


def downgrade():
    op.drop_column("stock_batches", "roll_lengths_m")

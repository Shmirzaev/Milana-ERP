"""Remember exact sewing assignment contribution for safe record corrections."""
from alembic import op
import sqlalchemy as sa
revision = "0131_sewing_corrections"
down_revision = "0130_eco_fabric_transfers"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sewing_records", sa.Column("sewing_assignment_id", sa.Integer(), sa.ForeignKey("sewing_assignments.id")))
    op.add_column("sewing_records", sa.Column("assignment_applied_qty", sa.Integer()))
    op.add_column("sewing_records", sa.Column("correction_version", sa.Integer(), server_default="0", nullable=False))


def downgrade():
    op.drop_column("sewing_records", "correction_version")
    op.drop_column("sewing_records", "assignment_applied_qty")
    op.drop_column("sewing_records", "sewing_assignment_id")

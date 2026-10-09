"""Add band account scope and non-production line completion evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0143_sewing_band_access"
down_revision = "0142_package_partial_dispatch"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("sewing_band_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_users_sewing_band", "sewing_flows", ["sewing_band_id"], ["id"])
        batch.create_index("ix_users_sewing_band_id", ["sewing_band_id"])
    op.add_column("sewing_assignments", sa.Column("line_finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sewing_assignments", sa.Column("line_finish_reason", sa.String(255), nullable=True))


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM users WHERE sewing_band_id IS NOT NULL")).scalar():
        raise RuntimeError("Remove band access explicitly before removing its authorization scope")
    if bind.execute(sa.text("SELECT count(*) FROM sewing_assignments WHERE line_finished_at IS NOT NULL")).scalar():
        raise RuntimeError("Preserve line completion evidence before downgrade")
    op.drop_column("sewing_assignments", "line_finish_reason")
    op.drop_column("sewing_assignments", "line_finished_at")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_sewing_band_id")
        batch.drop_constraint("fk_users_sewing_band", type_="foreignkey")
        batch.drop_column("sewing_band_id")

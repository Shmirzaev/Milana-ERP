"""Preserve per-item dispatch totals under the original package identity."""
from alembic import op
import sqlalchemy as sa

revision = "0142_package_partial_dispatch"
down_revision = "0141_passport_nastil"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("packages", sa.Column("dispatched_quantities", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("packages", sa.Column("dispatched_quantity", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("packages") as batch:
        batch.create_check_constraint("ck_packages_dispatch_bounds", "dispatched_quantity >= 0 AND dispatched_quantity <= total_quantity")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM packages WHERE CAST(dispatched_quantities AS text) != '{}' ")).scalar():
        raise RuntimeError("Preserve partial shipment evidence before downgrade")
    with op.batch_alter_table("packages") as batch:
        batch.drop_constraint("ck_packages_dispatch_bounds", type_="check")
    op.drop_column("packages", "dispatched_quantities")
    op.drop_column("packages", "dispatched_quantity")

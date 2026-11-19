"""Store verified closing balance samples for the CEO dashboard."""

from alembic import op
import sqlalchemy as sa


revision = "0159_ceo_balance_snapshots"
down_revision = "0158_ceo_role"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ceo_balance_snapshots",
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("factory", sa.String(3), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("business_date", "factory"),
        sa.CheckConstraint("factory IN ('ALL', 'MIL', 'BST', 'ECO')", name="ck_ceo_snapshot_factory"),
        sa.CheckConstraint("schema_version > 0", name="ck_ceo_snapshot_version"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM ceo_balance_snapshots LIMIT 1")).first():
        raise RuntimeError("CEO balance history exists; preserve it before dropping the snapshot table")
    op.drop_table("ceo_balance_snapshots")

"""Record explicit admin release without changing source orders or stock."""
from alembic import op
import sqlalchemy as sa

revision = "0150_package_customer_release"
down_revision = "0149_besttex_cutting_access"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "package_customer_releases",
        sa.Column("package_id", sa.Integer(), sa.ForeignKey("packages.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_order_ids", sa.JSON(), nullable=False),
        sa.Column("released_quantity", sa.Integer(), nullable=False),
        sa.Column("released_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.CheckConstraint("released_quantity > 0", name="ck_package_customer_release_quantity"),
    )


def downgrade():
    op.drop_table("package_customer_releases")

"""Add a reversible inactive marker for departments."""

from alembic import op
import sqlalchemy as sa


revision = "0132_department_soft_delete"
down_revision = "0131_sewing_corrections"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "departments",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade():
    op.drop_column("departments", "is_active")

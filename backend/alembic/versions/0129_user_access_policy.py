"""Add optional user access overrides without changing existing accounts."""
from alembic import op
import sqlalchemy as sa

revision = "0129_user_access_policy"
down_revision = "0128_selected_pack_labels"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("access_policy", sa.JSON(), nullable=True))


def downgrade():
    connection = op.get_bind()
    configured = connection.execute(sa.text(
        "SELECT COUNT(*) FROM users WHERE access_policy IS NOT NULL "
        "AND CAST(access_policy AS TEXT) NOT IN ('{}', 'null')"
    )).scalar_one()
    if configured:
        raise RuntimeError("Restore backed-up access settings before removing access policies")
    op.drop_column("users", "access_policy")

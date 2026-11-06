"""Grant Payroll access to sewing flows, factory work and bundle scanning."""
from alembic import op
import sqlalchemy as sa

revision = "0126_payroll_sewing_access"
down_revision = "0125_roll_lengths"
branch_labels = None
depends_on = None

_GRANTS = ("sewing.flows", "sewing.records", "sewing.bundles")


def upgrade():
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("permissions", sa.JSON))
    connection = op.get_bind()
    for row in connection.execute(sa.select(roles).where(sa.func.lower(roles.c.name) == "payroll")).mappings():
        permissions = list(row["permissions"] or [])
        added = [permission for permission in _GRANTS if permission not in permissions]
        if added:
            connection.execute(roles.update().where(roles.c.id == row["id"]).values(permissions=permissions + added))


def downgrade():
    # Existing/manual grants cannot be distinguished from migration additions.
    # Keep access on schema rollback; revoke permissions through a reviewed change.
    pass

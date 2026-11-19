"""Provision the reserved CEO role without granting it to existing accounts.

Revision ID: 0158_ceo_role
Revises: 0157_package_allocation_items
"""
from alembic import op
import sqlalchemy as sa

revision = "0158_ceo_role"
down_revision = "0157_package_allocation_items"
branch_labels = None
depends_on = None

roles = sa.table(
    "roles", sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("permissions", sa.JSON),
)
users = sa.table("users", sa.column("role_id", sa.Integer))


def upgrade():
    bind = op.get_bind()
    existing = bind.execute(sa.select(roles.c.id, roles.c.permissions).where(roles.c.name == "CEO")).one_or_none()
    if existing is None:
        bind.execute(roles.insert().values(name="CEO", permissions=[]))
        return
    if existing.permissions or bind.execute(sa.select(users.c.role_id).where(users.c.role_id == existing.id).limit(1)).first():
        raise RuntimeError("Existing CEO role has grants or assignments. Reconcile it before enabling CEO access.")


def downgrade():
    bind = op.get_bind()
    assigned = sa.select(users.c.role_id).where(users.c.role_id == roles.c.id).exists()
    if bind.execute(sa.select(roles.c.id).where(roles.c.name == "CEO", assigned)).first():
        raise RuntimeError("Remove CEO role assignments before downgrading its access controls.")
    bind.execute(roles.delete().where(roles.c.name == "CEO"))

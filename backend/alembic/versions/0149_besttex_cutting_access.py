"""Provision only the owner's named Besttex cutting-sheet reader.

No role, operational edit capability, factory assignment or table shape changes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0149_besttex_cutting_access"
down_revision = "0148_second_grade_packages"
branch_labels = None
depends_on = None


def upgrade():
    users = sa.table("users", sa.column("id", sa.Integer), sa.column("email", sa.String),
                     sa.column("factory_code", sa.String), sa.column("extra_permissions", sa.JSON),
                     sa.column("access_policy", sa.JSON))
    connection = op.get_bind()
    rows = connection.execute(sa.select(users).where(
        sa.func.lower(users.c.email) == "besttex@milanapremium.uz",
    ).with_for_update()).mappings().all()
    if len(rows) > 1:
        raise RuntimeError("Besttex account is ambiguous; review access before migrating")
    for row in rows:
        permission = "besttex.cutting_sheets"
        token = permission if row["factory_code"] == "BST" else f"factory:BST:{permission}"
        extra = list(row["extra_permissions"] or [])
        if token not in extra:
            extra.append(token)
        policy = dict(row["access_policy"] or {})
        if "BST" in policy:
            existing = policy["BST"]
            policy["BST"] = {**existing, "allow": list(dict.fromkeys([*existing.get("allow", []), permission])),
                             "deny": [key for key in existing.get("deny", []) if key != permission]}
        connection.execute(users.update().where(users.c.id == row["id"]).values(
            extra_permissions=extra, access_policy=policy or row["access_policy"],
        ))


def downgrade():
    # Do not revoke a potentially human-reaffirmed permission automatically.
    # Administrators can revoke this one capability through the audited Users UI.
    pass

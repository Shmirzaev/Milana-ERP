"""Bind users and login sessions to an operating factory."""

from alembic import op
import sqlalchemy as sa

revision = "0090_user_factory_access"
down_revision = "0089_packaging_departments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("factory_code", sa.String(length=3), nullable=True))
    op.execute("""
        UPDATE users AS u SET factory_code = CASE
            WHEN d.code IN ('BST', 'BPK') THEN 'BST'
            WHEN d.code IN ('ECT', 'ECO', 'ECP') THEN 'ECO'
            ELSE 'MIL' END
        FROM departments AS d WHERE d.id = u.department_id
    """)
    op.execute("UPDATE users SET factory_code = 'MIL' WHERE factory_code IS NULL")
    op.alter_column("users", "factory_code", nullable=False, server_default="MIL")
    op.create_check_constraint("ck_users_factory_code", "users", "factory_code IN ('MIL', 'BST', 'ECO')")
    op.create_index("ix_users_factory_code", "users", ["factory_code"])


def downgrade() -> None:
    op.drop_index("ix_users_factory_code", table_name="users")
    op.drop_constraint("ck_users_factory_code", "users", type_="check")
    op.drop_column("users", "factory_code")

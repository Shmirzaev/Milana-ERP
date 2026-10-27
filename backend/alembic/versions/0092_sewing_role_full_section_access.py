"""Grant the Sewing role complete access to the sewing section."""

from alembic import op


revision = "0092_sewing_role_access"
down_revision = "0091_payroll_workspace_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE roles
        SET permissions = '["sewing.workspace", "sewing.records", "sewing.bundles", "sewing.flows", "traceability.view"]'
        WHERE lower(name) = 'sewing'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE roles
        SET permissions = '["sewing.workspace", "sewing.records", "sewing.bundles", "traceability.view"]'
        WHERE lower(name) = 'sewing'
    """)

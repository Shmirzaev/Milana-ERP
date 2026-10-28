"""Grant the Payroll role access to the complete payroll workspace."""

from alembic import op


revision = "0091_payroll_workspace_access"
down_revision = "0090_user_factory_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE roles
        SET permissions = '["payroll.view", "payroll.manage", "payroll.scan", "sewing.daily_reports.view"]'
        WHERE lower(name) = 'payroll'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE roles
        SET permissions = '["payroll.scan", "sewing.daily_reports.view"]'
        WHERE lower(name) = 'payroll'
    """)

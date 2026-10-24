"""Add the dashboard-only top/bottom piece multiplier to cutting passports."""
from alembic import op
import sqlalchemy as sa

revision = "0147_passport_tepa_pass"
down_revision = "0146_payroll_qr_closure"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cutting_passports", sa.Column("tepa_pass", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("cutting_passports", "tepa_pass")

"""Allow second-grade packages without reclassifying existing stock."""
from alembic import op
import sqlalchemy as sa

revision = "0148_second_grade_packages"
down_revision = "0147_passport_tepa_pass"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_packages_stock_kind", "packages", type_="check")
    op.create_check_constraint("ck_packages_stock_kind", "packages",
                               "stock_kind IN ('standard', 'first_grade', 'second_grade')")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM packages WHERE stock_kind = 'second_grade' LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while second-grade packages exist")
    op.drop_constraint("ck_packages_stock_kind", "packages", type_="check")
    op.create_check_constraint("ck_packages_stock_kind", "packages",
                               "stock_kind IN ('standard', 'first_grade')")

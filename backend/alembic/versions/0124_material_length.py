"""Store optional total received material length in metres."""
from alembic import op
import sqlalchemy as sa

revision = "0124_material_length"
down_revision = "0123_fabric_scan_register"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stock_batches", sa.Column("length_m", sa.Numeric(14, 3), nullable=True))
    op.add_column("cutting_records", sa.Column("cutting_passport_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_cutting_record_passport", "cutting_records", "cutting_passports", ["cutting_passport_id"], ["id"])
    op.create_index("ix_cutting_records_cutting_passport_id", "cutting_records", ["cutting_passport_id"])


def downgrade():
    op.drop_index("ix_cutting_records_cutting_passport_id", table_name="cutting_records")
    op.drop_constraint("fk_cutting_record_passport", "cutting_records", type_="foreignkey")
    op.drop_column("cutting_records", "cutting_passport_id")
    op.drop_column("stock_batches", "length_m")

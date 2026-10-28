"""Persist opt-in metre calculations for cutting passports."""
import json
from alembic import op
import sqlalchemy as sa

revision = "0144_passport_meter_mode"
down_revision = "0143_sewing_band_access"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cutting_passports", sa.Column("meter_mode", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    rows = op.get_bind().execute(sa.text("SELECT meter_mode, materials FROM cutting_passports"))
    for mode, materials in rows:
        if isinstance(materials, str):
            materials = json.loads(materials)
        if mode or any(row.get("meter_mode") for row in (materials or [])):
            raise RuntimeError("Preserve metre passport quantities before removing their unit")
    op.drop_column("cutting_passports", "meter_mode")

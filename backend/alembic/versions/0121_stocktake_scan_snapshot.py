"""Retain package/model quantities observed at the first stocktake scan."""
from alembic import op
import sqlalchemy as sa

revision = "0121_stocktake_scan_snapshot"
down_revision = "0120_canonical_bundle_references"
branch_labels = None
depends_on = None


def upgrade():
    # Historic scan-time quantities cannot be reconstructed from today's stock.
    op.add_column("warehouse_stocktake_rows", sa.Column("scan_snapshot", sa.JSON(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text(
        "SELECT count(*) FROM warehouse_stocktake_rows WHERE scan_snapshot IS NOT NULL "
        "AND CAST(scan_snapshot AS TEXT) <> 'null'"
    )).scalar():
        raise RuntimeError("Preserve recorded stocktake scan evidence; downgrade requires a reviewed backup")
    op.drop_column("warehouse_stocktake_rows", "scan_snapshot")

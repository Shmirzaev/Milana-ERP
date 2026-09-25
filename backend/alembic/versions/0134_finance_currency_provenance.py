"""Keep transaction currency provenance without guessing legacy amounts."""

from alembic import op
import sqlalchemy as sa


revision = "0134_finance_currency_provenance"
down_revision = "0133_movement_cost_snapshot"
branch_labels = None
depends_on = None


def upgrade():
    for table, column in (
        ("sales_orders", "currency"),
        ("invoices", "currency"),
        ("payments", "currency"),
        ("stock_batches", "cost_currency"),
        ("stock_movements", "cost_currency_at_movement"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(column, sa.String(3), nullable=True))


def downgrade():
    for table, column in (
        ("stock_movements", "cost_currency_at_movement"),
        ("stock_batches", "cost_currency"),
        ("payments", "currency"),
        ("invoices", "currency"),
        ("sales_orders", "currency"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column)

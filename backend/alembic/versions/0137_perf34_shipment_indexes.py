"""PERF34: index the shipment document's package-content and price lists.

``shipment_document`` loads the contents of every package in a shipment with
``WHERE package_items.package_id IN (...)`` and the order's price list with
``WHERE sales_order_items.sales_order_id = ?``. Neither column carried an index,
so both reads were a sequential scan of the whole table on every document build,
in addition to the repeated in-memory rescans removed alongside this revision.

These are plain btree indexes on the two filtered columns. They change no query
text, no ordering and no row set, so a frozen dispatch document still renders
from the same snapshot it was frozen with.

The revision id stays inside the 32 characters ``alembic_version.version_num``
allows, like every other revision in this chain.
"""
from alembic import op

revision = "0137_perf34_shipment_indexes"
down_revision = "0136_employee_salary_precision"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_package_items_package_id", "package_items", ["package_id"])
    op.create_index("ix_sales_order_items_sales_order_id", "sales_order_items", ["sales_order_id"])


def downgrade():
    op.drop_index("ix_sales_order_items_sales_order_id", "sales_order_items")
    op.drop_index("ix_package_items_package_id", "package_items")

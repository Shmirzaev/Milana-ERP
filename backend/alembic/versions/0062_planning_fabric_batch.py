"""move fabric batch choice from models to production planning

Revision ID: 0062_planning_fabric_batch
Revises: 0061_production_order_brand
Create Date: 2026-07-17
"""

from copy import deepcopy

from alembic import op
import sqlalchemy as sa


revision = "0062_planning_fabric_batch"
down_revision = "0061_production_order_brand"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "production_orders",
        sa.Column("fabric_batch_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_production_orders_fabric_batch_id_stock_batches",
        "production_orders",
        "stock_batches",
        ["fabric_batch_id"],
        ["id"],
    )
    op.create_index(
        "ix_production_orders_fabric_batch_id",
        "production_orders",
        ["fabric_batch_id"],
    )

    connection = op.get_bind()
    fabric_rows = connection.execute(sa.text("""
        SELECT mb.model_id, mb.item_id, i.name, i.sku
        FROM model_bom AS mb
        JOIN items AS i ON i.id = mb.item_id
        WHERE i.category IN ('fabric', 'semi_finished')
        ORDER BY mb.id
    """)).mappings().all()
    first_fabric_by_model = {}
    for row in fabric_rows:
        first_fabric_by_model.setdefault(int(row["model_id"]), row)

    models_table = sa.table(
        "models",
        sa.column("id", sa.Integer()),
        sa.column("details_json", sa.JSON()),
    )
    model_rows = connection.execute(
        sa.select(models_table.c.id, models_table.c.details_json)
    ).mappings().all()
    for model_row in model_rows:
        fabric_row = first_fabric_by_model.get(int(model_row["id"]))
        details = deepcopy(model_row["details_json"] or {})
        if not isinstance(details, dict):
            continue
        general = details.get("general")
        if not isinstance(general, dict):
            general = {}
        changed = general.pop("variant_stock_batch_id", None) is not None
        if fabric_row:
            item_id = int(fabric_row["item_id"])
            label = str(fabric_row["name"] or fabric_row["sku"] or "").strip()
            if str(fabric_row["name"] or "").strip() and str(fabric_row["sku"] or "").strip():
                label = f"{fabric_row['name']} ({fabric_row['sku']})"
            if general.get("variant_fabric_item_id") != item_id:
                general["variant_fabric_item_id"] = item_id
                changed = True
            if label and general.get("variant_fabric") != label:
                general["variant_fabric"] = label
                changed = True
        if changed:
            details["general"] = general
            connection.execute(
                models_table.update()
                .where(models_table.c.id == int(model_row["id"]))
                .values(details_json=details)
            )

    connection.execute(sa.text("""
        UPDATE model_bom AS mb
        SET stock_batch_id = NULL,
            photo_url = i.image_url
        FROM items AS i
        WHERE i.id = mb.item_id
          AND i.category IN ('fabric', 'semi_finished')
    """))


def downgrade():
    # Model-to-batch links are intentionally not restored: a model defines a
    # fabric type, while physical batch selection belongs to production.
    op.drop_index("ix_production_orders_fabric_batch_id", table_name="production_orders")
    op.drop_constraint(
        "fk_production_orders_fabric_batch_id_stock_batches",
        "production_orders",
        type_="foreignkey",
    )
    op.drop_column("production_orders", "fabric_batch_id")

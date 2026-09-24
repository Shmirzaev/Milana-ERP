from __future__ import annotations

import json

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, MetaData, String, Table, create_engine, insert, select

from app.migrations.preflight_0107 import (
    PREDECESSOR_0107,
    REVISION_0107,
    TARGET_PERMISSION_0107,
    read_only_preflight_0107,
)


def _engine(revision: str = PREDECESSOR_0107):
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table("alembic_version", metadata, Column("version_num", String, primary_key=True))
    models = Table("models", metadata,
                   Column("id", Integer, primary_key=True), Column("catalog_scope", String))
    items = Table("items", metadata, Column("id", Integer, primary_key=True),
                  Column("name", String), Column("sku", String), Column("category", String))
    bom = Table("model_bom", metadata, Column("id", Integer, primary_key=True),
                Column("model_id", ForeignKey("models.id")), Column("item_id", ForeignKey("items.id")),
                Column("stock_batch_id", Integer), Column("material_name", String))
    Table("bundles", metadata, Column("id", Integer, primary_key=True),
          Column("production_order_id", Integer), Column("production_batch_id", Integer))
    Table("work_orders", metadata, Column("id", Integer, primary_key=True),
          Column("production_order_id", Integer), Column("operation", String))
    Table("cutting_records", metadata, Column("id", Integer, primary_key=True),
          Column("work_order_id", Integer), Column("production_batch_id", Integer))
    roles = Table("roles", metadata, Column("id", Integer, primary_key=True),
                  Column("name", String), Column("permissions", JSON), Column("updated_at", DateTime))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(metadata.tables["alembic_version"]), {"version_num": revision})
        connection.execute(insert(models), [
            {"id": 1, "catalog_scope": "usluga"}, {"id": 2, "catalog_scope": "standard"},
        ])
        connection.execute(insert(items), [
            {"id": 1, "name": " Fabric ", "sku": "F-1", "category": "FABRIC"},
            {"id": 2, "name": None, "sku": "SKU-2", "category": "semi_finished"},
            {"id": 3, "name": "Trim", "sku": "T-3", "category": "accessory"},
        ])
        connection.execute(insert(bom), [
            {"id": 10, "model_id": 1, "item_id": 1, "stock_batch_id": 44, "material_name": None},
            {"id": 11, "model_id": 1, "item_id": None, "stock_batch_id": None,
             "material_name": "Manual fabric"},
            {"id": 12, "model_id": 1, "item_id": 2, "stock_batch_id": 45, "material_name": None},
            {"id": 13, "model_id": 2, "item_id": 3, "stock_batch_id": None, "material_name": None},
        ])
        bundles = metadata.tables["bundles"]
        work_orders = metadata.tables["work_orders"]
        cutting_records = metadata.tables["cutting_records"]
        connection.execute(insert(bundles), [
            {"id": 100, "production_order_id": 1, "production_batch_id": 3},
            {"id": 101, "production_order_id": 2, "production_batch_id": 4},
            {"id": 102, "production_order_id": 3, "production_batch_id": 5},
        ])
        connection.execute(insert(work_orders), [
            {"id": 1, "production_order_id": 1, "operation": "cutting"},
            {"id": 2, "production_order_id": 2, "operation": "cutting"},
        ])
        connection.execute(insert(cutting_records), [
            {"id": 21, "work_order_id": 1, "production_batch_id": 3},
            {"id": 22, "work_order_id": 2, "production_batch_id": 4},
            {"id": 23, "work_order_id": 2, "production_batch_id": 4},
        ])
        connection.execute(insert(roles), [
            {"id": 7, "name": "Eco Cotton Usluga", "permissions": ["usluga.view"],
             "updated_at": None},
            {"id": 8, "name": "eco cotton usluga",
             "permissions": ["usluga.view", TARGET_PERMISSION_0107], "updated_at": None},
        ])
    return engine


def test_0107_preflight_snapshots_only_matching_rows_and_keeps_ambiguous_links_unlinked():
    engine = _engine()
    report = read_only_preflight_0107(engine)

    assert report["revision"] == REVISION_0107
    assert report["applicability"] == "manual_review_required"
    fabrics = report["usluga_fabric_inventory_links"]
    assert fabrics["ids"] == [10, 12]
    assert fabrics["count"] == 2
    assert fabrics["restoration_rows"][0]["before"] == {
        "item_id": 1, "stock_batch_id": 44, "material_name": None,
    }
    assert fabrics["restoration_rows"][0]["after"]["material_name"] == "Fabric"
    assert fabrics["restoration_rows"][1]["after"]["material_name"] == "SKU-2"
    assert len(fabrics["snapshot_sha256"]) == 64

    ranked = report["usluga_material_roles"]
    assert [(row["id"], row["material_role_after"]) for row in ranked["rows"]] == [
        (10, "main"), (11, "secondary"), (12, "secondary"),
    ]
    links = report["bundle_cutting_record_links"]
    assert links["auto_links"] == [{
        "bundle_id": 100, "production_order_id": 1, "production_batch_id": 3,
        "cutting_record_id_after": 21,
    }]
    assert links["ambiguous_bundles"] == [{
        "bundle_id": 101, "production_order_id": 2, "production_batch_id": 4,
        "cutting_record_ids": [22, 23],
    }]
    assert links["no_match_count"] == 1
    roles = report["eco_cotton_usluga_role"]["roles"]
    assert roles[0]["restoration_snapshot"]["permissions"] == ["usluga.view"]
    assert roles[0]["after_permissions"] == ["usluga.view", TARGET_PERMISSION_0107]
    assert roles[1]["changed"] is False

    # The preview is read-only: the source JSON and BOM pointers remain intact.
    with engine.connect() as connection:
        metadata = MetaData()
        bom = Table("model_bom", metadata, autoload_with=connection)
        roles_table = Table("roles", metadata, autoload_with=connection)
        source_bom = connection.execute(select(bom).order_by(bom.c.id)).mappings().all()
        source_roles = connection.execute(select(roles_table).order_by(roles_table.c.id)).mappings().all()
    assert source_bom[0]["item_id"] == 1
    assert source_roles[0]["permissions"] == ["usluga.view"]
    engine.dispose()


def test_0107_preflight_fails_closed_before_inspecting_rows_on_revision_mismatch():
    engine = _engine("0107_usluga_cutting_approval")
    report = read_only_preflight_0107(engine)

    assert report["applicability"] == "revision_mismatch_review_required"
    assert report["affected_rows_inspected"] is False
    assert report["database_revisions"] == [REVISION_0107]
    assert "restoration_rows" not in report
    engine.dispose()


def test_0107_role_permission_hash_is_repeatable_and_report_excludes_notes_and_pii():
    engine = _engine()
    first = read_only_preflight_0107(engine)
    second = read_only_preflight_0107(engine)

    assert first["eco_cotton_usluga_role"]["snapshot_sha256"] == second[
        "eco_cotton_usluga_role"]["snapshot_sha256"]
    serialized = json.dumps(first, sort_keys=True)
    assert "email" not in serialized.lower()
    assert "notes" not in serialized.lower()
    assert first["eco_cotton_usluga_role"]["matching_role_count"] == 2
    engine.dispose()

import csv
import importlib.util
import io
import json
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, text

from app.db.session import SessionLocal
from app.models import Model, Package, PackageItem
from app.models.stocktake import WarehouseStocktakeRow
from app.tests.test_warehouse_stocktake import BASE, business_fingerprint, detail, scan, start
from app.tests.test_warehouse_stocktake import packs as packs


def exported(client, headers, cid):
    response = client.get(f"{BASE}/{cid}/export.csv", headers=headers)
    assert response.status_code == 200
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_first_scan_keeps_quantity_and_mixed_model_sizes_through_duplicates_and_completion(client, auth_headers, packs):
    cid = start(client, auth_headers)
    with SessionLocal() as db:
        other = Model(code="ST-MIXED", name="Second model")
        db.add(other)
        db.flush()
        package = db.get(Package, packs[0])
        package.total_quantity = 40
        db.add_all([
            PackageItem(package_id=package.id, model_id=package.model_id, color="BLUE", size="M", quantity=15),
            PackageItem(package_id=package.id, model_id=other.id, color="RED", size="L", quantity=25),
        ])
        db.commit()
    first = scan(client, auth_headers, cid, "COUNT-0")["row"]
    assert first["snapshot"]["quantity"] == 60
    assert first["scanned_pieces"] == first["scan_snapshot"]["quantity"] == 40
    assert first["scan_evidence_source"] == "scan"
    items = first["scan_snapshot"]["items"]
    assert [(row["size"], row["quantity"]) for row in items] == [("M", 15), ("L", 25)]
    assert items[1]["model_code"] == "ST-MIXED"
    assert items[1]["model_name"] == "Second model"
    with SessionLocal() as db:
        db.get(Package, packs[0]).total_quantity = 12
        db.query(PackageItem).filter_by(package_id=packs[0], size="L").update({"quantity": 2})
        db.commit()
    before_count_actions = business_fingerprint()
    duplicate = scan(client, auth_headers, cid, "OLD-UNIQUE")
    assert duplicate["duplicate"]
    assert duplicate["row"]["scan_snapshot"] == first["scan_snapshot"]
    assert duplicate["row"]["scanned_at"] == first["scanned_at"]
    assert duplicate["row"]["current"]["quantity"] == 12
    assert client.post(f"{BASE}/{cid}/complete", headers=auth_headers).status_code == 200
    frozen = detail(client, auth_headers, cid)
    assert frozen["summary"]["scanned_packages"] == 1 and frozen["summary"]["scanned_pieces"] == 40
    assert business_fingerprint() == before_count_actions
    report = exported(client, auth_headers, cid)
    scanned_row = next(row for row in report if row["Package"] == "COUNT-0")
    assert scanned_row["Expected pieces"] == "60" and scanned_row["Current pieces"] == "12"
    assert scanned_row["Scanned pieces"] == "40" and scanned_row["Scan quantity basis"] == "scan"
    assert "ST-MIXED / Second model / RED / L : 25" in scanned_row["Scanned model / color / size breakdown"]
    assert report[-1]["Scanned pieces total"] == "40"
    with SessionLocal() as db:
        db.get(Package, packs[0]).total_quantity = 1
        db.commit()
    assert detail(client, auth_headers, cid) == frozen
    assert exported(client, auth_headers, cid) == report


def test_legacy_scans_disclose_count_start_fallback_never_backfill_from_current_stock(client, auth_headers, packs):
    cid = start(client, auth_headers)
    expected = scan(client, auth_headers, cid, "COUNT-0")["row"]
    unexpected = scan(client, auth_headers, cid, "COUNT-3")["row"]
    with SessionLocal() as db:
        for row_id in (expected["id"], unexpected["id"]):
            db.get(WarehouseStocktakeRow, row_id).scan_snapshot = None  # Existing rows after additive migration.
        db.get(Package, packs[0]).total_quantity = 7
        db.get(Package, packs[3]).total_quantity = 8
        db.commit()
    duplicate = scan(client, auth_headers, cid, "COUNT-0")
    assert duplicate["duplicate"] and duplicate["row"]["scan_snapshot"] is None
    assert duplicate["row"]["scan_evidence_source"] == "count_start"
    assert duplicate["row"]["scanned_pieces"] == 60
    rows = detail(client, auth_headers, cid, "?result=scanned")
    legacy_unexpected = next(row for row in rows["rows"] if row["id"] == unexpected["id"])
    assert legacy_unexpected["scan_evidence_source"] == "scan" and legacy_unexpected["scanned_pieces"] == 60
    assert rows["summary"]["scanned_packages"] == 2
    assert rows["summary"]["scanned_pieces"] == 120 and rows["summary"]["estimated_packages"] == 1
    report = exported(client, auth_headers, cid)
    assert report[-1]["Count-start fallback packages"] == "1"
    assert report[-1]["Scanned pieces total"] == "120"


def test_saved_history_totals_ignore_filters_pages_unresolved_and_duplicate_labels(client, auth_headers, packs):
    before = business_fingerprint()
    cid, other = start(client, auth_headers), start(client, auth_headers)
    first = scan(client, auth_headers, cid, "OLD-UNIQUE")
    scan(client, auth_headers, cid, "COUNT-1")
    scan(client, auth_headers, cid, "COUNT-3")
    last = scan(client, auth_headers, cid, "UNKNOWN")
    scan(client, auth_headers, cid, "OLD-SHARED")
    scan(client, auth_headers, cid, "PACKAGE:COUNT-0|COUNT-QR-0")
    scan(client, auth_headers, cid, "UNKNOWN")
    only_missing = detail(client, auth_headers, cid, "?result=missing&limit=1&offset=999")
    assert not only_missing["rows"]
    summary = only_missing["summary"]
    assert summary["scanned"] == 5 and summary["scanned_packages"] == 3
    assert summary["scanned_pieces"] == 180
    assert summary["unknown"] == summary["ambiguous"] == 1
    assert summary["estimated_packages"] == summary["unquantified_packages"] == 0
    one = detail(client, auth_headers, cid, "?result=scanned&limit=1&offset=1")
    assert one["total"] == 5 and one["rows"][0]["id"] == last["row"]["id"]
    assert one["summary"] == summary
    all_history = detail(client, auth_headers, cid, "?result=scanned")
    assert all_history["rows"][-1]["id"] == first["row"]["id"]
    assert all(row["scanned_at"] for row in all_history["rows"])
    listed = client.get(BASE, headers=auth_headers).json()["items"]
    mine = next(row for row in listed if row["id"] == cid)["summary"]
    empty = next(row for row in listed if row["id"] == other)["summary"]
    assert mine["scanned_packages"] == 3 and mine["scanned_pieces"] == 180
    assert empty["scanned_packages"] == empty["scanned_pieces"] == 0
    report = exported(client, auth_headers, cid)
    assert report[-1]["Scanned packages total"] == "3" and report[-1]["Scanned pieces total"] == "180"
    assert report[-1]["Unknown labels total"] == report[-1]["Ambiguous labels total"] == "1"
    assert business_fingerprint() == before


def test_undo_clears_first_scan_evidence_and_rescan_captures_new_quantity(client, auth_headers, packs):
    cid = start(client, auth_headers)
    first = scan(client, auth_headers, cid, "COUNT-0")["row"]
    assert client.delete(f"{BASE}/{cid}/scans/{first['id']}", headers=auth_headers).status_code == 200
    with SessionLocal() as db:
        saved = db.get(WarehouseStocktakeRow, first["id"])
        assert saved.scan_snapshot is None and saved.snapshot["quantity"] == 60
        db.get(Package, packs[0]).total_quantity = 22
        db.commit()
    result = scan(client, auth_headers, cid, "COUNT-0")
    assert not result["duplicate"] and result["row"]["scanned_pieces"] == 22
    assert result["row"]["snapshot"]["quantity"] == 60
    assert detail(client, auth_headers, cid)["summary"]["scanned_pieces"] == 22


def test_mixed_direct_and_other_package_alias_is_ambiguous_and_not_counted(client, auth_headers, packs):
    cid = start(client, auth_headers)
    scanned = scan(client, auth_headers, cid, "PACKAGE:COUNT-1|OLD-UNIQUE")
    assert scanned["row"]["result"] == "ambiguous" and scanned["row"]["scanned_pieces"] is None
    summary = detail(client, auth_headers, cid)["summary"]
    assert summary["scanned_packages"] == summary["scanned_pieces"] == 0


def test_disappeared_package_after_resolution_is_unresolved_not_a_counted_pack(client, auth_headers, packs, monkeypatch):
    from app.api.routes import stocktake

    cid = start(client, auth_headers)
    monkeypatch.setattr(stocktake, "resolve_package", lambda db, code: (2147483647, False))
    scanned = scan(client, auth_headers, cid, "DELETED-BETWEEN-RESOLVE-AND-LOCK")["row"]
    assert scanned["package_id"] is None and scanned["result"] == "unknown"
    assert scanned["scanned_pieces"] is None
    assert detail(client, auth_headers, cid)["summary"]["scanned_packages"] == 0


def test_folder_totals_use_one_batched_scan_query_without_current_stock_queries(client, auth_headers, packs):
    from app.db.session import engine

    for _ in range(6):
        cid = start(client, auth_headers)
        scan(client, auth_headers, cid, "COUNT-0")
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get(BASE, headers=auth_headers)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 6
    assert all(row["summary"]["scanned_pieces"] == 60 for row in response.json()["items"])
    assert sum("from warehouse_stocktake_rows" in statement for statement in statements) == 1
    assert not any("from packages" in statement or "from finished_goods_stock" in statement for statement in statements)


def test_scan_snapshot_migration_preserves_old_snapshots_and_does_not_invent_scan_evidence():
    path = Path(__file__).parents[2] / "alembic/versions/0121_stocktake_scan_snapshot.py"
    spec = importlib.util.spec_from_file_location("scan_snapshot_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE warehouse_stocktake_rows (id INTEGER PRIMARY KEY, snapshot JSON, final_snapshot JSON)"))
        connection.execute(text("INSERT INTO warehouse_stocktake_rows VALUES (1, :start, :final)"),
                           {"start": json.dumps({"quantity": 60}), "final": json.dumps({"quantity": 40})})
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            row = connection.execute(text("SELECT * FROM warehouse_stocktake_rows")).mappings().one()
            assert row["scan_snapshot"] is None
            assert json.loads(row["snapshot"]) == {"quantity": 60}
            assert json.loads(row["final_snapshot"]) == {"quantity": 40}
            migration.downgrade()
            migration.upgrade()
            connection.execute(text("UPDATE warehouse_stocktake_rows SET scan_snapshot=:scan"), {"scan": '{"quantity":50}'})
            with pytest.raises(RuntimeError, match="Preserve recorded"):
                migration.downgrade()
    engine.dispose()

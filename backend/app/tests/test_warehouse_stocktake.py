import csv
import io
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AuditLog, FinishedGoodsStock, LegacyStockReceipt, Model, Package, PackageBarcodeAlias

BASE = "/api/warehouse-stocktakes"


@pytest.fixture
def packs():
    with SessionLocal() as db:
        model = db.query(Model).first()
        result = []
        for n, status in enumerate(("received_in_storage", "reserved", "damaged", "packed", "shipped", "delivered")):
            receipt = LegacyStockReceipt(
                source_system="COUNT_TEST",
                source_warehouse_id="1",
                source_record_id=str(n),
                source_checksum="0" * 64,
                source_payload={},
            )
            db.add(receipt)
            db.flush()
            pack = Package(
                package_no=f"COUNT-{n}",
                barcode=f"COUNT-QR-{n}",
                legacy_receipt_id=receipt.id,
                model_id=model.id,
                color="BLUE",
                total_quantity=60,
                capacity=60,
                status=status,
            )
            db.add(pack)
            db.flush()
            db.add(
                FinishedGoodsStock(
                    package_id=pack.id,
                    model_id=model.id,
                    color="BLUE",
                    size="M",
                    quantity=60,
                    available_qty=0 if n == 1 else 60,
                    reserved_qty=60 if n == 1 else 0,
                )
            )
            result.append(pack.id)
        db.add_all(
            [
                PackageBarcodeAlias(package_id=result[0], code="OLD-UNIQUE", code_type="legacy"),
                PackageBarcodeAlias(package_id=result[0], code="OLD-SHARED", code_type="legacy"),
                PackageBarcodeAlias(package_id=result[1], code="OLD-SHARED", code_type="legacy"),
            ]
        )
        db.commit()
        return result


def start(client, headers, **body):
    response = client.post(
        BASE, headers=headers, json={"title": "Whole warehouse", "request_key": str(uuid4()), **body}
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def scan(client, headers, cid, code):
    response = client.post(f"{BASE}/{cid}/scan", headers=headers, json={"code": code})
    assert response.status_code == 200, response.text
    return response.json()


def detail(client, headers, cid, suffix=""):
    response = client.get(f"{BASE}/{cid}{suffix}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def business_fingerprint():
    with SessionLocal() as db:
        return [
            db.execute(select(table)).all()
            for table in [Package.__table__, FinishedGoodsStock.__table__, LegacyStockReceipt.__table__]
        ]


def test_full_count_unknown_missing_duplicates_completion_and_no_stock_mutation(client, auth_headers, packs):
    before = business_fingerprint()
    cid = start(client, auth_headers)
    initial = detail(client, auth_headers, cid)
    expected_ids = {row["package_id"] for row in initial["rows"]}
    assert set(packs[:3]) <= expected_ids
    assert not expected_ids.intersection(packs[3:])
    first = scan(client, auth_headers, cid, "  PACKAGE:COUNT-0|COUNT-QR-0  ")
    assert first["row"]["result"] == "found" and not first["duplicate"]
    assert scan(client, auth_headers, cid, "OLD-UNIQUE")["duplicate"]
    assert scan(client, auth_headers, cid, "COUNT-0")["duplicate"]
    assert scan(client, auth_headers, cid, "NEVER-IMPORTED")["row"]["result"] == "unknown"
    assert scan(client, auth_headers, cid, "NEVER-IMPORTED")["duplicate"]
    assert scan(client, auth_headers, cid, "COUNT-QR-3")["row"]["result"] == "unexpected"
    assert scan(client, auth_headers, cid, "COUNT-QR-4")["row"]["result"] == "unexpected"
    result = detail(client, auth_headers, cid)
    assert result["summary"]["found"] == 1
    assert result["summary"]["scanned"] == 4
    assert result["summary"]["missing"] == initial["summary"]["expected"] - 1
    completed = client.post(f"{BASE}/{cid}/complete", headers=auth_headers)
    assert completed.status_code == 200
    assert client.post(f"{BASE}/{cid}/complete", headers=auth_headers).json() == completed.json()
    assert client.post(f"{BASE}/{cid}/scan", headers=auth_headers, json={"code": "COUNT-1"}).status_code == 409
    assert client.delete(f"{BASE}/{cid}/scans/{first['row']['id']}", headers=auth_headers).status_code == 409
    assert business_fingerprint() == before


def test_ambiguous_and_conflicting_codes_never_select_a_pack(client, auth_headers, packs):
    cid = start(client, auth_headers)
    for code in ["OLD-SHARED", "PACKAGE:COUNT-0|COUNT-QR-1"]:
        result = scan(client, auth_headers, cid, code)
        assert result["row"]["result"] == "ambiguous"
        assert result["row"]["package_id"] is None
    assert detail(client, auth_headers, cid)["summary"]["found"] == 0
    assert scan(client, auth_headers, cid, "PACKAGE:COUNT-0|COUNT-QR-0")["row"]["result"] == "found"


def test_undo_is_scoped_audited_and_restores_missing(client, auth_headers, packs):
    cid = start(client, auth_headers)
    other = start(client, auth_headers)
    found = scan(client, auth_headers, cid, "COUNT-0")["row"]["id"]
    unknown = scan(client, auth_headers, cid, "UNKNOWN")["row"]["id"]
    assert client.delete(f"{BASE}/{other}/scans/{found}", headers=auth_headers).status_code == 404
    for row_id in [found, unknown]:
        assert client.delete(f"{BASE}/{cid}/scans/{row_id}", headers=auth_headers).status_code == 200
    result = detail(client, auth_headers, cid)
    assert result["summary"]["scanned"] == result["summary"]["unknown"] == 0
    assert result["summary"]["missing"] == result["summary"]["expected"]
    assert not scan(client, auth_headers, cid, "COUNT-0")["duplicate"]
    with SessionLocal() as db:
        assert (
            db.query(AuditLog).filter_by(entity_type="WarehouseStocktake", entity_id=cid, action="undo_scan").count()
            == 2
        )


def test_movement_snapshot_and_completed_report_are_stable(client, auth_headers, packs):
    cid = start(client, auth_headers)
    with SessionLocal() as db:
        db.get(Package, packs[0]).status = "shipped"
        db.get(Package, packs[1]).storage_cell = "A-01"
        db.query(FinishedGoodsStock).filter_by(package_id=packs[2]).update({"available_qty": 12})
        db.commit()
    result = detail(client, auth_headers, cid, "?result=changed")
    assert result["summary"]["changed"] == 3
    assert result["total"] == 3
    row = next(r for r in result["rows"] if r["package_id"] == packs[0])
    assert row["snapshot"]["status"] == "received_in_storage"
    assert row["current"]["status"] == "shipped"
    client.post(f"{BASE}/{cid}/complete", headers=auth_headers)
    frozen = detail(client, auth_headers, cid)
    with SessionLocal() as db:
        db.get(Package, packs[0]).status = "delivered"
        db.commit()
    assert detail(client, auth_headers, cid) == frozen


def test_pagination_filters_export_and_start_retry(client, auth_headers, packs):
    key = str(uuid4())
    cid = start(client, auth_headers, request_key=key, title="=COUNT")
    assert start(client, auth_headers, request_key=key) == cid
    scan(client, auth_headers, cid, "=UNKNOWN")
    unknown = detail(client, auth_headers, cid, "?result=unknown&q=UNKNOWN&limit=1")
    assert unknown["total"] == 1 and len(unknown["rows"]) == 1
    assert detail(client, auth_headers, cid, "?limit=1&offset=99999")["rows"] == []
    exported = client.get(f"{BASE}/{cid}/export.csv", headers=auth_headers)
    assert exported.status_code == 200
    rows = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert len(rows) == detail(client, auth_headers, cid)["total"] + 2  # Header + explicit totals footer.
    assert rows[-1][-1] == "totals"
    assert rows[1][0] == "'=COUNT"
    assert any("'=UNKNOWN" in row for row in rows)
    assert client.get(f"{BASE}/{cid}?limit=201", headers=auth_headers).status_code == 422


@pytest.mark.parametrize("code", ["", "   ", "a" * 513])
def test_invalid_scans_not_recorded(client, auth_headers, code):
    cid = start(client, auth_headers)
    assert client.post(f"{BASE}/{cid}/scan", headers=auth_headers, json={"code": code}).status_code == 422
    assert detail(client, auth_headers, cid)["summary"]["scanned"] == 0


def test_all_count_endpoints_require_warehouse_access(client, auth_headers, packs):
    cid = start(client, auth_headers)
    row_id = scan(client, auth_headers, cid, "COUNT-0")["row"]["id"]
    token = client.post("/api/auth/token", data={"username": "planning@example.com", "password": "demo12345"})
    assert token.status_code == 200, token.text
    headers = {"Authorization": "Bearer " + token.json()["access_token"]}
    for method, path, body in [
        ("get", BASE, None),
        ("post", BASE, {"request_key": str(uuid4()), "title": "Forbidden"}),
        ("get", f"{BASE}/{cid}", None),
        ("get", f"{BASE}/{cid}/export.csv", None),
        ("post", f"{BASE}/{cid}/scan", {"code": "COUNT-0"}),
        ("post", f"{BASE}/{cid}/complete", None),
        ("delete", f"{BASE}/{cid}/scans/{row_id}", None),
    ]:
        kwargs = {"headers": headers}
        if body is not None:
            kwargs["json"] = body
        assert client.request(method, path, **kwargs).status_code == 403, path


def test_scans_and_missing_lists_are_isolated_between_counts(client, auth_headers, packs):
    first, second = start(client, auth_headers), start(client, auth_headers)
    scan(client, auth_headers, first, "COUNT-0")
    assert detail(client, auth_headers, second)["summary"]["found"] == 0
    assert not scan(client, auth_headers, second, "COUNT-0")["duplicate"]


def test_ready_storage_user_can_run_count_and_anonymous_cannot(client, packs):
    assert client.get(BASE).status_code == 401
    token = client.post("/api/auth/token", data={"username": "fgs@example.com", "password": "demo12345"})
    assert token.status_code == 200, token.text
    headers = {"Authorization": "Bearer " + token.json()["access_token"]}
    cid = start(client, headers)
    assert scan(client, headers, cid, "COUNT-0")["row"]["result"] == "found"
    assert detail(client, headers, cid)["summary"]["found"] == 1
    assert client.post(f"{BASE}/{cid}/complete", headers=headers).status_code == 200
    assert client.get(f"{BASE}/{cid}/export.csv", headers=headers).status_code == 200


def test_stocktake_migration_roundtrip():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = Path(__file__).parents[2] / "alembic/versions/0114_warehouse_stocktake.py"
    spec = importlib.util.spec_from_file_location("stocktake_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            inspector = inspect(connection)
            assert set(inspector.get_table_names()) == {"warehouse_stocktakes", "warehouse_stocktake_rows"}
            assert {i["name"] for i in inspector.get_indexes("warehouse_stocktake_rows")} == {
                "ix_warehouse_stocktake_rows_stocktake_id",
                "ix_warehouse_stocktake_rows_package_id",
            }
            assert any(
                c["column_names"] == ["stocktake_id", "identity"]
                for c in inspector.get_unique_constraints("warehouse_stocktake_rows")
            )
            migration.downgrade()
            assert inspect(connection).get_table_names() == []
    engine.dispose()

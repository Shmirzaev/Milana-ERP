from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes import stocktake as stocktake_routes
from app.models import Package, User
from app.models.stocktake import WarehouseStocktake, WarehouseStocktakeRow
from app.services import stocktake as stocktake_service
from app.tests.conftest import TestSessionLocal


def _stocktake_rows(count: int) -> int:
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        stocktake = WarehouseStocktake(
            request_key=str(uuid4()),
            title="PERF33 pagination",
            created_by=current.id,
        )
        db.add(stocktake)
        db.flush()
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = []
        for number in range(count):
            scanned = number % 3 != 0
            expected = number % 2 == 0
            category = "expected" if expected else ("unknown", "unexpected", "ambiguous")[number % 3]
            snapshot = {
                "package_no": f"PERF33-{number:04d}",
                "barcode": f"PERF33-QR-{number:04d}",
                "model_code": "PERF33",
                "model_name": "Pagination model",
                "color": "blue",
                "quantity": number,
                "available": number,
                "reserved": 0,
                "status": "received_in_storage",
                "warehouse_id": 1,
                "location": "A-01",
            }
            rows.append(WarehouseStocktakeRow(
                stocktake_id=stocktake.id,
                identity=f"synthetic:{number}",
                expected=expected,
                category=category,
                snapshot=snapshot,
                scan_snapshot=snapshot if scanned else None,
                scan_code=f"SCAN-{number:04d}" if scanned else None,
                scanned_at=started + timedelta(seconds=number) if scanned else None,
                scanned_by=current.id if scanned else None,
            ))
        db.add_all(rows)
        db.commit()
        return int(stocktake.id)


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_common_stocktake_page_serializes_only_requested_rows(monkeypatch, row_count):
    count_id = _stocktake_rows(row_count)
    calls = 0
    original = stocktake_service.row_payload

    def counted_payload(row, current):
        nonlocal calls
        calls += 1
        return original(row, current)

    monkeypatch.setattr(stocktake_routes, "row_payload", counted_payload)
    monkeypatch.setattr(stocktake_service, "row_payload", counted_payload)
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        result = stocktake_routes.detail(
            count_id,
            db,
            current,
            result="all",
            q="",
            offset=0,
            limit=10,
        )

    assert result["total"] == row_count
    assert len(result["rows"]) == min(row_count, 10)
    assert calls == min(row_count, 10)


def _scalar_detail(rows, result, offset, limit):
    summary = {
        key: sum(row["result"] == key for row in rows)
        for key in ("found", "missing", "unknown", "unexpected", "ambiguous")
    }
    summary["expected"] = sum(row["expected"] for row in rows)
    summary["changed"] = sum(row["changed"] for row in rows)
    summary.update(stocktake_service.scan_summary(rows))
    filtered = [
        row
        for row in rows
        if result == "all"
        or (row["scanned_at"] is not None if result == "scanned" else row["result"] == result)
    ]
    if result == "scanned":
        filtered.sort(key=lambda row: (row["scanned_at"], row["id"]), reverse=True)
    return summary, len(filtered), filtered[offset:offset + limit]


@pytest.mark.parametrize(
    "result",
    ["all", "scanned", "found", "missing", "unknown", "unexpected", "ambiguous"],
)
def test_common_stocktake_filters_summary_and_sort_match_scalar(result):
    count_id = _stocktake_rows(37)
    with TestSessionLocal() as db:
        count = stocktake_routes.get_count(db, count_id)
        expected_summary, expected_total, expected_rows = _scalar_detail(
            stocktake_routes.results(db, count),
            result,
            offset=2,
            limit=5,
        )
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        actual = stocktake_routes.detail(
            count_id,
            db,
            current,
            result=result,
            q="",
            offset=2,
            limit=5,
        )

    assert actual["summary"] == expected_summary
    assert actual["total"] == expected_total
    assert actual["rows"] == expected_rows


@pytest.mark.parametrize("row_count,offset", [(0, 0), (7, 999)])
def test_common_stocktake_page_preserves_zero_and_past_end_totals(row_count, offset):
    count_id = _stocktake_rows(row_count)
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        actual = stocktake_routes.detail(
            count_id,
            db,
            current,
            result="all",
            q="",
            offset=offset,
            limit=5,
    )

    assert actual["total"] == row_count
    assert actual["rows"] == []
    if row_count == 0:
        assert actual["summary"] == {
            "found": 0,
            "missing": 0,
            "unknown": 0,
            "unexpected": 0,
            "ambiguous": 0,
            "expected": 0,
            "changed": 0,
            "scanned": 0,
            "scanned_packages": 0,
            "scanned_pieces": 0,
            "estimated_packages": 0,
            "unquantified_packages": 0,
        }


def test_search_and_changed_filters_keep_scalar_fallback(monkeypatch):
    count_id = _stocktake_rows(31)
    calls = 0
    original = stocktake_routes.row_payload

    def counted_payload(row, current):
        nonlocal calls
        calls += 1
        return original(row, current)

    monkeypatch.setattr(stocktake_routes, "row_payload", counted_payload)
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        searched = stocktake_routes.detail(
            count_id,
            db,
            current,
            result="all",
            q="SCAN-0001",
            offset=0,
            limit=10,
        )
        changed = stocktake_routes.detail(
            count_id,
            db,
            current,
            result="changed",
            q="",
            offset=0,
            limit=10,
        )

    assert searched["total"] == 1
    assert searched["rows"][0]["scan_code"] == "SCAN-0001"
    assert changed["total"] == 0
    assert calls == 62


def test_requested_package_snapshot_scopes_finished_goods_balance_subquery():
    with TestSessionLocal() as db:
        package_id = db.query(Package.id).order_by(Package.id.asc()).scalar() or 987653
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT") and "finished_goods_stock" in statement:
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            stocktake_service.package_snapshots(db, [package_id])
            assert stocktake_service.package_snapshots(db, []) == {}
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert statements
    assert all("where finished_goods_stock.package_id in" in statement for statement in statements)


def test_completed_page_preserves_global_frozen_null_snapshot_semantics():
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        count = WarehouseStocktake(
            request_key=str(uuid4()),
            title="Legacy completed snapshots",
            created_by=current.id,
            completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        db.add(count)
        db.flush()
        db.add_all([
            WarehouseStocktakeRow(
                stocktake_id=count.id,
                identity="legacy:first",
                package_id=987654,
                expected=True,
                category="expected",
                snapshot={"package_no": "FROZEN-A", "quantity": 1},
                final_snapshot={"package_no": "FROZEN-A", "quantity": 1},
            ),
            WarehouseStocktakeRow(
                stocktake_id=count.id,
                identity="legacy:second",
                package_id=987654,
                expected=True,
                category="expected",
                snapshot={"package_no": "FROZEN-B", "quantity": 2},
                final_snapshot=None,
            ),
        ])
        db.commit()
        count_id = int(count.id)

    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        actual = stocktake_routes.detail(
            count_id,
            db,
            current,
            result="all",
            q="",
            offset=0,
            limit=1,
        )

    assert actual["summary"]["changed"] == 2
    assert actual["total"] == 2
    assert actual["rows"][0]["current"] is None
    assert actual["rows"][0]["changed"] is True


def test_live_page_preserves_deleted_package_current_snapshot_semantics():
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        count = WarehouseStocktake(
            request_key=str(uuid4()),
            title="Deleted package snapshot",
            created_by=current.id,
        )
        db.add(count)
        db.flush()
        db.add(WarehouseStocktakeRow(
            stocktake_id=count.id,
            identity="deleted:package",
            package_id=987655,
            expected=True,
            category="expected",
            snapshot={"package_no": "DELETED", "quantity": 3},
        ))
        db.commit()
        count_id = int(count.id)

    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        actual = stocktake_routes.detail(
            count_id,
            db,
            current,
            result="all",
            q="",
            offset=0,
            limit=10,
        )

    assert actual["summary"]["changed"] == 1
    assert actual["rows"][0]["current"] == {}
    assert actual["rows"][0]["changed"] is True

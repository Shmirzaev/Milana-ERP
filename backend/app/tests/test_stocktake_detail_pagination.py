import csv
import io
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.responses import StreamingResponse
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


def _changed_stocktake_rows(count: int) -> int:
    count_id = _stocktake_rows(count)
    with TestSessionLocal() as db:
        rows = db.query(WarehouseStocktakeRow).filter_by(stocktake_id=count_id).order_by(
            WarehouseStocktakeRow.id.asc(),
        ).all()
        for index, row in enumerate(rows):
            row.package_id = 9_000_000 + index
        db.commit()
    return count_id


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


@pytest.mark.parametrize(("row_count", "expected_row_pages"), [(1, 1), (50, 1), (401, 2)])
def test_stocktake_export_streams_complete_keyset_pages(
    client,
    auth_headers,
    monkeypatch,
    row_count,
    expected_row_pages,
):
    count_id = _stocktake_rows(row_count)
    serialized = 0
    original = stocktake_routes.row_payload

    def counted_payload(row, current):
        nonlocal serialized
        serialized += 1
        return original(row, current)

    monkeypatch.setattr(stocktake_routes, "row_payload", counted_payload)
    statements: list[str] = []
    with TestSessionLocal() as db:
        bind = db.bind

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(bind, "before_cursor_execute", capture)
    try:
        response = client.get(
            f"/api/warehouse-stocktakes/{count_id}/export.csv",
            headers=auth_headers,
        )
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == row_count + 1  # Data rows plus totals footer.
    assert rows[-1]["Row type"] == "totals"
    assert serialized == row_count
    row_pages = [
        statement
        for statement in statements
        if " from warehouse_stocktake_rows " in statement
        and "order by warehouse_stocktake_rows.id asc" in statement
        and " limit " in statement
    ]
    assert len(row_pages) == expected_row_pages, statements
    assert all("warehouse_stocktake_rows.id >" in statement for statement in row_pages)

    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        streamed = stocktake_routes.export(count_id, db, current)
    assert isinstance(streamed, StreamingResponse)


def test_completed_export_uses_global_latest_snapshot_for_cross_chunk_duplicate_package():
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        package_id = db.query(Package.id).order_by(Package.id.asc()).scalar() or 987654
        stocktake = WarehouseStocktake(
            request_key=str(uuid4()),
            title="PERF33 completed duplicate",
            created_by=current.id,
            completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        db.add(stocktake)
        db.flush()
        db.add_all([
            WarehouseStocktakeRow(
                stocktake_id=stocktake.id,
                identity=f"legacy-duplicate:{number}",
                package_id=package_id,
                expected=True,
                category="expected",
                snapshot={"package_no": f"START-{number}"},
                final_snapshot={"package_no": f"FINAL-{number}"},
            )
            for number in range(401)
        ])
        db.commit()
        count_id = int(stocktake.id)

    statements: list[str] = []
    with TestSessionLocal() as db:
        count = stocktake_routes.get_count(db, count_id)

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = list(stocktake_routes._stocktake_export_rows(db, count))
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(rows) == 401
    assert all(row["current"] == {"package_no": "FINAL-400"} for row in rows)
    latest_snapshot_queries = [
        statement
        for statement in statements
        if "max(warehouse_stocktake_rows.id)" in statement
        and "group by warehouse_stocktake_rows.package_id" in statement
    ]
    assert len(latest_snapshot_queries) == 2, statements


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


def test_search_and_changed_filters_serialize_only_matching_page(monkeypatch):
    count_id = _stocktake_rows(31)
    calls = 0
    original = stocktake_routes.row_payload

    def counted_payload(row, current):
        nonlocal calls
        calls += 1
        return original(row, current)

    monkeypatch.setattr(stocktake_routes, "row_payload", counted_payload)
    monkeypatch.setattr(stocktake_service, "row_payload", counted_payload)
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
    assert calls == 1  # only the search match; unchanged rows never hydrate


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_changed_filter_matches_scalar_parity_and_bounds_hydration_queries(monkeypatch, row_count):
    count_id = _changed_stocktake_rows(row_count)
    needle = "PERF33-00"
    offset = 3
    limit = 7
    with TestSessionLocal() as db:
        count = db.get(WarehouseStocktake, count_id)
        scalar_rows = stocktake_routes.results(db, count)
        scalar_summary = {
            key: sum(row["result"] == key for row in scalar_rows)
            for key in ("found", "missing", "unknown", "unexpected", "ambiguous")
        }
        scalar_summary["expected"] = sum(row["expected"] for row in scalar_rows)
        scalar_summary["changed"] = sum(row["changed"] for row in scalar_rows)
        scalar_summary.update(stocktake_service.scan_summary(scalar_rows))
        expected_rows = [
            row for row in scalar_rows
            if row["changed"]
            and needle.casefold() in " ".join(
                str(value or "")
                for value in [
                    row["scan_code"], *row["snapshot"].values(),
                    *(row["scan_snapshot"] or {}).values(),
                ]
            ).casefold()
        ]

    calls = 0
    original = stocktake_service.row_payload

    def counted_payload(row, current):
        nonlocal calls
        calls += 1
        return original(row, current)

    monkeypatch.setattr(stocktake_routes, "row_payload", counted_payload)
    monkeypatch.setattr(stocktake_service, "row_payload", counted_payload)
    statements: list[str] = []

    def capture_statement(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        event.listen(db.bind, "before_cursor_execute", capture_statement)
        try:
            actual = stocktake_routes.detail(
                count_id,
                db,
                current,
                result="changed",
                q=needle,
                offset=offset,
                limit=limit,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture_statement)

    assert actual["summary"] == scalar_summary
    assert actual["total"] == len(expected_rows)
    assert actual["rows"] == expected_rows[offset : offset + limit]
    assert calls == len(actual["rows"]) <= limit
    select_count = sum(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    # Summary plus two 400-row scan/snapshot chunks and one page hydration stays constant-scale.
    assert select_count <= 14


def test_search_serializes_only_matching_rows_for_large_count(monkeypatch):
    count_id = _stocktake_rows(401)
    calls = 0
    original = stocktake_routes.row_payload

    def counted_payload(row, current):
        nonlocal calls
        calls += 1
        return original(row, current)

    monkeypatch.setattr(stocktake_routes, "row_payload", counted_payload)
    monkeypatch.setattr(stocktake_service, "row_payload", counted_payload)
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        searched = stocktake_routes.detail(
            count_id,
            db,
            current,
            result="all",
            q="SCAN-0400",
            offset=0,
            limit=10,
        )

    assert searched["total"] == 1
    assert len(searched["rows"]) == 1
    assert searched["rows"][0]["scan_code"] == "SCAN-0400"
    assert calls == 1


def test_search_matches_snapshot_values_not_json_keys():
    count_id = _stocktake_rows(5)
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        key_match = stocktake_routes.detail(
            count_id, db, current, result="all", q="package_no", offset=0, limit=10
        )
        value_match = stocktake_routes.detail(
            count_id, db, current, result="all", q="PERF33-0001", offset=0, limit=10
        )

    assert key_match["total"] == 0
    assert value_match["total"] == 1
    assert value_match["rows"][0]["scan_code"] == "SCAN-0001"


def test_broad_search_counts_all_matches_but_serializes_only_requested_page(monkeypatch):
    count_id = _stocktake_rows(401)
    calls = 0
    original = stocktake_routes.row_payload

    def counted_payload(row, current):
        nonlocal calls
        calls += 1
        return original(row, current)

    monkeypatch.setattr(stocktake_routes, "row_payload", counted_payload)
    monkeypatch.setattr(stocktake_service, "row_payload", counted_payload)
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        searched = stocktake_routes.detail(
            count_id,
            db,
            current,
            result="all",
            q="SCAN-",
            offset=100,
            limit=10,
        )

    matching_codes = [f"SCAN-{index:04d}" for index in range(401) if index % 3 != 0]
    assert searched["total"] == len(matching_codes)
    assert [row["scan_code"] for row in searched["rows"]] == matching_codes[100:110]
    assert calls == 10


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


@pytest.mark.parametrize("scan_count", [1, 50, 401])
def test_stocktake_summary_groups_duplicate_package_scan_evidence(monkeypatch, scan_count):
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        package_id = 987656
        count = WarehouseStocktake(
            request_key=str(uuid4()),
            title="PERF33 grouped scan evidence",
            created_by=current.id,
            completed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        db.add(count)
        db.flush()
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db.add_all([
            WarehouseStocktakeRow(
                stocktake_id=count.id,
                identity=f"duplicate-scan:{number}",
                package_id=package_id,
                expected=True,
                category="expected",
                snapshot={"package_no": "DUPLICATE", "quantity": 7},
                scan_snapshot={"package_no": "DUPLICATE", "quantity": 7 + number},
                final_snapshot={"package_no": "DUPLICATE", "quantity": 7},
                scan_code=f"DUPLICATE-{number}",
                scanned_at=started + timedelta(seconds=number),
                scanned_by=current.id,
            )
            for number in range(scan_count)
        ])
        db.commit()
        count_id = int(count.id)

    calls = 0
    original_scan_fields = stocktake_service.scan_fields

    def counted_scan_fields(row):
        nonlocal calls
        calls += 1
        return original_scan_fields(row)

    monkeypatch.setattr(stocktake_service, "scan_fields", counted_scan_fields)
    statements: list[str] = []
    with TestSessionLocal() as db:
        count = db.get(WarehouseStocktake, count_id)

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            summary = stocktake_service.stocktake_summary(db, count)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert summary["scanned"] == scan_count
    assert summary["scanned_packages"] == 1
    assert summary["scanned_pieces"] == 7
    assert summary["estimated_packages"] == 0
    assert summary["unquantified_packages"] == 0
    assert calls == 1
    grouped_scans = [
        statement
        for statement in statements
        if "min(warehouse_stocktake_rows.id)" in statement
        and "group by warehouse_stocktake_rows.package_id" in statement
    ]
    assert len(grouped_scans) == 1


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
        changed = stocktake_routes.detail(
            count_id,
            db,
            current,
            result="changed",
            q="",
            offset=0,
            limit=1,
        )

    assert actual["summary"]["changed"] == 2
    assert actual["total"] == 2
    assert actual["rows"][0]["current"] is None
    assert actual["rows"][0]["changed"] is True
    assert changed["summary"] == actual["summary"]
    assert changed["total"] == 2
    assert changed["rows"][0]["current"] is None
    assert changed["rows"][0]["changed"] is True


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

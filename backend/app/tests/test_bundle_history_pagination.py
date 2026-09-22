from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.api.routes.bundles import get_history
from app.db.session import SessionLocal
from app.models import BundleScanLog
from app.tests.test_production_flow import _create_bundle_for_scan


def _seed_history(bundle_id: int, count: int) -> list[int]:
    with SessionLocal() as db:
        db.query(BundleScanLog).filter(BundleScanLog.bundle_id == bundle_id).delete()
        rows = [
            BundleScanLog(
                bundle_id=bundle_id,
                scan_type=f"page_scan_{number:04d}",
                scanned_at=datetime(2095, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=number),
            )
            for number in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return [int(row.id) for row in rows]


def _statement_trace(db, callback):
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        return callback(), statements
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_bundle_history_page_bounds_rows_matches_legacy_and_never_writes(
    row_count,
    client,
    auth_headers,
):
    bundle = _create_bundle_for_scan(client, auth_headers)
    scan_ids = _seed_history(bundle["id"], row_count)

    with SessionLocal() as db:
        legacy, legacy_statements = _statement_trace(
            db,
            lambda: get_history(bundle["id"], db, None),
        )
    with SessionLocal() as db:
        page, page_statements = _statement_trace(
            db,
            lambda: get_history(bundle["id"], db, None, page=1, page_size=50),
        )

    expected_ids = scan_ids[:50]
    assert [row["id"] for row in legacy[:50]] == expected_ids
    assert [row["id"] for row in page["rows"]] == expected_ids
    assert page["rows"] == legacy[:50]
    assert page["total"] == row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (row_count > 50)
    assert len(page["rows"]) <= 50
    assert len(legacy_statements) == 2
    assert len(page_statements) == 3
    assert all(statement.startswith("select") for statement in [*legacy_statements, *page_statements])
    row_statement = next(
        statement
        for statement in page_statements
        if " from bundle_scan_logs " in statement and " order by bundle_scan_logs.scanned_at asc" in statement
    )
    assert "bundle_scan_logs.bundle_id = ?" in row_statement
    assert " limit ? offset ?" in row_statement


def test_bundle_history_page_http_contract_preserves_legacy_auth_and_404(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)
    _seed_history(bundle["id"], 2)

    legacy = client.get(f"/api/bundles/{bundle['id']}/history", headers=auth_headers)
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)

    paged = client.get(
        f"/api/bundles/{bundle['id']}/history?page=1&page_size=50",
        headers=auth_headers,
    )
    assert paged.status_code == 200
    body = paged.json()
    assert body["rows"] == legacy.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert set(body["rows"][0]) == {
        "id",
        "scan_type",
        "scanned_by",
        "from_department_id",
        "to_department_id",
        "scanned_at",
    }

    assert client.get(
        f"/api/bundles/{bundle['id']}/history?page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get(f"/api/bundles/{bundle['id']}/history?page=1&page_size=50").status_code == 401
    missing = client.get("/api/bundles/2000000000/history?page=1&page_size=50", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Bundle not found"

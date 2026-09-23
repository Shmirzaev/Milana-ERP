from datetime import datetime, timezone
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.stocktake import list_counts
from app.models import User
from app.models.stocktake import WarehouseStocktake, WarehouseStocktakeRow
from app.tests.conftest import TestSessionLocal


@contextmanager
def _stocktake_database(count: int):
    engine = create_engine("sqlite://")
    WarehouseStocktake.__table__.create(engine)
    WarehouseStocktakeRow.__table__.create(engine)
    with Session(engine) as db:
        rows = [
            WarehouseStocktake(
                request_key=str(uuid4()),
                title=f"PERF35 stocktake {index:04d}",
                created_by=1,
            )
            for index in range(count)
        ]
        db.add_all(rows)
        db.commit()
        yield db, [int(row.id) for row in rows]
    engine.dispose()


def _read(db: Session, **kwargs):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        payload = list_counts(db, object(), **kwargs)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_stocktake_pages_bound_sql_and_preserve_legacy_payload(count):
    with _stocktake_database(count) as (db, created_ids):
        page, statements = _read(db, offset=0, page=1, page_size=50)
        legacy, legacy_statements = _read(db, offset=0)

        selects = [statement for statement in statements if statement.startswith("select")]
        writes = [
            statement
            for statement in statements
            if statement.startswith(("insert", "update", "delete"))
        ]
        assert page == {
            **legacy,
            "page": 1,
            "page_size": 50,
            "has_more": count > 50,
        }
        assert [row["id"] for row in page["items"]] == list(reversed(created_ids))[:50]
        assert len(page["items"]) == min(count, 50)
        assert len(selects) == 3, selects
        assert " limit ? offset ?" in selects[0]
        assert "warehouse_stocktakes.request_key" not in selects[0]
        assert "warehouse_stocktakes.created_by" in selects[0]
        assert len([statement for statement in legacy_statements if statement.startswith("select")]) == 3
        assert writes == []


def test_stocktake_page_contract_auth_compatibility_and_no_writes(client, auth_headers):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        user_id = int(db.query(User.id).order_by(User.id).first()[0])
        rows = [
            WarehouseStocktake(
                request_key=str(uuid4()),
                title=f"PERF35 stocktake {marker} {index}",
                created_by=user_id,
            )
            for index in range(3)
        ]
        db.add_all(rows)
        db.commit()
        created_ids = [int(row.id) for row in rows]
        before = db.query(WarehouseStocktake).count()

    legacy = client.get("/api/warehouse-stocktakes?offset=0", headers=auth_headers)
    paged = client.get(
        "/api/warehouse-stocktakes?page=1&page_size=2",
        headers=auth_headers,
    )

    assert legacy.status_code == paged.status_code == 200
    assert paged.json() == {
        "total": legacy.json()["total"],
        "items": legacy.json()["items"][:2],
        "page": 1,
        "page_size": 2,
        "has_more": legacy.json()["total"] > 2,
    }
    assert [row["id"] for row in paged.json()["items"]] == list(reversed(created_ids))[:2]
    assert client.get("/api/warehouse-stocktakes?page=1&page_size=1").status_code == 401
    assert client.get(
        "/api/warehouse-stocktakes?page_size=501",
        headers=auth_headers,
    ).status_code == 422

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/warehouse-stocktakes?page=1&page_size=1",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with TestSessionLocal() as db:
        assert db.query(WarehouseStocktake).count() == before


def test_stocktake_list_scan_summary_streams_and_preserves_first_package_evidence():
    with _stocktake_database(1) as (db, created_ids):
        stocktake_id = created_ids[0]
        scanned_at = datetime.now(timezone.utc)
        db.add_all([
            WarehouseStocktakeRow(
                stocktake_id=stocktake_id, identity="package:first", package_id=91,
                expected=True, category="expected", snapshot={"quantity": 7},
                scanned_at=scanned_at,
            ),
            WarehouseStocktakeRow(
                stocktake_id=stocktake_id, identity="package:duplicate", package_id=91,
                expected=False, category="unexpected", snapshot={"quantity": 9},
                scan_snapshot={"quantity": 12}, scanned_at=scanned_at,
            ),
            WarehouseStocktakeRow(
                stocktake_id=stocktake_id, identity="code:unknown", package_id=None,
                expected=False, category="unknown", snapshot={}, scanned_at=scanned_at,
            ),
        ])
        db.commit()

        payload, statements = _read(db, offset=0, page=1, page_size=1)

    assert payload["items"][0]["summary"] == {
        "scanned": 3,
        "scanned_packages": 1,
        "scanned_pieces": 7,
        "estimated_packages": 1,
        "unquantified_packages": 0,
    }
    scan_selects = [
        statement for statement in statements
        if statement.startswith("select") and "warehouse_stocktake_rows" in statement
    ]
    assert len(scan_selects) == 1
    assert "order by warehouse_stocktake_rows.id asc" in scan_selects[0]

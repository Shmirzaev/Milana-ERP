from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.finance import get_revenue_by_period
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Invoice, Role, SalesOrder, User


def _seed_months(count: int) -> tuple[datetime, datetime, list[str]]:
    marker = uuid4().hex
    with SessionLocal() as db:
        order = SalesOrder(order_no=f"REVENUE-PAGE-{marker}", status="confirmed", total_amount=count)
        db.add(order)
        db.flush()
        periods: list[str] = []
        invoices = []
        for index in range(count):
            year = 1980 + index // 12
            month = index % 12 + 1
            periods.append(f"{year:04d}-{month:02d}")
            invoices.append(
                Invoice(
                    sales_order_id=order.id,
                    invoice_no=f"REVENUE-PAGE-{marker}-{index:04d}",
                    amount=index + 1,
                    status="unpaid",
                    issued_at=datetime(year, month, 15, 12, tzinfo=timezone.utc),
                )
            )
        db.add_all(invoices)
        db.commit()
    start = datetime(1980, 1, 1, tzinfo=timezone.utc)
    last_index = count - 1
    last_year = 1980 + last_index // 12
    last_month = last_index % 12 + 1
    if last_month == 12:
        end = datetime(last_year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(microseconds=1)
    else:
        end = datetime(last_year, last_month + 1, 1, tzinfo=timezone.utc) - timedelta(microseconds=1)
    return start, end, periods


def _read(from_dt: datetime, to_dt: datetime, **kwargs):
    with SessionLocal() as db:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = get_revenue_by_period(db, None, from_dt, to_dt, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_revenue_period_page_bounds_grouped_sql_and_matches_legacy_prefix(row_count):
    from_dt, to_dt, periods = _seed_months(row_count)

    legacy, legacy_statements = _read(from_dt, to_dt)
    page, page_statements = _read(from_dt, to_dt, page=1, page_size=50)

    assert [row["period"] for row in legacy] == periods
    assert page["rows"] == legacy[:50]
    assert page["total"] == row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (row_count > 50)
    assert len(page["rows"]) <= 50
    assert len(legacy_statements) == 1, legacy_statements
    assert len(page_statements) == 2, page_statements
    row_statement = next(statement for statement in page_statements if " limit ? offset ?" in statement)
    assert "group by" in row_statement
    assert "order by" in row_statement


def test_revenue_period_page_contract_permission_auth_and_no_writes(client, auth_headers):
    from_dt, to_dt, _periods = _seed_months(3)
    with SessionLocal() as db:
        role = Role(name=f"No finance view {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        denied_user = User(
            name="Denied finance reader",
            email=f"denied-finance-reader-{uuid4().hex}@example.com",
            password_hash="unused-pagination-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(denied_user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied_user.id)}"}
        before = (db.query(Invoice).count(), db.query(SalesOrder).count(), db.query(AuditLog).count())

    params = {"from": from_dt.isoformat(), "to": to_dt.isoformat()}
    legacy = client.get("/api/finance/revenue-by-period", params=params, headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)

    paged = client.get(
        "/api/finance/revenue-by-period",
        params={**params, "page": 2, "page_size": 2},
        headers=auth_headers,
    )
    assert paged.status_code == 200, paged.text
    payload = paged.json()
    assert payload["rows"] == legacy.json()[2:4]
    assert payload["total"] == 3
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["has_more"] is False

    assert client.get(
        "/api/finance/revenue-by-period",
        params={**params, "page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/finance/revenue-by-period",
        params={**params, "page": 1, "page_size": 2},
        headers=denied_headers,
    ).status_code == 403
    assert client.get(
        "/api/finance/revenue-by-period",
        params={**params, "page": 1, "page_size": 2},
    ).status_code == 401

    with SessionLocal() as db:
        after = (db.query(Invoice).count(), db.query(SalesOrder).count(), db.query(AuditLog).count())
    assert after == before

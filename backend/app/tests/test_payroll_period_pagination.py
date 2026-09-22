from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.payroll import list_periods
from app.models import AuditLog, PayrollPeriod
from app.schemas.payroll import PayrollPeriodOut
from app.tests.conftest import TestSessionLocal


def _factory_user():
    return SimpleNamespace(
        role=SimpleNamespace(name="", permissions=[]),
        factory_code="MIL",
        session_factory_code="MIL",
    )


@contextmanager
def _period_database(count: int):
    engine = create_engine("sqlite://")
    PayrollPeriod.__table__.create(engine)
    base_date = datetime(2090, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as db:
        periods = [
            PayrollPeriod(
                factory_code="MIL",
                period_no=f"PERF35-{index:04d}",
                name=f"Payroll period {index:04d}",
                start_date=base_date + timedelta(days=index),
                end_date=base_date + timedelta(days=index, hours=12),
                status="draft",
            )
            for index in range(count)
        ]
        db.add_all(periods)
        db.commit()
        yield db, [int(period.id) for period in periods]
    engine.dispose()


def _read(db: Session, **kwargs):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        payload = list_periods(db, _factory_user(), status="draft", **kwargs)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return payload, statements


def _payload(rows: list[PayrollPeriod]) -> list[dict]:
    return [PayrollPeriodOut.model_validate(row).model_dump(mode="json") for row in rows]


@pytest.mark.parametrize("count", [1, 50, 401])
def test_payroll_period_pages_bound_sql_and_preserve_legacy_payload(count):
    with _period_database(count) as (db, period_ids):
        page, statements = _read(db, page=1, page_size=50)
        legacy, legacy_statements = _read(db, page=None, page_size=None)
        expected_count = min(count, 50)

        assert page["total"] == count
        assert page["page"] == 1
        assert page["page_size"] == 50
        assert page["has_more"] is (count > 50)
        assert [row.id for row in page["rows"]] == list(reversed(period_ids))[:expected_count]
        assert _payload(page["rows"]) == _payload(legacy[:expected_count])
        assert len(statements) == 2, statements
        assert " limit ? offset ?" in statements[1]
        assert len(legacy_statements) == 1, legacy_statements


def test_payroll_period_page_contract_factory_filter_auth_and_no_writes(client, auth_headers):
    marker = uuid4().hex[:10]
    start_date = datetime(2099, 1, 1, tzinfo=timezone.utc)
    with TestSessionLocal() as db:
        mil_period = PayrollPeriod(
            factory_code="MIL",
            period_no=f"PERF35-MIL-{marker}",
            name="PERF35 MIL period",
            start_date=start_date,
            end_date=start_date + timedelta(days=1),
            status="draft",
        )
        bst_period = PayrollPeriod(
            factory_code="BST",
            period_no=f"PERF35-BST-{marker}",
            name="PERF35 BST period",
            start_date=start_date,
            end_date=start_date + timedelta(days=1),
            status="draft",
        )
        db.add_all([mil_period, bst_period])
        db.commit()
        mil_period_id = int(mil_period.id)
        bst_period_id = int(bst_period.id)
        before = (db.query(PayrollPeriod).count(), db.query(AuditLog).count())

    legacy = client.get("/api/payroll/periods?status=draft", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert mil_period_id in {row["id"] for row in legacy.json()}
    assert bst_period_id not in {row["id"] for row in legacy.json()}

    response = client.get(
        "/api/payroll/periods?status=draft&page=1&page_size=50",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rows"] == legacy.json()[:50]
    assert payload["total"] == len(legacy.json())
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    assert payload["has_more"] is (payload["total"] > 50)

    assert client.get(
        "/api/payroll/periods?page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get("/api/payroll/periods?page=1&page_size=1").status_code == 401

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/payroll/periods?page=1&page_size=1",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with TestSessionLocal() as db:
        after = (db.query(PayrollPeriod).count(), db.query(AuditLog).count())
    assert after == before

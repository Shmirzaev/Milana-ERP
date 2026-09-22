from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.payroll import order_qr_status_orders
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, PayrollQrLabel, Role, User


def _seed_options(count: int, *, factory_code: str = "MIL") -> tuple[str, list[str]]:
    marker = f"PERF35-QR-{uuid4().hex}"
    with SessionLocal() as db:
        rows = [
            PayrollQrLabel(
                label_uid=f"{marker}-UID-{index:04d}",
                factory_code=factory_code,
                sales_order_no=f"{marker}-SO-{index:04d}",
                production_no=f"{marker}-PO-{index:04d}",
                model_code=f"MODEL-{index % 7}",
                issued_at=datetime(2095, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
            )
            for index in range(count)
        ]
        db.add_all(rows)
        if rows:
            db.add(PayrollQrLabel(
                label_uid=f"{marker}-UID-DUPLICATE",
                factory_code=factory_code,
                sales_order_no=rows[-1].sales_order_no,
                production_no=rows[-1].production_no,
                model_code=rows[-1].model_code,
                issued_at=rows[-1].issued_at,
            ))
        db.commit()
    return marker, [f"{marker}-SO-{index:04d}" for index in reversed(range(count))]


def _read(marker: str, **kwargs):
    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        _ = current.role, current.department
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = order_qr_status_orders(db, current, search=marker, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_order_option_page_bounds_sql_and_preserves_legacy_payload(row_count):
    marker, expected_order = _seed_options(row_count)

    legacy, legacy_statements = _read(marker)
    page, page_statements = _read(marker, page=1, page_size=50)

    expected_prefix = expected_order[:50]
    assert [row["order_no"] for row in legacy[:50]] == expected_prefix
    assert page["rows"] == legacy[:50]
    assert page["total"] == row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (row_count > 50)
    assert len(page["rows"]) <= 50
    assert len(legacy_statements) == 21, legacy_statements
    assert len(page_statements) == 23, page_statements
    assert all(statement.startswith("select") for statement in [*legacy_statements, *page_statements])
    legacy_list_statements = [statement for statement in legacy_statements if "payroll_qr_labels" in statement]
    page_list_statements = [statement for statement in page_statements if "payroll_qr_labels" in statement]
    assert len(legacy_list_statements) == 1
    assert len(page_list_statements) == 3
    page_statement = next(
        statement
        for statement in page_list_statements
        if " from (select payroll_qr_labels.sales_order_no" in statement and " limit ? offset ?" in statement
    )
    assert "group by" in page_statement
    assert "order by max(" in page_statement

    assert page["rows"][0]["label_count"] == 2


def test_order_option_page_contract_factory_auth_and_no_writes(client, auth_headers):
    marker, expected_order = _seed_options(3)
    other_marker, _ = _seed_options(1, factory_code="ECO")
    with SessionLocal() as db:
        denied_role = Role(name=f"Order option denied {uuid4().hex}", permissions=[])
        db.add(denied_role)
        db.flush()
        denied = User(
            name="Order option denied",
            email=f"order-option-denied-{uuid4().hex}@example.invalid",
            password_hash="unused-pagination-hash",
            role_id=denied_role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(denied)
        db.flush()
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied.id, {'factory_code': 'MIL'})}"}
        db.commit()
        before = (db.query(PayrollQrLabel).count(), db.query(AuditLog).count())

    legacy = client.get(
        "/api/payroll/reports/order-qr-status/orders",
        params={"search": marker},
        headers=auth_headers,
    )
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)

    paged = client.get(
        "/api/payroll/reports/order-qr-status/orders",
        params={"search": marker, "page": 2, "page_size": 2},
        headers=auth_headers,
    )
    assert paged.status_code == 200, paged.text
    payload = paged.json()
    assert payload["rows"] == legacy.json()[2:3]
    assert payload["rows"][0]["order_no"] == expected_order[2]
    assert payload["total"] == 3
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["has_more"] is False
    assert all(other_marker not in row["order_no"] for row in payload["rows"])

    assert client.get(
        "/api/payroll/reports/order-qr-status/orders",
        params={"search": marker, "page": 1, "page_size": 101},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/payroll/reports/order-qr-status/orders",
        params={"search": marker, "page": 1, "page_size": 2},
    ).status_code == 401
    assert client.get(
        "/api/payroll/reports/order-qr-status/orders",
        params={"search": marker, "page": 1, "page_size": 2},
        headers=denied_headers,
    ).status_code == 403

    with SessionLocal() as db:
        after = (db.query(PayrollQrLabel).count(), db.query(AuditLog).count())
    assert after == before

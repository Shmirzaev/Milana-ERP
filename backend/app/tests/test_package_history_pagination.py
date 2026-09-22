from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.packages import history
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Department, Model, Package, PackageScanLog, ProductionOrder, Role, User


def _seed_history(count: int) -> tuple[int, list[int]]:
    marker = uuid4().hex
    with SessionLocal() as db:
        model_id = int(db.query(Model.id).order_by(Model.id).first()[0])
        order = ProductionOrder(
            production_no=f"PERF35-PACKAGE-HISTORY-{marker}",
            production_type="branded_stock",
            model_id=model_id,
            planned_quantity=max(count, 1),
        )
        db.add(order)
        db.flush()
        package = Package(
            package_no=f"PERF35-PACKAGE-HISTORY-{marker}",
            barcode=f"PERF35-PACKAGE-HISTORY-BC-{marker}",
            packaging_department_code="PKG",
            production_order_id=order.id,
            model_id=model_id,
            color="Blue",
            total_quantity=max(count, 1),
            capacity=max(count, 1),
            status="packed",
        )
        db.add(package)
        db.flush()
        rows = [
            PackageScanLog(
                package_id=package.id,
                scan_type=f"bounded_{index:04d}",
                location=f"A-{index:04d}",
                scanned_at=datetime(2095, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
            )
            for index in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return int(package.id), [int(row.id) for row in rows]


def _read(package_id: int, **kwargs):
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
            payload = history(package_id, db, current, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_package_history_page_bounds_sql_and_preserves_legacy_payload(row_count):
    package_id, scan_ids = _seed_history(row_count)

    legacy, legacy_statements = _read(package_id)
    page, page_statements = _read(package_id, page=1, page_size=50)

    assert [row["id"] for row in legacy[:50]] == scan_ids[:50]
    assert page["rows"] == legacy[:50]
    assert page["total"] == row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (row_count > 50)
    assert len(page["rows"]) <= 50
    assert len(legacy_statements) == 2, legacy_statements
    assert len(page_statements) == 3, page_statements
    assert all(statement.startswith("select") for statement in [*legacy_statements, *page_statements])
    row_statement = next(
        statement
        for statement in page_statements
        if " from package_scan_logs " in statement and " limit ? offset ?" in statement
    )
    assert "package_scan_logs.package_id = ?" in row_statement
    assert "order by package_scan_logs.scanned_at asc, package_scan_logs.id asc" in row_statement


def test_package_history_page_contract_scope_auth_and_no_writes(client, auth_headers):
    package_id, scan_ids = _seed_history(3)
    with SessionLocal() as db:
        role = Role(name=f"Package history reader {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        eco_reader = User(
            name="ECO package history reader",
            email=f"package-history-{uuid4().hex}@example.invalid",
            password_hash="unused-pagination-hash",
            role_id=role.id,
            department_id=db.query(Department.id).filter(Department.code == "ECP").scalar(),
            factory_code="ECO",
            extra_permissions=[],
            is_active=True,
        )
        db.add(eco_reader)
        db.flush()
        eco_headers = {
            "Authorization": f"Bearer {create_access_token(eco_reader.id, {'factory_code': 'ECO'})}"
        }
        db.commit()
        before = (
            db.query(Package).count(),
            db.query(PackageScanLog).count(),
            db.query(AuditLog).count(),
        )

    legacy = client.get(f"/api/packages/{package_id}/history", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)

    paged = client.get(
        f"/api/packages/{package_id}/history",
        params={"page": 2, "page_size": 2},
        headers=auth_headers,
    )
    assert paged.status_code == 200, paged.text
    payload = paged.json()
    assert payload["rows"] == legacy.json()[2:3]
    assert payload["rows"][0]["id"] == scan_ids[2]
    assert payload["total"] == 3
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["has_more"] is False

    assert client.get(
        f"/api/packages/{package_id}/history",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        f"/api/packages/{package_id}/history",
        params={"page": 1, "page_size": 2},
    ).status_code == 401
    assert client.get(
        f"/api/packages/{package_id}/history",
        params={"page": 1, "page_size": 2},
        headers=eco_headers,
    ).status_code == 403
    missing = client.get(
        "/api/packages/2000000000/history",
        params={"page": 1, "page_size": 2},
        headers=auth_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Package not found"

    with SessionLocal() as db:
        after = (
            db.query(Package).count(),
            db.query(PackageScanLog).count(),
            db.query(AuditLog).count(),
        )
    assert after == before

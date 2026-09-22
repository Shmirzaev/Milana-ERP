from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.packages import list_package_change_requests
from app.db.session import SessionLocal
from app.models import AuditLog, Model, Package, PackageChangeRequest, ProductionOrder, User
from app.schemas.tracking import PackageChangeRequestOut


def _seed_requests(count: int) -> tuple[list[int], int]:
    marker = uuid4().hex
    with SessionLocal() as db:
        baseline = db.query(PackageChangeRequest).count()
        model_id = int(db.query(Model.id).order_by(Model.id).first()[0])
        order = ProductionOrder(
            production_no=f"PERF35-CHANGE-{marker}",
            production_type="branded_stock",
            model_id=model_id,
            planned_quantity=count,
        )
        db.add(order)
        db.flush()
        packages = [
            Package(
                package_no=f"PERF35-CHANGE-{marker}-{index:04d}",
                barcode=f"PERF35-CHANGE-BC-{marker}-{index:04d}",
                packaging_department_code="PKG",
                production_order_id=order.id,
                model_id=model_id,
                color="Blue",
                total_quantity=1,
                capacity=60,
                status="packed",
            )
            for index in range(count)
        ]
        db.add_all(packages)
        db.flush()
        requests = [
            PackageChangeRequest(
                package_id=package.id,
                package_no=package.package_no,
                request_type="edit",
                status="pending",
                before_json={"notes": None},
                payload_json={"notes": f"bounded-{index:04d}"},
                reason=f"pagination {index:04d}",
                requested_by=1,
            )
            for index, package in enumerate(packages)
        ]
        db.add_all(requests)
        db.commit()
        return [int(request.id) for request in requests], baseline


def _read(**kwargs):
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
            payload = list_package_change_requests(db, current, status="all", **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


def _payload(rows: list[PackageChangeRequest]) -> list[dict]:
    return [PackageChangeRequestOut.model_validate(row).model_dump(mode="json") for row in rows]


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_change_request_page_bounds_sql_and_preserves_legacy_payload(row_count):
    created_ids, baseline = _seed_requests(row_count)

    legacy, legacy_statements = _read()
    page, page_statements = _read(page=1, page_size=50)

    expected_ids = list(reversed(created_ids))[:50]
    assert [row.id for row in page["rows"]][: len(expected_ids)] == expected_ids
    assert _payload(page["rows"]) == _payload(legacy[:50])
    assert page["total"] == baseline + row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is ((baseline + row_count) > 50)
    assert len(page["rows"]) <= 50
    assert len(legacy_statements) == 1, legacy_statements
    assert len(page_statements) == 2, page_statements
    row_statement = next(statement for statement in page_statements if " limit ? offset ?" in statement)
    assert " join packages " in row_statement
    assert " order by package_change_requests.id desc" in row_statement
    assert " limit ? offset ?" in row_statement


def test_change_request_page_contract_scope_auth_and_no_writes(client, auth_headers):
    created_ids, baseline = _seed_requests(3)
    with SessionLocal() as db:
        before = (
            db.query(Package).count(),
            db.query(PackageChangeRequest).count(),
            db.query(AuditLog).count(),
        )

    legacy = client.get(
        "/api/packages/change-requests",
        params={"status": "all"},
        headers=auth_headers,
    )
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)

    paged = client.get(
        "/api/packages/change-requests",
        params={"status": "all", "page": 2, "page_size": 2},
        headers=auth_headers,
    )
    assert paged.status_code == 200, paged.text
    payload = paged.json()
    assert payload["total"] == baseline + 3
    assert payload["rows"] == legacy.json()[2:4]
    assert payload["rows"][0]["id"] == created_ids[0]
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert payload["has_more"] is (baseline + 3 > 4)

    assert client.get(
        "/api/packages/change-requests",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/packages/change-requests",
        params={"status": "all", "page": 1, "page_size": 2, "packaging_department_code": "BPK"},
        headers=auth_headers,
    ).status_code == 403
    assert client.get(
        "/api/packages/change-requests",
        params={"page": 1, "page_size": 2},
    ).status_code == 401

    with SessionLocal() as db:
        after = (
            db.query(Package).count(),
            db.query(PackageChangeRequest).count(),
            db.query(AuditLog).count(),
        )
    assert after == before

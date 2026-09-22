"""Print-run listing batches children without weakening manifest checks."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.core.security import create_access_token
from app.models import Department, PackagePrintRun, PackagePrintRunMember, Role, User
from app.services.package_workflows import run_payload
from app.tests.conftest import TestSessionLocal, test_engine


def _seed_runs(count):
    marker = uuid4().hex[:10]
    ids = []
    with TestSessionLocal() as db:
        user_id = db.query(User.id).first()[0]
        for index in range(count):
            # Members retain historical identities without a Package FK.
            package_ids = [100000 + index * 2, 100001 + index * 2]
            run = PackagePrintRun(
                run_no=f"PERF-{marker}-{index}", code=f"PACKRUN:{marker}-{index}",
                packaging_department_code="PKG", created_by=user_id,
                package_ids=package_ids, deleted_package_ids=[package_ids[0]],
                created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
            db.add(run)
            db.flush()
            ids.append(run.id)
            for package_id in package_ids:
                db.add(PackagePrintRunMember(
                    run_id=run.id, package_id=package_id,
                    snapshot={"quantity": 3, "manual_receipt_id": 1},
                ))
        db.commit()
    return ids


@pytest.mark.parametrize("count", [1, 10, 50, 101])
def test_print_run_member_queries_are_bounded(client, auth_headers, count):
    ids = _seed_runs(count)
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get("/api/packages/print-runs", headers=auth_headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["id"] for row in rows] == list(reversed(ids))[:100]
    assert all(row["count"] == 1 and row["quantity"] == 3 for row in rows)
    assert all(row["manual_receipt"] is True for row in rows)
    assert all(len(row["package_ids"]) == len(row["packages"]) == 1 for row in rows)
    member_reads = [sql for sql in statements if "FROM package_print_run_members" in sql]
    print(f"Print runs {count}: {len(statements)} SELECTs, {len(member_reads)} member reads")
    assert len(member_reads) == 1


@pytest.mark.parametrize("count", [1, 50, 401])
def test_print_run_pages_preserve_legacy_order_and_bound_member_reads(client, auth_headers, count):
    ids = _seed_runs(count)
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get("/api/packages/print-runs?page=1&page_size=50", headers=auth_headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    legacy = client.get("/api/packages/print-runs", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert legacy.status_code == 200, legacy.text
    page = response.json()
    returned_count = min(count, 50)
    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page["rows"]] == list(reversed(ids))[:returned_count]
    assert page["rows"] == legacy.json()[:returned_count]
    assert len(statements) == 4, statements
    member_reads = [statement for statement in statements if " from package_print_run_members " in statement]
    assert len(member_reads) == 1
    assert member_reads[0].count("?") == returned_count


def test_print_run_page_size_is_bounded(client, auth_headers):
    response = client.get("/api/packages/print-runs?page_size=101", headers=auth_headers)
    assert response.status_code == 422, response.text


def test_print_run_list_rejects_corrupt_manifest(client, auth_headers):
    [run_id] = _seed_runs(1)
    with TestSessionLocal() as db:
        db.get(PackagePrintRun, run_id).package_ids = [999999]
        db.commit()
    response = client.get("/api/packages/print-runs", headers=auth_headers)
    assert response.status_code == 409


def test_print_run_list_excludes_retired_runs_and_requires_login(client, auth_headers):
    [run_id] = _seed_runs(1)
    with TestSessionLocal() as db:
        db.get(PackagePrintRun, run_id).deleted_at = datetime.now(timezone.utc)
        db.commit()
    assert client.get("/api/packages/print-runs").status_code == 401
    response = client.get("/api/packages/print-runs", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_print_run_list_preserves_factory_filter_and_single_payload(client):
    own_id, other_id = _seed_runs(2)
    with TestSessionLocal() as db:
        other = db.get(PackagePrintRun, other_id)
        other.packaging_department_code = "ECP"
        # Invisible corrupt data must not be loaded/validated for this factory.
        other.package_ids = [999999]
        role = Role(name="Print run performance reader", permissions=["packaging.records"])
        db.add(role)
        db.flush()
        user = User(
            name="Synthetic packaging reader", email="print-perf@example.invalid",
            password_hash="unused", role_id=role.id,
            department_id=db.query(Department.id).filter_by(code="PKG").scalar(),
            factory_code="MIL",
        )
        db.add(user)
        db.flush()
        token = create_access_token(user.id, {"factory_code": "MIL"})
        db.commit()
        expected = run_payload(db, db.get(PackagePrintRun, own_id))
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/packages/print-runs", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == [expected]
    filtered = client.get("/api/packages/print-runs?production_order_id=2147483647", headers=headers)
    assert filtered.status_code == 200
    assert filtered.json() == []
    filtered_page = client.get(
        "/api/packages/print-runs?production_order_id=2147483647&page=1&page_size=50",
        headers=headers,
    )
    assert filtered_page.status_code == 200
    assert filtered_page.json() == {
        "rows": [],
        "total": 0,
        "page": 1,
        "page_size": 50,
        "has_more": False,
    }
